"""
dev_mem.memory.migrate_claude_mem — One-time migration from claude-mem DB.

Usage:
    python3 -m dev_mem.memory.migrate_claude_mem

Reads ~/.claude-mem/claude-mem.db (sqlite) and imports observations into
the dev-mem database, deduplicating on (memory_session_id, title, created_at_epoch).
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

CLAUDE_MEM_DB = Path.home() / ".claude-mem" / "claude-mem.db"


def _parse_epoch(ts: str | None) -> int:
    if not ts:
        return 0
    import time
    try:
        from datetime import datetime, timezone
        if "T" in str(ts):
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        else:
            dt = datetime.fromisoformat(str(ts))
        return int(dt.timestamp())
    except Exception:  # noqa: BLE001
        return 0


def migrate(
    source_db: Path = CLAUDE_MEM_DB,
    *,
    verbose: bool = True,
) -> int:
    """Migrate claude-mem observations to dev-mem. Returns count of imported rows."""
    from dev_mem.memory.observations import insert_observation
    from dev_mem.settings import Settings

    settings = Settings()
    dest_db_path = settings.db_path

    if not source_db.exists():
        if verbose:
            print(f"[migrate] Source not found: {source_db}", file=sys.stderr)
        return 0

    if not dest_db_path.exists():
        if verbose:
            print(f"[migrate] Target DB not found: {dest_db_path}", file=sys.stderr)
            print("[migrate] Run: dev-mem upgrade", file=sys.stderr)
        return 0

    src = sqlite3.connect(str(source_db))
    src.row_factory = sqlite3.Row
    dest = sqlite3.connect(str(dest_db_path))
    dest.row_factory = sqlite3.Row
    dest.execute("PRAGMA journal_mode=WAL")

    imported = 0
    skipped = 0

    try:
        # Try to read observations table from claude-mem schema
        try:
            rows = src.execute("SELECT * FROM observations ORDER BY id ASC").fetchall()
        except sqlite3.OperationalError:
            if verbose:
                print("[migrate] 'observations' table not found in source DB.", file=sys.stderr)
            return 0

        for row in rows:
            d = dict(row)
            memory_session_id = str(d.get("memory_session_id") or d.get("session_id") or "")
            title = str(d.get("title") or "")
            created_at = str(d.get("created_at") or d.get("created_at_epoch") or "")
            epoch = _parse_epoch(created_at) or int(d.get("created_at_epoch") or 0)

            # Dedup check
            exists = dest.execute(
                "SELECT id FROM observations "
                "WHERE memory_session_id = ? AND title = ? AND created_at_epoch = ?",
                (memory_session_id, title, epoch),
            ).fetchone()
            if exists:
                skipped += 1
                continue

            # Map type
            obs_type = str(d.get("type") or d.get("obs_type") or "discovery")
            valid_types = {"bugfix", "feature", "refactor", "discovery", "decision", "change"}
            if obs_type not in valid_types:
                obs_type = "discovery"

            # Facts / concepts
            facts_raw = d.get("facts") or "[]"
            concepts_raw = d.get("concepts") or "[]"
            try:
                facts = json.loads(facts_raw) if isinstance(facts_raw, str) else facts_raw
            except Exception:  # noqa: BLE001
                facts = []
            try:
                concepts = json.loads(concepts_raw) if isinstance(concepts_raw, str) else concepts_raw
            except Exception:  # noqa: BLE001
                concepts = []

            insert_observation(
                dest,
                title=title,
                obs_type=obs_type,
                narrative=str(d.get("narrative") or ""),
                text=str(d.get("text") or ""),
                subtitle=str(d.get("subtitle") or ""),
                facts=facts if isinstance(facts, list) else [],
                concepts=concepts if isinstance(concepts, list) else [],
                project=str(d.get("project") or ""),
                session_id=str(d.get("session_id") or ""),
                memory_session_id=memory_session_id,
                files_read=[],
                files_modified=[],
                discovery_tokens=d.get("discovery_tokens"),
            )
            imported += 1

    finally:
        src.close()
        dest.close()

    if verbose:
        print(f"[migrate] Done. Imported: {imported}, Skipped (dup): {skipped}")

    return imported


def main() -> None:
    count = migrate(verbose=True)
    sys.exit(0 if count >= 0 else 1)


if __name__ == "__main__":
    main()
