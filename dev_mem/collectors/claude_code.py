"""
dev_mem.collectors.claude_code — PostToolUse hook handler for Claude Code.

Claude Code pipes a JSON payload to stdin when a tool finishes:

    {
        "tool":       "Bash",
        "input":      {...},
        "output":     {...},
        "session_id": "abc123",
        "ts":         "2024-01-01T00:00:00Z"
    }

This module reads stdin, records the event, detects errors, and captures
prompts.  Hard deadline: 50 ms.
"""

from __future__ import annotations

import json
import os
import re
import signal
import sys
import threading
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Hard timeout: 50 ms
# ---------------------------------------------------------------------------

_TIMEOUT_SECONDS = 0.050

# Maximum characters kept for input/output summaries
_SUMMARY_MAX = 500

# Patterns indicating an error in output
_ERROR_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bError\b", re.IGNORECASE),
    re.compile(r"Traceback \(most recent call last\)"),
    re.compile(r"\bException\b", re.IGNORECASE),
    re.compile(r"\bFAILED\b"),
    re.compile(r"\bexit code [1-9]\d*\b", re.IGNORECASE),
    re.compile(r"returncode=[1-9]\d*"),
]

# Tool names that carry the user's prompt text
_PROMPT_TOOLS: frozenset[str] = frozenset(
    {"UserMessage", "user_message", "HumanTurn", "human_turn"}
)


def _self_kill() -> None:  # pragma: no cover
    os.kill(os.getpid(), signal.SIGKILL)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _truncate(text: str, max_len: int = _SUMMARY_MAX) -> str:
    return text if len(text) <= max_len else text[:max_len] + "…"


def _to_str(obj: Any) -> str:
    """Flatten any JSON value to a plain string."""
    if isinstance(obj, str):
        return obj
    try:
        return json.dumps(obj, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(obj)


def _detect_error(text: str) -> Optional[str]:
    """
    Scan *text* for error indicators.

    Returns a short excerpt centred on the first match, or None.
    """
    for pattern in _ERROR_PATTERNS:
        m = pattern.search(text)
        if m:
            start = max(0, m.start() - 40)
            end = min(len(text), m.end() + 120)
            return text[start:end].strip()
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    timer = threading.Timer(_TIMEOUT_SECONDS, _self_kill)
    timer.daemon = True
    timer.start()
    try:
        _run()
    finally:
        timer.cancel()


def _run() -> None:
    # Read and parse stdin
    try:
        raw = sys.stdin.read()
        payload: dict[str, Any] = json.loads(raw)
    except (json.JSONDecodeError, OSError):
        return

    tool: str = payload.get("tool", "")
    session_id: str = payload.get("session_id", "")
    input_obj: Any = payload.get("input", {})
    output_obj: Any = payload.get("output", {})

    input_summary = _truncate(_to_str(input_obj))
    output_summary = _truncate(_to_str(output_obj))

    from dev_mem.db import Database
    from dev_mem.settings import DB_PATH

    db = Database(DB_PATH)
    try:
        # Auto-detect project from cwd
        project_id: Optional[int] = None
        row = db.get_project_by_path(os.getcwd())
        if row:
            project_id = row["id"]

        # Detect errors in the full output string (before truncation)
        full_output = _to_str(output_obj)
        error_excerpt = _detect_error(full_output)
        has_error = error_excerpt is not None

        db.insert_claude_session(
            project_id=project_id,
            tool=tool,
            input_summary=input_summary,
            output_summary=output_summary,
            session_id=session_id,
        )

        if has_error and error_excerpt:
            db.upsert_error(
                project_id=project_id,
                error_text=_truncate(error_excerpt, 300),
            )

        # Capture prompt text when the tool is a user-message variant
        if tool in _PROMPT_TOOLS:
            prompt_text = ""
            if isinstance(input_obj, dict):
                prompt_text = str(
                    input_obj.get("content")
                    or input_obj.get("message")
                    or input_obj.get("text")
                    or ""
                )
            elif isinstance(input_obj, str):
                prompt_text = input_obj

            if prompt_text:
                db.insert_prompt(
                    project_id=project_id,
                    text=_truncate(prompt_text),
                    source="claude_code",
                )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Module entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    main()
