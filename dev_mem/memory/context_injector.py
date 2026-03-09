"""
dev_mem.memory.context_injector — Build dev-mem context for SessionStart.

Prints a compact XML block to stdout that Claude Code injects into the
system prompt at the start of each session.

Design goals:
  - Token-efficient: ~1500–2500 chars max
  - Meaningful: real learnings and decisions, not raw tool titles
  - Fast: must complete in < 1.5 s
"""

from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Context block builder
# ---------------------------------------------------------------------------

def build_context_block(
    conn: sqlite3.Connection,
    project: str,
    project_id: Optional[int],
    *,
    max_chars: int = 2500,
) -> str:
    parts: list[str] = []

    # ── 1. Last 2 session summaries (project-aware, fallback to any) ──
    summaries = []
    if project_id is not None:
        summaries = conn.execute(
            "SELECT * FROM session_summaries WHERE project_id = ? "
            "ORDER BY created_at DESC LIMIT 2",
            (project_id,),
        ).fetchall()
    if not summaries:
        # Fall back: most recent summaries regardless of project
        # Filter to meaningful ones (completed or learned field non-empty)
        summaries = conn.execute(
            "SELECT * FROM session_summaries "
            "WHERE (completed != '' OR learned != '') "
            "ORDER BY created_at DESC LIMIT 2"
        ).fetchall()

    if summaries:
        parts.append("<sessions>")
        for s in summaries:
            date = (s["created_at"] or "")[:10]
            parts.append(f'  <session at="{date}">')
            if s["completed"] and _is_meaningful(s["completed"]):
                parts.append(f"    <done>{_esc(s['completed'][:200])}</done>")
            if s["learned"] and _is_meaningful(s["learned"]) and not s["learned"].startswith("{"):
                parts.append(f"    <learned>{_esc(s['learned'][:300])}</learned>")
            if s["files_edited"]:
                # Show just file names, not full paths
                fnames = [Path(p).name for p in s["files_edited"].split("\n") if p.strip()]
                if fnames:
                    parts.append(f"    <edited>{_esc(', '.join(fnames[:10]))}</edited>")
            parts.append("  </session>")
        parts.append("</sessions>")

    # ── 2. Recent learnings (project-aware, fallback to any) ─────────
    learnings = []
    if project_id is not None:
        learnings = conn.execute(
            "SELECT type, text FROM learnings WHERE project_id = ? "
            "ORDER BY ts DESC LIMIT 8",
            (project_id,),
        ).fetchall()
    if not learnings:
        learnings = conn.execute(
            "SELECT type, text FROM learnings ORDER BY ts DESC LIMIT 8"
        ).fetchall()

    if learnings:
        parts.append("<learnings>")
        for l in learnings:
            ltype = l["type"] or "note"
            text = (l["text"] or "")[:200]
            if text:
                parts.append(f'  <learning type="{ltype}">{_esc(text)}</learning>')
        parts.append("</learnings>")

    # ── 3. Recent decisions ───────────────────────────────────────────
    try:
        dec_where = "WHERE 1=1"
        dec_params: list = []
        if project_id is not None:
            dec_where += " AND project_id = ?"
            dec_params.append(project_id)
        decisions = conn.execute(
            f"SELECT title, reasoning FROM decisions {dec_where} ORDER BY ts DESC LIMIT 4",
            dec_params,
        ).fetchall()
        if decisions:
            parts.append("<decisions>")
            for d in decisions:
                title = (d["title"] or "")[:150]
                if title:
                    parts.append(f"  <decision>{_esc(title)}</decision>")
            parts.append("</decisions>")
    except Exception:
        pass

    # ── 4. Fallback: recent observations if no sessions yet ───────────
    if not summaries:
        params: list = []
        where = "WHERE 1=1"
        if project and project != Path(os.getcwd()).name:
            where += " AND project = ?"
            params.append(project)
        params.append(6)

        obs_rows = conn.execute(
            f"SELECT type, title, narrative FROM observations "
            f"{where} ORDER BY created_at_epoch DESC LIMIT ?",
            params,
        ).fetchall()

        if obs_rows:
            parts.append("<recent_work>")
            for o in obs_rows:
                title = (o["title"] or "")[:100]
                if _is_meaningful(title):
                    parts.append(f'  <item type="{o["type"] or "discovery"}">{_esc(title)}</item>')
            parts.append("</recent_work>")

    if not parts:
        return ""

    inner = "\n".join(parts)
    block = (
        f'<dev-mem-context project="{_esc(project)}" generated="{_now_iso()}">\n'
        f"{inner}\n"
        "</dev-mem-context>"
    )

    if len(block) > max_chars:
        block = block[:max_chars] + "\n</dev-mem-context>"

    return block


def _is_meaningful(text: str) -> bool:
    """Return False for raw tool title strings like 'Bash: ls ...' or 'Read: /path'."""
    if not text or not text.strip():
        return False
    stripped = text.strip()
    # Skip raw JSON blobs
    if stripped.startswith("{") or stripped.startswith("["):
        return False
    # Skip raw tool prefixes that convey nothing
    tool_prefixes = ("Bash: ", "Read: ", "Write: ", "Edit: ", "MultiEdit: ", "Glob: ", "Grep: ")
    if any(stripped.startswith(p) for p in tool_prefixes):
        return False
    return True


def _esc(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


# ---------------------------------------------------------------------------
# Entry point for SessionStart hook
# ---------------------------------------------------------------------------

def write_context_to_stdout() -> None:
    """
    Detect project from CWD, build compact context block, print to stdout.
    Must complete in < 1.5 s.
    """
    from dev_mem.settings import DB_PATH, Settings

    settings = Settings()
    db_path = settings.db_path

    if not db_path.exists():
        return

    cwd = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()

    conn: Optional[sqlite3.Connection] = None
    try:
        conn = sqlite3.connect(str(db_path), timeout=1.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA query_only=1")

        # Resolve project
        project_id: Optional[int] = None
        project: str = ""

        row = conn.execute(
            "SELECT * FROM projects WHERE path = ? AND active = 1", (cwd,)
        ).fetchone()
        if not row:
            all_projects = conn.execute(
                "SELECT * FROM projects WHERE active = 1 ORDER BY LENGTH(path) DESC"
            ).fetchall()
            for p in all_projects:
                if cwd.startswith(p["path"]):
                    row = p
                    break

        if row:
            project_id = row["id"]
            project = row["name"]
        else:
            project = Path(cwd).name

        max_chars = settings.get("context_inject_max_chars", 2500)

        block = build_context_block(
            conn,
            project,
            project_id,
            max_chars=max_chars,
        )
        if block:
            print(block, flush=True)

    except Exception:
        pass
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass
