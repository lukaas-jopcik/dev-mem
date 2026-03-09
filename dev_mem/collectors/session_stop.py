"""
dev_mem.collectors.session_stop — Stop hook for Claude Code.

On session end:
1. Marks the session as completed in claude_code_sessions
2. Builds a smart session summary from observations (files, decisions, fixes)
3. Extracts learnings into the learnings table

Hard timeout: 8 seconds.
"""

from __future__ import annotations

import json
import os
import signal
import sqlite3
import sys
import threading


_TIMEOUT_SECONDS = 8.0


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
    from dev_mem.memory.session_tracker import (
        complete_session,
        build_session_summary,
        extract_learnings,
    )

    settings = Settings()
    db_path = settings.db_path
    if not db_path.exists():
        return

    conn = sqlite3.connect(str(db_path), timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")

    try:
        session_row = conn.execute(
            "SELECT * FROM claude_code_sessions WHERE memory_session_id = ?",
            (memory_session_id,),
        ).fetchone()
        project_id = session_row["project_id"] if session_row else None

        complete_session(conn, memory_session_id)
        build_session_summary(conn, memory_session_id, project_id)
        n_learnings = extract_learnings(conn, memory_session_id, project_id)

        # Write a brief status to stderr (visible in Claude Code logs)
        if n_learnings > 0:
            print(f"[dev-mem] session saved · {n_learnings} learnings extracted", file=sys.stderr)

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
