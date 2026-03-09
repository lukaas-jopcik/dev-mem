"""
migrations/005_token_tracking.py — Token usage tracking.

Adds context_injected_chars to claude_code_sessions so we can measure
actual context injection size per session and compute token savings.
"""

from __future__ import annotations

import sqlite3

VERSION = 5
DESCRIPTION = "Add context_injected_chars to claude_code_sessions for token savings tracking"


def up(db_conn: sqlite3.Connection) -> None:
    cur = db_conn.cursor()

    # Add column (safe to run if already exists)
    try:
        cur.execute(
            "ALTER TABLE claude_code_sessions ADD COLUMN context_injected_chars INTEGER DEFAULT 0"
        )
    except sqlite3.OperationalError:
        pass  # column already exists

    try:
        cur.execute(
            "ALTER TABLE claude_code_sessions ADD COLUMN context_had_prior_sessions INTEGER DEFAULT 0"
        )
    except sqlite3.OperationalError:
        pass

    db_conn.commit()
