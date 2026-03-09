"""
migrations/004_agent_skill_calls.py — Agent and Skill invocation tracking.

Adds the agent_skill_calls table to track Claude Code Agent and Skill tool
invocations with structured columns for efficient analytics queries.
"""

from __future__ import annotations

import sqlite3

VERSION = 4
DESCRIPTION = "Add agent_skill_calls table for Agent/Skill usage analytics"


def up(db_conn: sqlite3.Connection) -> None:
    cur = db_conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS agent_skill_calls (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_session_id   TEXT    NOT NULL DEFAULT '',
            project_id          INTEGER,
            project             TEXT    NOT NULL DEFAULT '',
            call_type           TEXT    NOT NULL DEFAULT 'agent',
            name                TEXT    NOT NULL DEFAULT '',
            description         TEXT    NOT NULL DEFAULT '',
            args                TEXT    NOT NULL DEFAULT '',
            is_background       INTEGER NOT NULL DEFAULT 0,
            ts                  TEXT    NOT NULL
        )
    """)

    cur.execute("CREATE INDEX IF NOT EXISTS idx_asc_call_type_name ON agent_skill_calls(call_type, name)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_asc_ts ON agent_skill_calls(ts)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_asc_project_id ON agent_skill_calls(project_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_asc_session ON agent_skill_calls(memory_session_id)")

    db_conn.commit()
