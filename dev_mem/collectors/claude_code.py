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

_TIMEOUT_SECONDS = 0.500

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

    # Claude Code sends tool_name/tool_input/tool_response (PostToolUse format)
    tool: str = payload.get("tool_name") or payload.get("tool", "")
    session_id: str = payload.get("session_id", "")
    input_obj: Any = payload.get("tool_input") or payload.get("input", {})
    output_obj: Any = payload.get("tool_response") or payload.get("output", {})

    input_summary = _truncate(_to_str(input_obj))
    output_summary = _truncate(_to_str(output_obj))

    # memory_session_id: prefer env var (set by Claude Code), fall back to payload
    memory_session_id: str = os.environ.get("CLAUDE_SESSION_ID") or session_id

    from dev_mem.db import Database
    from dev_mem.settings import DB_PATH, Settings

    settings = Settings()
    db = Database(DB_PATH)
    try:
        # Auto-detect project from cwd
        project_id: Optional[int] = None
        project_name: str = ""
        cwd = os.getcwd()
        row = db.get_project_by_path(cwd)
        if row:
            project_id = row["id"]
            project_name = row["name"] if "name" in row.keys() else ""

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

        # ------------------------------------------------------------------
        # Agent / Skill invocation tracking
        # ------------------------------------------------------------------
        if tool in ("Agent", "Skill") and memory_session_id:
            _record_agent_skill(
                conn=db._conn,
                tool=tool,
                input_obj=input_obj,
                memory_session_id=memory_session_id,
                project_id=project_id,
                project_name=project_name,
            )

        # ------------------------------------------------------------------
        # Memory subsystem: session tracking + observation generation
        # ------------------------------------------------------------------
        if memory_session_id and settings.get("observations_enabled", True):
            _record_memory(
                conn=db._conn,
                tool=tool,
                input_obj=input_obj,
                output_obj=output_obj,
                memory_session_id=memory_session_id,
                project_id=project_id,
                project_name=project_name,
                cwd=cwd,
                settings=settings,
            )

    finally:
        db.close()


def _record_agent_skill(
    conn: Any,
    tool: str,
    input_obj: Any,
    memory_session_id: str,
    project_id: Optional[int],
    project_name: str,
) -> None:
    """
    Record an Agent or Skill invocation in agent_skill_calls table.
    Runs inside the 50 ms budget; errors are swallowed silently.
    """
    from datetime import datetime, timezone

    try:
        now_iso = datetime.now(timezone.utc).isoformat()
        call_type = tool.lower()  # "agent" or "skill"
        name = ""
        description = ""
        args = ""
        is_background = 0

        if isinstance(input_obj, dict):
            if tool == "Agent":
                name = str(input_obj.get("subagent_type") or input_obj.get("name") or "")
                description = str(input_obj.get("description") or input_obj.get("prompt", "")[:200])
                is_background = int(bool(input_obj.get("run_in_background", False)))
            elif tool == "Skill":
                name = str(input_obj.get("skill") or "")
                args = str(input_obj.get("args") or "")[:200]

        if not name:
            return

        conn.execute(
            """
            INSERT INTO agent_skill_calls
                (memory_session_id, project_id, project, call_type, name,
                 description, args, is_background, ts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (memory_session_id, project_id, project_name, call_type,
             name, description, args, is_background, now_iso),
        )
        conn.commit()
    except Exception:  # noqa: BLE001
        pass


def _record_memory(
    conn: Any,
    tool: str,
    input_obj: Any,
    output_obj: Any,
    memory_session_id: str,
    project_id: Optional[int],
    project_name: str,
    cwd: str,
    settings: Any,
) -> None:
    """
    Track session + generate observations.  Runs inside the 50 ms budget.
    All errors are swallowed — memory must never block the workflow.
    """
    try:
        from dev_mem.memory.session_tracker import (
            get_or_create_session,
            increment_session_tool_count,
            increment_session_obs_count,
        )
        from dev_mem.memory.observations import generate_observation_from_tool_call, insert_observation

        # Ensure session row exists
        get_or_create_session(conn, memory_session_id, project_id, project_name, cwd)
        increment_session_tool_count(conn, memory_session_id)

        # Generate observation
        obs_tools = settings.get("observations_obs_tools", ["Read", "Write", "Edit", "Bash", "MultiEdit"])
        if tool not in obs_tools:
            return

        min_chars = settings.get("observations_min_output_chars", 100)
        obs_kwargs = generate_observation_from_tool_call(
            tool, input_obj, output_obj, min_output_chars=min_chars
        )
        if obs_kwargs is None:
            return

        insert_observation(
            conn,
            **obs_kwargs,
            project=project_name,
            project_id=project_id,
            session_id=memory_session_id,
            memory_session_id=memory_session_id,
        )
        increment_session_obs_count(conn, memory_session_id)

    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# Module entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    main()
