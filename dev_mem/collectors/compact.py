"""
dev_mem.collectors.compact — PreCompact hook for Claude Code.

Runs before Claude compresses the context window. Saves the current
session state so that the next session start has up-to-date context
without needing to re-read all history.

Hard timeout: 5 seconds.
"""

from __future__ import annotations

import json
import os
import signal
import sqlite3
import sys
import threading
from pathlib import Path


_TIMEOUT_SECONDS = 5.0


def _self_kill() -> None:  # pragma: no cover
    os.kill(os.getpid(), signal.SIGKILL)


def _run() -> None:
    try:
        raw = sys.stdin.read()
        payload: dict = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, OSError):
        payload = {}

    memory_session_id = (
        payload.get("session_id")
        or payload.get("memory_session_id")
        or os.environ.get("CLAUDE_SESSION_ID")
        or ""
    )

    if not memory_session_id:
        return

    from dev_mem.settings import Settings
    from dev_mem.memory.session_tracker import build_session_summary, extract_learnings
    from dev_mem.memory.context_injector import write_project_memory_md

    settings = Settings()
    db_path = settings.db_path
    if not db_path.exists():
        return

    conn = sqlite3.connect(str(db_path), timeout=4.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")

    try:
        session_row = conn.execute(
            "SELECT * FROM claude_code_sessions WHERE memory_session_id = ?",
            (memory_session_id,),
        ).fetchone()
        project_id = session_row["project_id"] if session_row else None

        # Check if we already have a summary for this session
        existing = conn.execute(
            "SELECT id FROM session_summaries WHERE memory_session_id = ? LIMIT 1",
            (memory_session_id,),
        ).fetchone()

        if not existing:
            # First compact — build initial summary
            build_session_summary(conn, memory_session_id, project_id)
            extract_learnings(conn, memory_session_id, project_id)
        else:
            # Subsequent compact — update the existing summary with fresh observations
            # (observations added since last summary)
            last_summary_time = conn.execute(
                "SELECT MAX(created_at) AS t FROM session_summaries WHERE memory_session_id = ?",
                (memory_session_id,),
            ).fetchone()["t"] or ""

            new_obs = conn.execute(
                "SELECT COUNT(*) AS n FROM observations "
                "WHERE memory_session_id = ? AND created_at > ?",
                (memory_session_id, last_summary_time),
            ).fetchone()["n"]

            if new_obs > 0:
                # Rebuild to capture new observations
                build_session_summary(conn, memory_session_id, project_id)
                extract_learnings(conn, memory_session_id, project_id)

        # Write to Claude Code's persistent memory dir so context survives resets
        cwd = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
        project_name = (session_row["project"] if session_row else "") or Path(cwd).name
        write_project_memory_md(conn, project_name, project_id, cwd)

        print("[dev-mem] compact: session state saved", file=sys.stderr)

    except Exception:  # noqa: BLE001
        pass
    finally:
        conn.close()


def main() -> None:
    timer = threading.Timer(_TIMEOUT_SECONDS, _self_kill)
    timer.daemon = True
    timer.start()
    try:
        _run()
    except Exception:  # noqa: BLE001
        pass
    finally:
        timer.cancel()


if __name__ == "__main__":
    main()
