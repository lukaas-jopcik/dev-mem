"""
dev_mem.collectors.user_prompt — UserPromptSubmit hook for Claude Code.

Fires before every user message. Two jobs:

1. Inject a compact 1-line context reminder so Claude has project context
   even after context window resets (not just at SessionStart).

2. If the transcript file is getting large (approaching context limit),
   output a /compact suggestion before Claude hits the wall.

Hard timeout: 300ms — must not slow down the conversation.
"""

from __future__ import annotations

import json
import os
import signal
import sqlite3
import sys
import threading
from pathlib import Path
from typing import Optional

_TIMEOUT_SECONDS = 0.3

# Transcript size thresholds
_COMPACT_WARN_BYTES = 180_000   # ~45k tokens — suggest compact
_COMPACT_URGENT_BYTES = 280_000  # ~70k tokens — more insistent


def _self_kill() -> None:  # pragma: no cover
    os.kill(os.getpid(), signal.SIGKILL)


def _run() -> None:
    try:
        raw = sys.stdin.read()
        payload: dict = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, OSError):
        payload = {}

    session_id = (
        payload.get("session_id")
        or os.environ.get("CLAUDE_SESSION_ID")
        or ""
    )
    transcript_path = payload.get("transcript_path", "")

    # ── 1. Check transcript size for early compact suggestion ────────────
    compact_hint = ""
    if transcript_path:
        try:
            size = Path(transcript_path).stat().st_size
            if size >= _COMPACT_URGENT_BYTES:
                compact_hint = (
                    f"\n[dev-mem: transcript is {size // 1024}KB — "
                    "context limit approaching, consider /compact now]"
                )
            elif size >= _COMPACT_WARN_BYTES:
                compact_hint = (
                    f"\n[dev-mem: transcript is {size // 1024}KB — "
                    "context window getting large, /compact when convenient]"
                )
        except OSError:
            pass

    # ── 2. Mini context reminder from DB ────────────────────────────────
    if not session_id:
        if compact_hint:
            print(compact_hint.strip(), flush=True)
        return

    try:
        from dev_mem.settings import Settings
        settings = Settings()
        db_path = settings.db_path
        if not db_path.exists():
            if compact_hint:
                print(compact_hint.strip(), flush=True)
            return

        conn = sqlite3.connect(str(db_path), timeout=0.2)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA query_only=1")

        try:
            # Get project from session
            sess = conn.execute(
                "SELECT project, project_id FROM claude_code_sessions "
                "WHERE memory_session_id = ? LIMIT 1",
                (session_id,),
            ).fetchone()

            if not sess:
                if compact_hint:
                    print(compact_hint.strip(), flush=True)
                return

            project = sess["project"] or ""
            project_id: Optional[int] = sess["project_id"]

            # Get most recent session summary (not the current session)
            summary = None
            if project_id is not None:
                summary = conn.execute(
                    "SELECT created_at, completed, learned FROM session_summaries "
                    "WHERE project_id = ? AND memory_session_id != ? "
                    "ORDER BY created_at DESC LIMIT 1",
                    (project_id, session_id),
                ).fetchone()
            if not summary:
                summary = conn.execute(
                    "SELECT created_at, completed, learned FROM session_summaries "
                    "WHERE memory_session_id != ? "
                    "AND (completed != '' OR learned != '') "
                    "ORDER BY created_at DESC LIMIT 1",
                    (session_id,),
                ).fetchone()

            if not summary:
                if compact_hint:
                    print(compact_hint.strip(), flush=True)
                return

            date = (summary["created_at"] or "")[:10]
            completed = (summary["completed"] or "")[:80]
            learned_first = ""
            if summary["learned"]:
                learned_first = summary["learned"].split("\n")[0][:80]

            parts = [f'project="{project}"', f'last-session="{date}"']
            if completed:
                parts.append(f'done="{completed}"')
            if learned_first:
                parts.append(f'learned="{learned_first}"')

            reminder = "<dev-mem " + " ".join(parts) + " />"
            print(reminder + compact_hint, flush=True)

        finally:
            conn.close()

    except Exception:
        if compact_hint:
            try:
                print(compact_hint.strip(), flush=True)
            except Exception:
                pass


def main() -> None:
    timer = threading.Timer(_TIMEOUT_SECONDS, _self_kill)
    timer.daemon = True
    timer.start()
    try:
        _run()
    except Exception:
        pass
    finally:
        timer.cancel()


if __name__ == "__main__":
    main()
