"""
dev_mem.mcp.server — Raw stdio JSON-RPC 2.0 MCP server.

4 tools:
  - search           — FTS5 full-text search on observations
  - save_memory      — Insert a manual observation
  - get_observations — Fetch observations by IDs
  - timeline         — Return timeline slice around an anchor observation

No external MCP packages required — pure stdlib + dev_mem internals.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Optional

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "dev-mem"
SERVER_VERSION = "0.1.0"

_TOOLS: list[dict] = [
    {
        "name": "search",
        "description": (
            "Full-text search across dev-mem observations. "
            "Returns matching observations with title, type, narrative, and files."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["query"],
            "properties": {
                "query":    {"type": "string", "description": "Search query (FTS5 syntax supported)"},
                "limit":    {"type": "integer", "description": "Max results (default 20)", "default": 20},
                "project":  {"type": "string", "description": "Filter by project name"},
                "obs_type": {"type": "string", "description": "Filter by type (bugfix|feature|refactor|discovery|decision|change)"},
                "offset":   {"type": "integer", "description": "Pagination offset", "default": 0},
            },
        },
    },
    {
        "name": "save_memory",
        "description": "Save an observation/memory to the dev-mem database.",
        "inputSchema": {
            "type": "object",
            "required": ["text"],
            "properties": {
                "text":     {"type": "string", "description": "The main content of the observation"},
                "title":    {"type": "string", "description": "Short title (auto-derived from text if omitted)"},
                "obs_type": {
                    "type": "string",
                    "description": "Observation type",
                    "enum": ["bugfix", "feature", "refactor", "discovery", "decision", "change"],
                    "default": "discovery",
                },
                "narrative":  {"type": "string", "description": "Longer narrative / context"},
                "project":    {"type": "string", "description": "Project name"},
                "session_id": {"type": "string", "description": "Claude Code session ID"},
                "facts":      {"type": "array", "items": {"type": "string"}, "description": "List of atomic facts"},
            },
        },
    },
    {
        "name": "get_observations",
        "description": "Fetch one or more observations by their numeric IDs.",
        "inputSchema": {
            "type": "object",
            "required": ["ids"],
            "properties": {
                "ids":      {"type": "array", "items": {"type": "integer"}, "description": "List of observation IDs"},
                "order_by": {"type": "string", "description": "SQL ORDER BY clause (default: created_at_epoch DESC)"},
            },
        },
    },
    {
        "name": "timeline",
        "description": (
            "Return a timeline slice: N observations before and after an anchor. "
            "If no anchor is provided, returns the most recent observations."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "anchor":       {"type": "integer", "description": "Anchor observation ID"},
                "query":        {"type": "string",  "description": "Optional FTS query to find anchor automatically"},
                "depth_before": {"type": "integer", "description": "Observations before anchor (default 5)", "default": 5},
                "depth_after":  {"type": "integer", "description": "Observations after anchor (default 5)",  "default": 5},
                "project":      {"type": "string",  "description": "Filter by project name"},
            },
        },
    },
]


# ---------------------------------------------------------------------------
# DB connection
# ---------------------------------------------------------------------------

def _open_conn() -> Optional[sqlite3.Connection]:
    try:
        from dev_mem.settings import Settings
        db_path = Settings().db_path
        if not db_path.exists():
            return None
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def _tool_search(args: dict) -> dict:
    from dev_mem.memory.observations import search_observations

    conn = _open_conn()
    if conn is None:
        return {"error": "Database not available. Run: dev-mem upgrade"}

    try:
        results = search_observations(
            conn,
            args.get("query", ""),
            limit=int(args.get("limit", 20)),
            project=args.get("project"),
            obs_type=args.get("obs_type"),
            offset=int(args.get("offset", 0)),
        )
        return {"observations": results, "count": len(results)}
    finally:
        conn.close()


def _tool_save_memory(args: dict) -> dict:
    from dev_mem.memory.observations import insert_observation

    conn = _open_conn()
    if conn is None:
        return {"error": "Database not available. Run: dev-mem upgrade"}

    try:
        text = str(args.get("text", ""))
        title = str(args.get("title") or text[:60])
        obs_type = str(args.get("obs_type") or args.get("type") or "discovery")
        valid_types = {"bugfix", "feature", "refactor", "discovery", "decision", "change"}
        if obs_type not in valid_types:
            obs_type = "discovery"

        facts = args.get("facts", [])
        if isinstance(facts, str):
            try:
                facts = json.loads(facts)
            except Exception:  # noqa: BLE001
                facts = [facts]

        obs_id = insert_observation(
            conn,
            title=title,
            obs_type=obs_type,
            narrative=str(args.get("narrative") or text),
            text=text,
            project=str(args.get("project") or ""),
            session_id=str(args.get("session_id") or ""),
            memory_session_id=str(args.get("session_id") or ""),
            facts=facts if isinstance(facts, list) else [],
        )
        return {"id": obs_id, "title": title, "type": obs_type}
    finally:
        conn.close()


def _tool_get_observations(args: dict) -> dict:
    from dev_mem.memory.observations import get_observations_by_ids

    conn = _open_conn()
    if conn is None:
        return {"error": "Database not available. Run: dev-mem upgrade"}

    try:
        ids = [int(x) for x in (args.get("ids") or [])]
        order_by = str(args.get("order_by") or "created_at_epoch DESC")
        # Whitelist order_by to prevent SQL injection
        safe_orders = {
            "created_at_epoch DESC", "created_at_epoch ASC",
            "id DESC", "id ASC", "type ASC",
        }
        if order_by not in safe_orders:
            order_by = "created_at_epoch DESC"
        results = get_observations_by_ids(conn, ids, order_by=order_by)
        return {"observations": results, "count": len(results)}
    finally:
        conn.close()


def _tool_timeline(args: dict) -> dict:
    from dev_mem.memory.observations import get_timeline

    conn = _open_conn()
    if conn is None:
        return {"error": "Database not available. Run: dev-mem upgrade"}

    try:
        anchor = args.get("anchor")
        if anchor is not None:
            anchor = int(anchor)
        result = get_timeline(
            conn,
            anchor_id=anchor,
            depth_before=int(args.get("depth_before", 5)),
            depth_after=int(args.get("depth_after", 5)),
            project=args.get("project"),
            query=args.get("query"),
        )
        return {"observations": result, "count": len(result)}
    finally:
        conn.close()


_TOOL_HANDLERS = {
    "search": _tool_search,
    "save_memory": _tool_save_memory,
    "get_observations": _tool_get_observations,
    "timeline": _tool_timeline,
}


# ---------------------------------------------------------------------------
# JSON-RPC helpers
# ---------------------------------------------------------------------------

def _ok(req_id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _err(req_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _send(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# Request handlers
# ---------------------------------------------------------------------------

def _handle_initialize(req: dict) -> dict:
    return _ok(req.get("id"), {
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {"tools": {}},
        "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
    })


def _handle_tools_list(req: dict) -> dict:
    return _ok(req.get("id"), {"tools": _TOOLS})


def _handle_tools_call(req: dict) -> dict:
    params = req.get("params", {})
    tool_name = params.get("name", "")
    args = params.get("arguments") or params.get("args") or {}

    handler = _TOOL_HANDLERS.get(tool_name)
    if handler is None:
        return _err(req.get("id"), -32601, f"Unknown tool: {tool_name}")

    try:
        result = handler(args)
        # MCP expects content array
        content_text = json.dumps(result, ensure_ascii=False, default=str, indent=2)
        return _ok(req.get("id"), {
            "content": [{"type": "text", "text": content_text}],
            "isError": "error" in result,
        })
    except Exception as exc:  # noqa: BLE001
        return _err(req.get("id"), -32603, str(exc))


def _dispatch(req: dict) -> Optional[dict]:
    method = req.get("method", "")

    if method == "initialize":
        return _handle_initialize(req)
    if method in ("tools/list", "listTools"):
        return _handle_tools_list(req)
    if method in ("tools/call", "callTool"):
        return _handle_tools_call(req)
    if method == "notifications/initialized":
        return None  # notification — no response
    if req.get("id") is not None:
        return _err(req.get("id"), -32601, f"Method not found: {method}")
    return None


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run_server() -> None:
    """Read newline-delimited JSON from stdin, write responses to stdout."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as exc:
            _send(_err(None, -32700, f"Parse error: {exc}"))
            continue

        response = _dispatch(req)
        if response is not None:
            _send(response)


def main() -> None:
    run_server()


if __name__ == "__main__":
    main()
