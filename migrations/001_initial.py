"""
001_initial.py — Initial migration for dev-mem.

up()   ensures the base schema exists (idempotent — safe to run multiple times).
down() drops all managed tables for a clean rollback.
"""

from __future__ import annotations

import sqlite3

VERSION: int = 1
DESCRIPTION: str = "Initial schema"

# Tables in dependency order (children before parents for DROP)
_ALL_TABLES = [
    "daily_summaries",
    "analyses",
    "decisions",
    "learnings",
    "prompts",
    "errors",
    "claude_sessions",
    "file_events",
    "git_events",
    "commands",
    "sessions",
    "projects",
    "schema_versions",
]

_DDL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS schema_versions (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT    NOT NULL,
    description TEXT    NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS projects (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT    NOT NULL,
    path       TEXT    NOT NULL UNIQUE,
    color      TEXT    NOT NULL DEFAULT '#6366f1',
    active     INTEGER NOT NULL DEFAULT 1,
    created_at TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id   INTEGER REFERENCES projects(id),
    start_ts     TEXT    NOT NULL,
    end_ts       TEXT,
    duration_sec INTEGER
);

CREATE TABLE IF NOT EXISTS commands (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER REFERENCES projects(id),
    cmd_hash    TEXT    NOT NULL,
    cmd         TEXT    NOT NULL,
    ts          TEXT    NOT NULL,
    duration_ms INTEGER,
    exit_code   INTEGER
);

CREATE TABLE IF NOT EXISTS git_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER REFERENCES projects(id),
    hash        TEXT    NOT NULL UNIQUE,
    message     TEXT    NOT NULL,
    files_json  TEXT    NOT NULL DEFAULT '[]',
    insertions  INTEGER NOT NULL DEFAULT 0,
    deletions   INTEGER NOT NULL DEFAULT 0,
    ts          TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS file_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER REFERENCES projects(id),
    path       TEXT    NOT NULL,
    action     TEXT    NOT NULL,
    ts         TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS claude_sessions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id     INTEGER REFERENCES projects(id),
    tool           TEXT    NOT NULL DEFAULT '',
    input_summary  TEXT    NOT NULL DEFAULT '',
    output_summary TEXT    NOT NULL DEFAULT '',
    session_id     TEXT    NOT NULL DEFAULT '',
    ts             TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS errors (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER REFERENCES projects(id),
    error_text  TEXT    NOT NULL,
    error_hash  TEXT    NOT NULL,
    count       INTEGER NOT NULL DEFAULT 1,
    first_seen  TEXT    NOT NULL,
    last_seen   TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS prompts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER REFERENCES projects(id),
    text       TEXT    NOT NULL,
    source     TEXT    NOT NULL DEFAULT '',
    score      INTEGER NOT NULL DEFAULT 0,
    tags       TEXT    NOT NULL DEFAULT '[]',
    ts         TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS learnings (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER REFERENCES projects(id),
    text       TEXT    NOT NULL,
    type       TEXT    NOT NULL DEFAULT '',
    source     TEXT    NOT NULL DEFAULT '',
    ts         TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS decisions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id   INTEGER REFERENCES projects(id),
    title        TEXT    NOT NULL,
    context      TEXT    NOT NULL DEFAULT '',
    reasoning    TEXT    NOT NULL DEFAULT '',
    alternatives TEXT    NOT NULL DEFAULT '',
    ts           TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS analyses (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id   INTEGER REFERENCES projects(id),
    type         TEXT    NOT NULL,
    content      TEXT    NOT NULL DEFAULT '',
    context_file TEXT    NOT NULL DEFAULT '',
    ts           TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS daily_summaries (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id   INTEGER REFERENCES projects(id),
    date         TEXT    NOT NULL,
    md_content   TEXT    NOT NULL DEFAULT '',
    generated_at TEXT    NOT NULL,
    UNIQUE(project_id, date)
);
"""

_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_commands_project_ts    ON commands(project_id, ts);
CREATE INDEX IF NOT EXISTS idx_commands_hash          ON commands(cmd_hash);
CREATE INDEX IF NOT EXISTS idx_git_events_project     ON git_events(project_id, ts);
CREATE INDEX IF NOT EXISTS idx_file_events_project_ts ON file_events(project_id, ts);
CREATE INDEX IF NOT EXISTS idx_claude_sessions_proj   ON claude_sessions(project_id, ts);
CREATE INDEX IF NOT EXISTS idx_errors_project         ON errors(project_id, error_hash);
CREATE INDEX IF NOT EXISTS idx_prompts_project_score  ON prompts(project_id, score);
CREATE INDEX IF NOT EXISTS idx_learnings_project      ON learnings(project_id, ts);
CREATE INDEX IF NOT EXISTS idx_decisions_project      ON decisions(project_id, ts);
CREATE INDEX IF NOT EXISTS idx_analyses_project       ON analyses(project_id, ts);
CREATE INDEX IF NOT EXISTS idx_daily_summaries_date   ON daily_summaries(date);
CREATE INDEX IF NOT EXISTS idx_sessions_project       ON sessions(project_id, start_ts);
"""


def up(db_conn: sqlite3.Connection) -> None:
    """
    Apply the initial schema.

    Idempotent: uses CREATE TABLE IF NOT EXISTS and CREATE INDEX IF NOT EXISTS
    so running this on an already-initialised database is safe.
    """
    cur = db_conn.cursor()
    for statement in _DDL.strip().split(";"):
        stmt = statement.strip()
        if stmt:
            cur.execute(stmt)
    for statement in _INDEXES.strip().split(";"):
        stmt = statement.strip()
        if stmt:
            cur.execute(stmt)
    db_conn.commit()


def down(db_conn: sqlite3.Connection) -> None:
    """
    Drop all managed tables (rollback).

    Tables are dropped in reverse dependency order so foreign-key constraints
    are not violated (children before parents).
    """
    cur = db_conn.cursor()
    cur.execute("PRAGMA foreign_keys=OFF")
    for table in _ALL_TABLES:
        cur.execute(f"DROP TABLE IF EXISTS {table}")
    cur.execute("PRAGMA foreign_keys=ON")
    db_conn.commit()
