"""
context_builder.py — Build structured Markdown context files for dev-mem analyze.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dev_mem.db import Database

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONTEXT_DIR = Path.home() / ".dev-mem" / "context"
CHARS_PER_TOKEN = 4

# Priority order for truncation (most important first)
_PRIORITY = ["errors", "prompts", "git_events", "commands", "file_events"]


# ---------------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------------

def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN)


def _cap(text: str, max_tokens: int) -> str:
    limit = max_tokens * CHARS_PER_TOKEN
    if len(text) <= limit:
        return text
    return text[:limit] + "\n\n*(truncated)*"


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def _since_iso(hours: int = 24) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


def _section_commands(db: "Database", project_id: int, since: str, top_n: int = 20) -> str:
    rows = db._conn.execute(
        """
        SELECT cmd, COUNT(*) AS n, MAX(exit_code) AS last_exit
        FROM commands
        WHERE project_id IS ? AND ts >= ?
        GROUP BY cmd_hash
        ORDER BY n DESC
        LIMIT ?
        """,
        (project_id, since, top_n),
    ).fetchall()
    if not rows:
        return ""
    lines = ["### Top Commands", "| # | Command | Runs | Last Exit |", "|---|---------|------|-----------|"]
    for i, r in enumerate(rows, 1):
        exit_str = str(r["last_exit"]) if r["last_exit"] is not None else "-"
        lines.append(f"| {i} | `{r['cmd'][:80]}` | {r['n']} | {exit_str} |")
    return "\n".join(lines)


def _section_git(db: "Database", project_id: int, since: str) -> str:
    rows = db._conn.execute(
        """
        SELECT hash, message, insertions, deletions, ts
        FROM git_events
        WHERE project_id IS ? AND ts >= ?
        ORDER BY ts DESC
        """,
        (project_id, since),
    ).fetchall()
    if not rows:
        return ""
    lines = ["### Git Commits"]
    for r in rows:
        short_hash = r["hash"][:7]
        lines.append(f"- `{short_hash}` {r['message']} (+{r['insertions']}/-{r['deletions']}) @ {r['ts'][:16]}")
    return "\n".join(lines)


def _section_errors(db: "Database", project_id: int, since: str, top_n: int = 10) -> str:
    rows = db._conn.execute(
        """
        SELECT error_text, error_hash, count, last_seen
        FROM errors
        WHERE project_id IS ? AND last_seen >= ?
        ORDER BY count DESC
        LIMIT ?
        """,
        (project_id, since, top_n),
    ).fetchall()
    if not rows:
        return ""
    lines = ["### Errors", "| Count | Type | Last Seen | Sample |", "|-------|------|-----------|--------|"]
    from dev_mem.analyzer.error_patterns import extract_error_type
    for r in rows:
        etype = extract_error_type(r["error_text"])
        sample = r["error_text"][:60].replace("\n", " ")
        lines.append(f"| {r['count']} | {etype} | {r['last_seen'][:16]} | {sample} |")
    return "\n".join(lines)


def _section_claude(db: "Database", project_id: int, since: str) -> str:
    rows = db._conn.execute(
        """
        SELECT tool, input_summary, output_summary, ts
        FROM claude_sessions
        WHERE project_id IS ? AND ts >= ?
        ORDER BY ts DESC
        LIMIT 10
        """,
        (project_id, since),
    ).fetchall()
    if not rows:
        return ""
    lines = ["### Claude Sessions"]
    for r in rows:
        lines.append(f"- [{r['ts'][:16]}] **{r['tool']}**: {r['input_summary'][:80]}")
    return "\n".join(lines)


def _section_learnings(db: "Database", project_id: int, since: str) -> str:
    rows = db._conn.execute(
        """
        SELECT text, type, ts FROM learnings
        WHERE project_id IS ? AND ts >= ?
        ORDER BY ts DESC
        """,
        (project_id, since),
    ).fetchall()
    if not rows:
        return ""
    lines = ["### Learnings"]
    for r in rows:
        tag = f" `[{r['type']}]`" if r["type"] else ""
        lines.append(f"- {r['text']}{tag}")
    return "\n".join(lines)


def _section_prompts(db: "Database", project_id: int, since: str) -> str:
    rows = db._conn.execute(
        """
        SELECT text, score, tags, ts FROM prompts
        WHERE project_id IS ? AND ts >= ?
        ORDER BY score DESC
        """,
        (project_id, since),
    ).fetchall()
    if not rows:
        return ""
    lines = ["### Prompts (scored)", "| Score | Tags | Text |", "|-------|------|------|"]
    for r in rows:
        tags_str = ", ".join(json.loads(r["tags"]) if r["tags"] else [])
        lines.append(f"| {r['score']} | {tags_str} | {r['text'][:80]} |")
    return "\n".join(lines)


def _section_decisions(db: "Database", project_id: int, since: str) -> str:
    rows = db._conn.execute(
        """
        SELECT title, context, reasoning, ts FROM decisions
        WHERE project_id IS ? AND ts >= ?
        ORDER BY ts DESC
        """,
        (project_id, since),
    ).fetchall()
    if not rows:
        return ""
    lines = ["### Decisions Made"]
    for r in rows:
        lines.append(f"**{r['title']}** ({r['ts'][:10]})")
        if r["context"]:
            lines.append(f"  Context: {r['context'][:120]}")
        if r["reasoning"]:
            lines.append(f"  Reasoning: {r['reasoning'][:120]}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Context type builders
# ---------------------------------------------------------------------------

def _build_today(db: "Database", project_id: int, max_tokens: int) -> str:
    since = _since_iso(24)
    parts = [
        "## Today (last 24h)\n",
        _section_commands(db, project_id, since),
        _section_git(db, project_id, since),
        _section_errors(db, project_id, since),
        _section_claude(db, project_id, since),
        _section_learnings(db, project_id, since),
    ]
    return _cap("\n\n".join(p for p in parts if p), max_tokens)


def _build_prompts(db: "Database", project_id: int, max_tokens: int) -> str:
    since = _since_iso(24 * 30)  # last 30 days
    rows = db._conn.execute(
        """
        SELECT text, score, tags, ts FROM prompts
        WHERE project_id IS ?
        ORDER BY score DESC
        """,
        (project_id,),
    ).fetchall()
    if not rows:
        return "## Prompts\n\n_No prompts recorded._"

    scores = [r["score"] for r in rows]
    avg = sum(scores) / len(scores)
    best = rows[0]
    worst = sorted(rows, key=lambda r: r["score"])[0]

    lines = [
        "## Prompt Analysis\n",
        f"Total prompts: {len(rows)} | Avg score: {avg:.1f}/100\n",
        "### Best Prompt",
        f"Score: {best['score']} | {best['text'][:200]}",
        "",
        "### Worst Prompt",
        f"Score: {worst['score']} | {worst['text'][:200]}",
        "",
        _section_prompts(db, project_id, since),
    ]
    return _cap("\n".join(lines), max_tokens)


def _build_errors(db: "Database", project_id: int, max_tokens: int) -> str:
    since = _since_iso(24 * 7)
    header = "## Error Patterns (last 7 days)\n"
    section = _section_errors(db, project_id, since, top_n=10)
    return _cap(header + "\n" + section, max_tokens)


def _build_week(db: "Database", project_id: int, max_tokens: int) -> str:
    lines = ["## Weekly Summary (last 7 days)\n"]
    for delta in range(6, -1, -1):
        day = (datetime.now(timezone.utc) - timedelta(days=delta)).strftime("%Y-%m-%d")
        since = f"{day}T00:00:00+00:00"
        until = f"{day}T23:59:59+00:00"

        commits = db._conn.execute(
            "SELECT COUNT(*) AS n FROM git_events WHERE project_id IS ? AND ts BETWEEN ? AND ?",
            (project_id, since, until),
        ).fetchone()["n"]

        errors = db._conn.execute(
            "SELECT COUNT(*) AS n FROM errors WHERE project_id IS ? AND last_seen BETWEEN ? AND ?",
            (project_id, since, until),
        ).fetchone()["n"]

        avg_score_row = db._conn.execute(
            "SELECT AVG(score) AS avg FROM prompts WHERE project_id IS ? AND ts BETWEEN ? AND ?",
            (project_id, since, until),
        ).fetchone()
        avg_score = round(avg_score_row["avg"] or 0, 1)

        lines.append(f"- **{day}**: commits={commits}, errors={errors}, prompt_avg={avg_score}")

    return _cap("\n".join(lines), max_tokens)


def _build_learning(db: "Database", project_id: int, max_tokens: int) -> str:
    rows = db._conn.execute(
        """
        SELECT text, type, source, ts FROM learnings
        WHERE project_id IS ?
        ORDER BY type, ts
        """,
        (project_id,),
    ).fetchall()

    decisions = db._conn.execute(
        """
        SELECT title, context, reasoning, alternatives, ts FROM decisions
        WHERE project_id IS ?
        ORDER BY ts
        """,
        (project_id,),
    ).fetchall()

    lines = ["## Learnings & Decisions\n"]

    # Group learnings by type
    by_type: dict[str, list] = {}
    for r in rows:
        key = r["type"] or "general"
        by_type.setdefault(key, []).append(r["text"])

    lines.append("### Learnings by Type")
    for ltype, texts in by_type.items():
        lines.append(f"\n**{ltype}**")
        for t in texts:
            lines.append(f"- {t}")

    lines.append("\n### Decisions Made")
    for d in decisions:
        lines.append(f"\n**{d['title']}** ({d['ts'][:10]})")
        if d["context"]:
            lines.append(f"  Context: {d['context'][:150]}")
        if d["reasoning"]:
            lines.append(f"  Reasoning: {d['reasoning'][:150]}")
        if d["alternatives"]:
            lines.append(f"  Alternatives: {d['alternatives'][:100]}")

    return _cap("\n".join(lines), max_tokens)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_context(
    db: "Database",
    project_id: int,
    context_type: str,
    max_tokens: int = 4000,
) -> str:
    """
    Build a structured Markdown context string for *context_type*.

    Supported types: "today", "prompts", "project", "errors", "week", "learning"
    Capped at *max_tokens* (estimated at 4 chars/token).
    """
    project_row = db._conn.execute(
        "SELECT name FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    project_name = project_row["name"] if project_row else str(project_id)

    header = f"# dev-mem context: {context_type} | Project: {project_name}\n\n"

    dispatch = {
        "today": _build_today,
        "project": _build_today,  # alias
        "prompts": _build_prompts,
        "errors": _build_errors,
        "week": _build_week,
        "learning": _build_learning,
    }
    builder = dispatch.get(context_type, _build_today)
    body = builder(db, project_id, max_tokens - _estimate_tokens(header))
    return header + body


def save_context(content: str, context_type: str) -> Path:
    """
    Save *content* to ~/.dev-mem/context/analyze_{context_type}.md.

    Returns the path of the written file.
    """
    CONTEXT_DIR.mkdir(parents=True, exist_ok=True)
    path = CONTEXT_DIR / f"analyze_{context_type}.md"
    path.write_text(content, encoding="utf-8")
    return path
