"""
migrations/002_memory.py — Observations, claude_code_sessions, session_summaries.

Adds the memory subsystem tables used by the claude-mem 2-in-1 integration.
"""

from __future__ import annotations

import sqlite3


VERSION = 2
DESCRIPTION = "Add observations, claude_code_sessions, session_summaries tables"


def up(db_conn: sqlite3.Connection) -> None:
    cur = db_conn.cursor()

    # ------------------------------------------------------------------
    # observations
    # ------------------------------------------------------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS observations (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            title               TEXT    NOT NULL DEFAULT '',
            type                TEXT    NOT NULL DEFAULT 'discovery',
            text                TEXT    NOT NULL DEFAULT '',
            narrative           TEXT    NOT NULL DEFAULT '',
            subtitle            TEXT    NOT NULL DEFAULT '',
            facts               TEXT    NOT NULL DEFAULT '[]',
            concepts            TEXT    NOT NULL DEFAULT '[]',
            project             TEXT    NOT NULL DEFAULT '',
            project_id          INTEGER REFERENCES projects(id),
            session_id          TEXT    NOT NULL DEFAULT '',
            memory_session_id   TEXT    NOT NULL DEFAULT '',
            files_read          TEXT    NOT NULL DEFAULT '[]',
            files_modified      TEXT    NOT NULL DEFAULT '[]',
            prompt_number       INTEGER,
            discovery_tokens    INTEGER,
            created_at          TEXT    NOT NULL DEFAULT '',
            created_at_epoch    INTEGER NOT NULL DEFAULT 0
        )
    """)

    # FTS5 virtual table
    cur.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS observations_fts
        USING fts5(
            title,
            narrative,
            text,
            facts,
            content='observations',
            content_rowid='id'
        )
    """)

    # Sync triggers
    cur.execute("""
        CREATE TRIGGER IF NOT EXISTS obs_fts_insert AFTER INSERT ON observations BEGIN
            INSERT INTO observations_fts(rowid, title, narrative, text, facts)
            VALUES (new.id, new.title, new.narrative, new.text, new.facts);
        END
    """)
    cur.execute("""
        CREATE TRIGGER IF NOT EXISTS obs_fts_update AFTER UPDATE ON observations BEGIN
            INSERT INTO observations_fts(observations_fts, rowid, title, narrative, text, facts)
            VALUES ('delete', old.id, old.title, old.narrative, old.text, old.facts);
            INSERT INTO observations_fts(rowid, title, narrative, text, facts)
            VALUES (new.id, new.title, new.narrative, new.text, new.facts);
        END
    """)
    cur.execute("""
        CREATE TRIGGER IF NOT EXISTS obs_fts_delete AFTER DELETE ON observations BEGIN
            INSERT INTO observations_fts(observations_fts, rowid, title, narrative, text, facts)
            VALUES ('delete', old.id, old.title, old.narrative, old.text, old.facts);
        END
    """)

    # Indexes
    cur.execute("CREATE INDEX IF NOT EXISTS idx_observations_project ON observations(project)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_observations_project_id ON observations(project_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_observations_session ON observations(memory_session_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_observations_type ON observations(type)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_observations_epoch ON observations(created_at_epoch DESC)")

    # ------------------------------------------------------------------
    # claude_code_sessions
    # ------------------------------------------------------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS claude_code_sessions (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_session_id TEXT    UNIQUE NOT NULL,
            project_id        INTEGER REFERENCES projects(id),
            project           TEXT    NOT NULL DEFAULT '',
            cwd               TEXT    NOT NULL DEFAULT '',
            started_at        TEXT    NOT NULL DEFAULT '',
            ended_at          TEXT,
            tool_call_count   INTEGER NOT NULL DEFAULT 0,
            observation_count INTEGER NOT NULL DEFAULT 0,
            status            TEXT    NOT NULL DEFAULT 'active'
        )
    """)
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_cc_sessions_msid "
        "ON claude_code_sessions(memory_session_id)"
    )

    # ------------------------------------------------------------------
    # session_summaries
    # ------------------------------------------------------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS session_summaries (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_session_id TEXT    NOT NULL REFERENCES claude_code_sessions(memory_session_id),
            project_id        INTEGER REFERENCES projects(id),
            request           TEXT    NOT NULL DEFAULT '',
            investigated      TEXT    NOT NULL DEFAULT '',
            learned           TEXT    NOT NULL DEFAULT '',
            completed         TEXT    NOT NULL DEFAULT '',
            next_steps        TEXT    NOT NULL DEFAULT '',
            files_read        TEXT    NOT NULL DEFAULT '',
            files_edited      TEXT    NOT NULL DEFAULT '',
            created_at        TEXT    NOT NULL DEFAULT ''
        )
    """)
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_session_summaries_msid "
        "ON session_summaries(memory_session_id)"
    )

    db_conn.commit()


def down(db_conn: sqlite3.Connection) -> None:
    cur = db_conn.cursor()
    cur.execute("DROP TRIGGER IF EXISTS obs_fts_delete")
    cur.execute("DROP TRIGGER IF EXISTS obs_fts_update")
    cur.execute("DROP TRIGGER IF EXISTS obs_fts_insert")
    cur.execute("DROP TABLE IF EXISTS observations_fts")
    cur.execute("DROP TABLE IF EXISTS session_summaries")
    cur.execute("DROP TABLE IF EXISTS claude_code_sessions")
    cur.execute("DROP TABLE IF EXISTS observations")
    db_conn.commit()
