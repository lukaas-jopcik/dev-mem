"""
dev_mem.memory.observations — CRUD and search for observations.

Rule-based observation generation (no LLM, <50 ms).
"""

from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Type helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_epoch() -> int:
    return int(time.time())


def _json_list(value: Any) -> str:
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, str):
        return value  # assume already JSON
    return "[]"


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    for key in ("facts", "concepts", "files_read", "files_modified"):
        raw = d.get(key, "[]") or "[]"
        try:
            d[key] = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            d[key] = []
    return d


# ---------------------------------------------------------------------------
# Insert
# ---------------------------------------------------------------------------

def insert_observation(
    conn: sqlite3.Connection,
    *,
    title: str,
    obs_type: str = "discovery",
    narrative: str = "",
    text: str = "",
    subtitle: str = "",
    facts: list[str] | None = None,
    concepts: list[str] | None = None,
    project: str = "",
    project_id: int | None = None,
    session_id: str = "",
    memory_session_id: str = "",
    files_read: list[str] | None = None,
    files_modified: list[str] | None = None,
    prompt_number: int | None = None,
    discovery_tokens: int | None = None,
) -> int:
    """Insert a new observation and return its id."""
    now_iso = _now_iso()
    now_epoch = _now_epoch()

    row_id = conn.execute(
        """
        INSERT INTO observations
            (title, type, text, narrative, subtitle,
             facts, concepts,
             project, project_id,
             session_id, memory_session_id,
             files_read, files_modified,
             prompt_number, discovery_tokens,
             created_at, created_at_epoch)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            title,
            obs_type,
            text,
            narrative,
            subtitle,
            _json_list(facts or []),
            _json_list(concepts or []),
            project,
            project_id,
            session_id,
            memory_session_id,
            _json_list(files_read or []),
            _json_list(files_modified or []),
            prompt_number,
            discovery_tokens,
            now_iso,
            now_epoch,
        ),
    ).lastrowid
    conn.commit()
    return row_id  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def search_observations(
    conn: sqlite3.Connection,
    query: str,
    *,
    limit: int = 20,
    project: str | None = None,
    obs_type: str | None = None,
    offset: int = 0,
) -> list[dict]:
    """FTS5 full-text search on observations."""
    if not query.strip():
        return list_observations(conn, limit=limit, project=project, obs_type=obs_type, offset=offset)

    params: list[Any] = [query]
    extra = ""
    if project:
        extra += " AND o.project = ?"
        params.append(project)
    if obs_type:
        extra += " AND o.type = ?"
        params.append(obs_type)
    params += [limit, offset]

    rows = conn.execute(
        f"""
        SELECT o.*
        FROM observations_fts f
        JOIN observations o ON o.id = f.rowid
        WHERE observations_fts MATCH ?
        {extra}
        ORDER BY rank
        LIMIT ? OFFSET ?
        """,
        params,
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def list_observations(
    conn: sqlite3.Connection,
    *,
    limit: int = 20,
    project: str | None = None,
    obs_type: str | None = None,
    offset: int = 0,
) -> list[dict]:
    """Return recent observations without FTS, ordered by created_at_epoch DESC."""
    params: list[Any] = []
    where = "WHERE 1=1"
    if project:
        where += " AND project = ?"
        params.append(project)
    if obs_type:
        where += " AND type = ?"
        params.append(obs_type)
    params += [limit, offset]

    rows = conn.execute(
        f"SELECT * FROM observations {where} ORDER BY created_at_epoch DESC LIMIT ? OFFSET ?",
        params,
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Fetch by IDs
# ---------------------------------------------------------------------------

def get_observations_by_ids(
    conn: sqlite3.Connection,
    ids: list[int],
    *,
    order_by: str = "created_at_epoch DESC",
) -> list[dict]:
    if not ids:
        return []
    placeholders = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT * FROM observations WHERE id IN ({placeholders}) ORDER BY {order_by}",
        ids,
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------

def get_timeline(
    conn: sqlite3.Connection,
    anchor_id: Optional[int] = None,
    *,
    depth_before: int = 5,
    depth_after: int = 5,
    project: str | None = None,
    query: str | None = None,
) -> list[dict]:
    """Return N before + anchor + N after by created_at_epoch."""
    where_clause = "WHERE 1=1"
    base_params: list[Any] = []
    if project:
        where_clause += " AND project = ?"
        base_params.append(project)

    if anchor_id is None:
        # No anchor: just return the most recent observations
        if query:
            return search_observations(conn, query, limit=depth_before + depth_after + 1, project=project)
        rows = conn.execute(
            f"SELECT * FROM observations {where_clause} "
            "ORDER BY created_at_epoch DESC LIMIT ?",
            base_params + [depth_before + depth_after + 1],
        ).fetchall()
        return [_row_to_dict(r) for r in rows]

    anchor_row = conn.execute(
        "SELECT created_at_epoch FROM observations WHERE id = ?", (anchor_id,)
    ).fetchone()
    if not anchor_row:
        return []
    anchor_epoch = anchor_row["created_at_epoch"]

    before_rows = conn.execute(
        f"SELECT * FROM observations {where_clause} AND created_at_epoch < ? "
        "ORDER BY created_at_epoch DESC LIMIT ?",
        base_params + [anchor_epoch, depth_before],
    ).fetchall()

    anchor_data = conn.execute(
        "SELECT * FROM observations WHERE id = ?", (anchor_id,)
    ).fetchone()

    after_rows = conn.execute(
        f"SELECT * FROM observations {where_clause} AND created_at_epoch > ? "
        "ORDER BY created_at_epoch ASC LIMIT ?",
        base_params + [anchor_epoch, depth_after],
    ).fetchall()

    combined = list(reversed(before_rows))
    if anchor_data:
        combined.append(anchor_data)
    combined.extend(after_rows)
    return [_row_to_dict(r) for r in combined]


# ---------------------------------------------------------------------------
# Rule-based observation generation
# ---------------------------------------------------------------------------

_OBS_TOOLS = frozenset({"Read", "Write", "Edit", "MultiEdit", "Bash"})


def generate_observation_from_tool_call(
    tool: str,
    input_obj: Any,
    output_obj: Any,
    *,
    min_output_chars: int = 100,
    files_read: list[str] | None = None,
    files_modified: list[str] | None = None,
) -> dict | None:
    """
    Derive observation metadata from a tool call — rule-based, no LLM.

    Returns a kwargs dict suitable for insert_observation(), or None if the
    call is not substantive enough to record.
    """
    if tool not in _OBS_TOOLS:
        return None

    # Flatten output to string
    if isinstance(output_obj, str):
        output_str = output_obj
    else:
        try:
            output_str = json.dumps(output_obj, ensure_ascii=False)
        except (TypeError, ValueError):
            output_str = str(output_obj)

    if len(output_str) < min_output_chars:
        return None

    # Determine type and build title/narrative
    obs_type = "discovery"
    title = ""
    narrative = ""
    f_read: list[str] = list(files_read or [])
    f_modified: list[str] = list(files_modified or [])

    if tool == "Bash":
        cmd = ""
        if isinstance(input_obj, dict):
            cmd = str(input_obj.get("command", ""))
        elif isinstance(input_obj, str):
            cmd = input_obj

        # Check for error exit
        if isinstance(output_obj, dict):
            exit_code = output_obj.get("exit_code") or output_obj.get("exitCode") or 0
            if exit_code and int(exit_code) != 0:
                obs_type = "bugfix"
        if "error" in output_str.lower() or "traceback" in output_str.lower():
            obs_type = "bugfix"

        title = f"Bash: {cmd[:80]}" if cmd else "Bash command"
        narrative = output_str[:300]

    elif tool == "Write":
        path = ""
        if isinstance(input_obj, dict):
            path = str(input_obj.get("file_path", input_obj.get("path", "")))
        obs_type = "feature"
        f_modified.append(path) if path and path not in f_modified else None
        title = f"Write: {path}" if path else "Write file"
        narrative = f"Created/wrote file: {path}"

    elif tool in ("Edit", "MultiEdit"):
        path = ""
        if isinstance(input_obj, dict):
            path = str(input_obj.get("file_path", input_obj.get("path", "")))
        # Large edit → refactor
        obs_type = "refactor" if len(output_str) > 500 else "change"
        f_modified.append(path) if path and path not in f_modified else None
        title = f"Edit: {path}" if path else "Edit file"
        narrative = f"Edited file: {path}"

    elif tool == "Read":
        path = ""
        if isinstance(input_obj, dict):
            path = str(input_obj.get("file_path", input_obj.get("path", "")))
        obs_type = "discovery"
        f_read.append(path) if path and path not in f_read else None
        title = f"Read: {path}" if path else "Read file"
        narrative = output_str[:300]

    return {
        "title": title,
        "obs_type": obs_type,
        "narrative": narrative,
        "text": output_str[:500],
        "files_read": f_read,
        "files_modified": f_modified,
    }
