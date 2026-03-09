"""
dev_mem.memory.session_tracker — Claude Code session lifecycle tracking.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Session CRUD
# ---------------------------------------------------------------------------

def get_or_create_session(
    conn: sqlite3.Connection,
    memory_session_id: str,
    project_id: Optional[int],
    project: str,
    cwd: str,
) -> dict:
    row = conn.execute(
        "SELECT * FROM claude_code_sessions WHERE memory_session_id = ?",
        (memory_session_id,),
    ).fetchone()
    if row:
        return dict(row)

    conn.execute(
        """
        INSERT INTO claude_code_sessions
            (memory_session_id, project_id, project, cwd, started_at, status)
        VALUES (?, ?, ?, ?, ?, 'active')
        """,
        (memory_session_id, project_id, project, cwd, _now_iso()),
    )
    conn.commit()
    return dict(
        conn.execute(
            "SELECT * FROM claude_code_sessions WHERE memory_session_id = ?",
            (memory_session_id,),
        ).fetchone()
    )


def increment_session_tool_count(conn: sqlite3.Connection, memory_session_id: str) -> None:
    conn.execute(
        "UPDATE claude_code_sessions SET tool_call_count = tool_call_count + 1 "
        "WHERE memory_session_id = ?",
        (memory_session_id,),
    )
    conn.commit()


def increment_session_obs_count(conn: sqlite3.Connection, memory_session_id: str) -> None:
    conn.execute(
        "UPDATE claude_code_sessions SET observation_count = observation_count + 1 "
        "WHERE memory_session_id = ?",
        (memory_session_id,),
    )
    conn.commit()


def complete_session(conn: sqlite3.Connection, memory_session_id: str) -> None:
    conn.execute(
        "UPDATE claude_code_sessions SET status = 'completed', ended_at = ? "
        "WHERE memory_session_id = ?",
        (_now_iso(), memory_session_id),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Session summary builder — smart, not raw tool titles
# ---------------------------------------------------------------------------

def build_session_summary(
    conn: sqlite3.Connection,
    memory_session_id: str,
    project_id: Optional[int],
) -> Optional[int]:
    """
    Build a meaningful session_summary from accumulated observations.

    Instead of collecting raw tool titles, we:
    1. Track which files were read vs modified
    2. Extract real learnings (bugfixes, decisions) from narratives
    3. Produce a human-readable completed summary
    """
    rows = conn.execute(
        "SELECT * FROM observations WHERE memory_session_id = ? "
        "ORDER BY created_at_epoch ASC",
        (memory_session_id,),
    ).fetchall()

    if not rows:
        return None

    files_read: set[str] = set()
    files_edited: set[str] = set()
    completed_items: list[str] = []
    learned_items: list[str] = []
    topic_files: list[str] = []  # files that represent what was worked on

    for row in rows:
        obs_type = row["type"] or "discovery"
        title = row["title"] or ""
        narrative = row["narrative"] or ""

        # ── Parse tool type from title ──────────────────────────────────
        if title.startswith("Read: "):
            path = title[6:].strip()
            files_read.add(path)
            # Track non-trivial files as "topics"
            fname = Path(path).name
            if fname and not path.endswith("/") and fname not in (".", ".."):
                topic_files.append(fname)

        elif title.startswith(("Write: ", "Edit: ", "MultiEdit: ")):
            prefix_len = title.index(": ") + 2
            path = title[prefix_len:].strip()
            files_edited.add(path)
            fname = Path(path).name
            action = "Created" if title.startswith("Write:") else "Edited"
            completed_items.append(f"{action} {fname}")

        elif title.startswith("Bash: "):
            cmd = title[6:].strip()[:80]
            if obs_type == "bugfix":
                # Bash revealed/fixed a bug — only if narrative has real error info
                narr = _clean_narrative(narrative)
                if narr and len(narr) > 20 and not narr.startswith(("analytics", "base.html", "daily")):
                    learned_items.append(f"Fixed: {narr[:150]}")

        elif obs_type == "bugfix":
            narr = _clean_narrative(narrative)
            desc = narr or title
            if desc and not desc.startswith("{") and _looks_like_insight(desc):
                learned_items.append(f"Fixed: {desc[:150]}")

        elif obs_type == "decision":
            narr = _clean_narrative(narrative)
            desc = narr or title
            if desc and not desc.startswith("{") and _looks_like_insight(desc):
                learned_items.append(f"Decided: {desc[:150]}")

        elif obs_type == "refactor":
            narr = _clean_narrative(narrative)
            if narr and not narr.startswith("{"):
                completed_items.append(f"Refactored: {narr[:100]}")

        # Accumulate from files_json / facts
        for path in _parse_json_list(row["files_read"]):
            files_read.add(path)
        for path in _parse_json_list(row["files_modified"]):
            files_edited.add(path)
            files_edited.add(path)

    # Build concise completed string
    # Primary: what files were edited (most meaningful)
    edited_names = sorted({Path(p).name for p in files_edited if p})[:15]
    if edited_names:
        completed_str = "Edited: " + ", ".join(edited_names)
    else:
        completed_str = "\n".join(completed_items[:10])

    # Build investigated string from read files (topics)
    read_names = sorted({Path(p).name for p in files_read if p})[:12]
    investigated_str = "Read: " + ", ".join(read_names) if read_names else ""

    # Topic inference: if edited files, that's the main topic
    all_edited_paths = sorted(files_edited)
    if all_edited_paths:
        # Find common parent directory as topic
        try:
            common = str(Path(all_edited_paths[0]).parent)
            if len(all_edited_paths) > 1:
                for p in all_edited_paths[1:3]:
                    pp = str(Path(p).parent)
                    # Find common prefix
                    while common and not pp.startswith(common):
                        common = str(Path(common).parent)
            topic = Path(common).name if common != "/" else ""
            if topic and topic not in (".", ".."):
                investigated_str = f"Topic: {topic}. " + investigated_str
        except Exception:
            pass

    now = _now_iso()
    summary_id = conn.execute(
        """
        INSERT INTO session_summaries
            (memory_session_id, project_id,
             request, investigated, learned, completed, next_steps,
             files_read, files_edited, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            memory_session_id,
            project_id,
            "",
            investigated_str[:500],
            "\n".join(learned_items[:15]),
            completed_str[:500],
            "",
            "\n".join(sorted(files_read)[:40]),
            "\n".join(sorted(files_edited)[:40]),
            now,
        ),
    ).lastrowid
    conn.commit()
    return summary_id


