"""
db.py — SQLite schema, CRUD helpers, and migration runner for dev-mem.

The actual DDL lives in migrations/001_initial.py so this file stays lean.
On first open, init_schema() delegates to that migration's up() function.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _load_migration(script: Path) -> Any:
    """Import a migration script and return the module object."""
    spec = importlib.util.spec_from_file_location(script.stem, script)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load migration: {script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


# ---------------------------------------------------------------------------
# Database class
# ---------------------------------------------------------------------------

class Database:
    """
    Thin wrapper around a SQLite connection that owns the dev-mem schema.

    All public methods operate on the same connection and are safe to call
    from a single thread (SQLite default threading mode).
    """

    def __init__(self, db_path: Path | str) -> None:
        """
        Open (or create) the database at *db_path* and initialise the schema.
        """
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection = sqlite3.connect(
            str(self._path), check_same_thread=False
        )
        self._conn.row_factory = sqlite3.Row
        self.init_schema()

    # ------------------------------------------------------------------
    # Schema bootstrap
    # ------------------------------------------------------------------

    def init_schema(self) -> None:
        """
        Initialise all tables and indexes.

        Delegates to the 001_initial migration so DDL lives in one place.
        If the migration file is not found, a minimal PRAGMA setup is applied
        and the caller is expected to run run_migrations() separately.
        """
        initial = Path(__file__).parent.parent / "migrations" / "001_initial.py"
        if initial.exists():
            module = _load_migration(initial)
            module.up(self._conn)
            # Record the migration as applied if not already tracked.
            version: int = getattr(module, "VERSION", 1)
            description: str = getattr(module, "DESCRIPTION", "Initial schema")
            existing = self._conn.execute(
                "SELECT version FROM schema_versions WHERE version = ?", (version,)
            ).fetchone()
            if not existing:
                self._conn.execute(
                    "INSERT INTO schema_versions (version, applied_at, description) "
                    "VALUES (?, ?, ?)",
                    (version, _now_iso(), description),
                )
                self._conn.commit()
        else:
            # Fallback: at minimum enable WAL and foreign keys
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.commit()

    # ------------------------------------------------------------------
    # Project helpers
    # ------------------------------------------------------------------

    def get_project_by_path(self, cwd: str | Path) -> Optional[sqlite3.Row]:
        """
        Return the best-matching project row for *cwd*.

        Strategy: exact path match first, then longest parent-path match.
        Returns None if no project matches.
        """
        # Use abspath (no symlink resolution) so paths that don't exist
        # on disk still compare correctly against stored project paths.
        cwd_str = os.path.abspath(str(cwd))
        cur = self._conn.execute(
            "SELECT * FROM projects WHERE active = 1 ORDER BY length(path) DESC"
        )
        for row in cur.fetchall():
            project_path = row["path"]
            if cwd_str == project_path or cwd_str.startswith(project_path + os.sep):
                return row
        return None

    def upsert_project(
        self, name: str, path: str, color: str = "#6366f1"
    ) -> int:
        """
        Insert a new project or return the id of an existing one with the
        same *path*.
        """
        existing = self._conn.execute(
            "SELECT id FROM projects WHERE path = ?", (path,)
        ).fetchone()
        if existing:
            return existing["id"]
        cur = self._conn.execute(
            "INSERT INTO projects (name, path, color, active, created_at) "
            "VALUES (?, ?, ?, 1, ?)",
            (name, path, color, _now_iso()),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    def insert_command(
        self,
        project_id: Optional[int],
        cmd: str,
        duration_ms: Optional[int] = None,
        exit_code: Optional[int] = None,
    ) -> Optional[int]:
        """
        Insert a shell command record.

        Deduplication: if an identical cmd_hash already exists within the
        last 1 second for the same project, the insert is skipped.
        Returns the new row id, or None if deduplicated.
        """
        cmd_hash = _sha1(cmd)
        ts_now = _now_iso()
        one_sec_ago = datetime.fromtimestamp(
            time.time() - 1.0, tz=timezone.utc
        ).isoformat()

        duplicate = self._conn.execute(
            "SELECT id FROM commands "
            "WHERE project_id IS ? AND cmd_hash = ? AND ts >= ?",
            (project_id, cmd_hash, one_sec_ago),
        ).fetchone()
        if duplicate:
            return None

        cur = self._conn.execute(
            "INSERT INTO commands (project_id, cmd_hash, cmd, ts, duration_ms, exit_code) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (project_id, cmd_hash, cmd, ts_now, duration_ms, exit_code),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Git events
    # ------------------------------------------------------------------

    def insert_git_event(
        self,
        project_id: Optional[int],
        hash: str,
        message: str,
        files: list[str],
        insertions: int = 0,
        deletions: int = 0,
    ) -> Optional[int]:
        """
        Insert a git commit event. Silently ignores duplicate commit hashes.
        Returns the new row id, or None if the hash already exists.
        """
        existing = self._conn.execute(
            "SELECT id FROM git_events WHERE hash = ?", (hash,)
        ).fetchone()
        if existing:
            return None
        cur = self._conn.execute(
            "INSERT INTO git_events "
            "(project_id, hash, message, files_json, insertions, deletions, ts) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (project_id, hash, message,
             json.dumps(files), insertions, deletions, _now_iso()),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Claude sessions
    # ------------------------------------------------------------------

    def insert_claude_session(
        self,
        project_id: Optional[int],
        tool: str,
        input_summary: str,
        output_summary: str,
        session_id: str,
    ) -> int:
        """Insert a Claude AI session record and return its row id."""
        cur = self._conn.execute(
            "INSERT INTO claude_sessions "
            "(project_id, tool, input_summary, output_summary, session_id, ts) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (project_id, tool, input_summary, output_summary, session_id, _now_iso()),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Errors
    # ------------------------------------------------------------------

    def upsert_error(self, project_id: Optional[int], error_text: str) -> int:
        """
        Insert a new error or increment the counter for an existing one.

        Errors are grouped by a SHA-1 hash of the first 200 characters of
        the error text (lightweight fuzzy grouping for similar stack traces).
        Returns the row id.
        """
        error_hash = _sha1(error_text[:200])
        now = _now_iso()
        existing = self._conn.execute(
            "SELECT id FROM errors WHERE project_id IS ? AND error_hash = ?",
            (project_id, error_hash),
        ).fetchone()
        if existing:
            self._conn.execute(
                "UPDATE errors SET count = count + 1, last_seen = ? WHERE id = ?",
                (now, existing["id"]),
            )
            self._conn.commit()
            return existing["id"]
        cur = self._conn.execute(
            "INSERT INTO errors "
            "(project_id, error_text, error_hash, count, first_seen, last_seen) "
            "VALUES (?, ?, ?, 1, ?, ?)",
            (project_id, error_text, error_hash, now, now),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Prompts
    # ------------------------------------------------------------------

    def insert_prompt(
        self,
        project_id: Optional[int],
        text: str,
        source: str = "",
        score: int = 0,
        tags: Optional[list[str]] = None,
    ) -> int:
        """Insert a prompt record and return its row id."""
        cur = self._conn.execute(
            "INSERT INTO prompts (project_id, text, source, score, tags, ts) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (project_id, text, source, score, json.dumps(tags or []), _now_iso()),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Learnings
    # ------------------------------------------------------------------

    def insert_learning(
        self,
        project_id: Optional[int],
        text: str,
        type: str = "",
        source: str = "",
    ) -> int:
        """Insert a learning record and return its row id."""
        cur = self._conn.execute(
            "INSERT INTO learnings (project_id, text, type, source, ts) "
            "VALUES (?, ?, ?, ?, ?)",
            (project_id, text, type, source, _now_iso()),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Decisions
    # ------------------------------------------------------------------

    def insert_decision(
        self,
        project_id: Optional[int],
        title: str,
        context: str = "",
        reasoning: str = "",
        alternatives: str = "",
    ) -> int:
        """Insert an architectural decision record and return its row id."""
        cur = self._conn.execute(
            "INSERT INTO decisions "
            "(project_id, title, context, reasoning, alternatives, ts) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (project_id, title, context, reasoning, alternatives, _now_iso()),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Today stats
    # ------------------------------------------------------------------

    def get_today_stats(self, project_id: Optional[int]) -> dict[str, Any]:
        """
        Return a dict of activity counts for today (UTC date) scoped to
        *project_id*. All keys are always present even if the count is 0.
        """
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        pid = project_id

        def _count(table: str, ts_col: str = "ts") -> int:
            row = self._conn.execute(
                f"SELECT COUNT(*) AS n FROM {table} "
                f"WHERE project_id IS ? AND {ts_col} LIKE ?",
                (pid, f"{today}%"),
            ).fetchone()
            return row["n"] if row else 0

        return {
            "date": today,
            "commands": _count("commands"),
            "git_events": _count("git_events"),
            "file_events": _count("file_events"),
            "claude_sessions": _count("claude_sessions"),
            "errors": _count("errors", "last_seen"),
            "prompts": _count("prompts"),
            "learnings": _count("learnings"),
            "decisions": _count("decisions"),
        }

    # ------------------------------------------------------------------
    # Migrations
    # ------------------------------------------------------------------

    def run_migrations(self, migrations_dir: Path | str) -> list[str]:
        """
        Discover and run unapplied migration scripts from *migrations_dir*.

        Migration files must be named ``NNN_description.py`` and expose
        ``VERSION: int``, ``DESCRIPTION: str``, and ``up(conn)`` callables.
        Only migrations whose VERSION is not yet recorded in
        ``schema_versions`` are executed.

        Returns a list of descriptions for migrations that were applied.
        """
        migrations_dir = Path(migrations_dir)
        applied_versions: set[int] = {
            row[0]
            for row in self._conn.execute(
                "SELECT version FROM schema_versions"
            ).fetchall()
        }

        applied: list[str] = []
        for script in sorted(migrations_dir.glob("*.py")):
            module = _load_migration(script)
            version: int = getattr(module, "VERSION", None)
            description: str = getattr(module, "DESCRIPTION", script.stem)
            if version is None or version in applied_versions:
                continue
            module.up(self._conn)
            self._conn.execute(
                "INSERT INTO schema_versions (version, applied_at, description) "
                "VALUES (?, ?, ?)",
                (version, _now_iso(), description),
            )
            self._conn.commit()
            applied.append(description)

        return applied

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self._conn.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def __repr__(self) -> str:  # pragma: no cover
        return f"Database(path={self._path})"