# ---------------------------------------------------------------------------
# Learnings extractor — writes to learnings table
# ---------------------------------------------------------------------------

def extract_learnings(
    conn: sqlite3.Connection,
    memory_session_id: str,
    project_id: Optional[int],
) -> int:
    """
    Extract meaningful learnings from session observations → learnings table.
    Returns count of learnings written.
    """
    rows = conn.execute(
        "SELECT * FROM observations WHERE memory_session_id = ? "
        "ORDER BY created_at_epoch ASC",
        (memory_session_id,),
    ).fetchall()

    if not rows:
        return 0

    now = _now_iso()
    count = 0

    for row in rows:
        obs_type = row["type"] or "discovery"
        title = row["title"] or ""
        narrative = _clean_narrative(row["narrative"] or "")

        learning_type: Optional[str] = None
        text: Optional[str] = None

        if obs_type == "bugfix":
            # Only record if narrative has real error/fix info (not just a file path)
            desc = narrative or ""
            if not desc or desc.startswith(("Created/", "Edited file", "{")):
                # Fall back to title, but skip trivial commands
                if title.startswith("Bash: "):
                    cmd = title[6:].strip()
                    # Skip simple lookup commands
                    if any(cmd.startswith(skip) for skip in (
                        "ls ", "find ", "cat ", "head ", "tail ", "echo ",
                        "pwd", "which", "type ", "ps ", "kill ", "sleep",
                    )):
                        continue
                    desc = f"Investigated: {cmd[:100]}"
                else:
                    continue
            if len(desc) > 15 and not desc.startswith("{"):
                learning_type = "mistake"
                text = desc[:300]

        elif obs_type == "decision":
            desc = narrative or title
            if desc and not desc.startswith("{") and len(desc) > 15:
                # Skip raw tool titles
                if title.startswith(("Bash: ", "Read: ", "Write: ", "Edit: ")):
                    if not narrative or len(narrative) < 15:
                        continue
                    desc = narrative
                learning_type = "insight"
                text = desc[:300]

        elif obs_type == "refactor":
            # Only if narrative is meaningful, not just "Edited file: /path"
            if narrative and not narrative.startswith(("{", "Edited file", "Created/")):
                if len(narrative) > 30:
                    learning_type = "tip"
                    text = f"Refactored: {narrative[:250]}"

        elif obs_type == "feature":
            # Only capture features with meaningful narrative
            if narrative and len(narrative) > 40:
                if not narrative.startswith(("{", "Created/wrote", "Edited file")):
                    learning_type = "tip"
                    text = narrative[:250]

        if learning_type and text:
            # Deduplicate: skip if identical text already exists for this session
            existing = conn.execute(
                "SELECT id FROM learnings WHERE source = ? AND text = ? LIMIT 1",
                (memory_session_id, text),
            ).fetchone()
            if not existing:
                conn.execute(
                    "INSERT INTO learnings (project_id, text, type, source, ts) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (project_id, text, learning_type, memory_session_id, now),
                )
                count += 1

    if count > 0:
        conn.commit()
    return count


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _looks_like_insight(text: str) -> bool:
    """Return True if the text looks like a real insight, not a file listing or path."""
    if not text or len(text) < 15:
        return False
    # File listing output: mostly .html/.ts/.py/.md filenames
    lines = text.strip().splitlines()
    if len(lines) > 3:
        file_like = sum(1 for l in lines if l.strip().endswith(
            (".html", ".ts", ".tsx", ".py", ".js", ".md", ".json", ".css")
        ))
        if file_like > len(lines) * 0.6:
            return False
    # Looks like just a file path
    if text.startswith("/") and " " not in text:
        return False
    # Bash command listing
    _noisy = ("Edited file:", "Created/wrote file:", "analytics.html", "base.html")
    if any(text.startswith(p) for p in _noisy):
        return False
    return True


def _clean_narrative(raw: str) -> str:
    """Extract readable text from narrative — strip JSON blobs."""
    if not raw:
        return ""
    stripped = raw.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        # Try to extract stdout from tool output JSON
        try:
            obj = json.loads(stripped)
            if isinstance(obj, dict):
                stdout = obj.get("stdout", "")
                if stdout and len(stdout) > 10:
                    return stdout.strip()[:300]
            return ""
        except Exception:
            return ""
    return stripped


def _parse_json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(x) for x in parsed if x]
    except (json.JSONDecodeError, TypeError):
        pass
    return []
