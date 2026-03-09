"""
daily_summary.py — Daily Markdown summary generator.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from dev_mem.analyzer.rules import run_rules

if TYPE_CHECKING:
    from dev_mem.db import Database

DAILY_DIR = Path.home() / ".dev-mem" / "daily"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _day_range(day_str: str) -> tuple[str, str]:
    """Return (start_iso, end_iso) for a given YYYY-MM-DD day string."""
    return f"{day_str}T00:00:00+00:00", f"{day_str}T23:59:59+00:00"


def _fmt_duration(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m = rem // 60
    return f"{h}h {m}m"


def _session_total(db: "Database", project_id: int, since: str, until: str) -> int:
    row = db._conn.execute(
        """
        SELECT COALESCE(SUM(duration_sec), 0) AS total
        FROM sessions
        WHERE project_id IS ? AND start_ts BETWEEN ? AND ?
        """,
        (project_id, since, until),
    ).fetchone()
    return row["total"] if row else 0


# ---------------------------------------------------------------------------
# Section generators
# ---------------------------------------------------------------------------

def _section_at_a_glance(db: "Database", project_id: int, since: str, until: str) -> str:
    total_secs = _session_total(db, project_id, since, until)
    commits = db._conn.execute(
        "SELECT COUNT(*) AS n FROM git_events WHERE project_id IS ? AND ts BETWEEN ? AND ?",
        (project_id, since, until),
    ).fetchone()["n"]

    avg_row = db._conn.execute(
        "SELECT AVG(score) AS avg FROM prompts WHERE project_id IS ? AND ts BETWEEN ? AND ?",
        (project_id, since, until),
    ).fetchone()
    avg_score = round(avg_row["avg"] or 0)

    return (
        "## At a Glance\n\n"
        f"Time tracked: {_fmt_duration(total_secs)} | "
        f"Commits: {commits} | "
        f"Prompt score avg: {avg_score}/100"
    )


def _section_alerts(db: "Database", project_id: int, day_str: str) -> str:
    alerts = run_rules(db, project_id, day_str)
    if not alerts:
        return ""
    lines = ["## Alerts"]
    for a in alerts:
        icon = "🔴" if a["severity"] == "error" else "⚠️"
        lines.append(f"- {icon} **{a['rule']}**: {a['message']}")
        if a.get("detail"):
            lines.append(f"  _{a['detail']}_")
    return "\n".join(lines)


def _section_what_got_done(db: "Database", project_id: int, since: str, until: str) -> str:
    rows = db._conn.execute(
        """
        SELECT message, hash, insertions, deletions FROM git_events
        WHERE project_id IS ? AND ts BETWEEN ? AND ?
        ORDER BY ts
        """,
        (project_id, since, until),
    ).fetchall()
    if not rows:
        return "## What Got Done\n\n_No commits today._"
    lines = ["## What Got Done"]
    for r in rows:
        lines.append(f"- `{r['hash'][:7]}` {r['message']} (+{r['insertions']}/-{r['deletions']})")
    return "\n".join(lines)


def _section_learnings(db: "Database", project_id: int, since: str, until: str) -> str:
    rows = db._conn.execute(
        """
        SELECT text, type FROM learnings
        WHERE project_id IS ? AND ts BETWEEN ? AND ?
        ORDER BY ts
        """,
        (project_id, since, until),
    ).fetchall()
    if not rows:
        return "## Learnings\n\n_No learnings recorded today._"
    lines = ["## Learnings"]
    for r in rows:
        tag = f" `[{r['type']}]`" if r["type"] else ""
        lines.append(f"- {r['text']}{tag}")
    return "\n".join(lines)


def _section_decisions(db: "Database", project_id: int, since: str, until: str) -> str:
    rows = db._conn.execute(
        """
        SELECT title, context, reasoning FROM decisions
        WHERE project_id IS ? AND ts BETWEEN ? AND ?
        ORDER BY ts
        """,
        (project_id, since, until),
    ).fetchall()
    if not rows:
        return "## Decisions Made\n\n_No decisions recorded today._"
    lines = ["## Decisions Made"]
    for r in rows:
        lines.append(f"### {r['title']}")
        if r["context"]:
            lines.append(f"**Context:** {r['context']}")
        if r["reasoning"]:
            lines.append(f"**Reasoning:** {r['reasoning']}")
    return "\n".join(lines)


def _section_prompt_analysis(db: "Database", project_id: int, since: str, until: str) -> str:
    rows = db._conn.execute(
        """
        SELECT text, score, tags FROM prompts
        WHERE project_id IS ? AND ts BETWEEN ? AND ?
        ORDER BY score ASC
        LIMIT 1
        """,
        (project_id, since, until),
    ).fetchall()
    if not rows:
        return "## Prompt Analysis\n\n_No prompts recorded today._"
    worst = rows[0]
    tags = json.loads(worst["tags"]) if worst["tags"] else []
    lines = [
        "## Prompt Analysis",
        f"**Worst prompt today** (score: {worst['score']}/100)",
        f"> {worst['text'][:300]}",
        "",
        f"Tags: {', '.join(tags) if tags else 'none'}",
    ]
    return "\n".join(lines)


def _section_recommendation(db: "Database", project_id: int, day_str: str) -> str:
    alerts = run_rules(db, project_id, day_str)
    if not alerts:
        return "## Recommendation for Tomorrow\n\n- Keep up the current pace. Review your prompts for quality improvements."

    top = alerts[0]
    msg = top["message"]
    return f"## Recommendation for Tomorrow\n\n- Address: {msg}"


def _section_time_breakdown(db: "Database", project_id: int, since: str, until: str) -> str:
    rows = db._conn.execute(
        """
        SELECT start_ts, end_ts, duration_sec FROM sessions
        WHERE project_id IS ? AND start_ts BETWEEN ? AND ?
        ORDER BY start_ts
        """,
        (project_id, since, until),
    ).fetchall()
    if not rows:
        return "## Time Breakdown\n\n_No sessions recorded today._"
    lines = ["## Time Breakdown", "| Start | End | Duration |", "|-------|-----|----------|"]
    for r in rows:
        end = r["end_ts"][:16] if r["end_ts"] else "ongoing"
        dur = _fmt_duration(r["duration_sec"]) if r["duration_sec"] else "-"
        lines.append(f"| {r['start_ts'][:16]} | {end} | {dur} |")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_daily_summary(
    db: "Database",
    project_id: int,
    date: Optional[str] = None,
) -> str:
    """
    Generate a Markdown daily summary for *project_id* on *date* (YYYY-MM-DD).
    Defaults to today (UTC) if *date* is None.
    """
    day_str = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    since, until = _day_range(day_str)

    project_row = db._conn.execute(
        "SELECT name FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    project_name = project_row["name"] if project_row else str(project_id)

    sections = [
        f"# Daily Summary — {day_str} [Project: {project_name}]",
        "",
        _section_at_a_glance(db, project_id, since, until),
        "",
        _section_alerts(db, project_id, day_str),
        "",
        _section_what_got_done(db, project_id, since, until),
        "",
        _section_learnings(db, project_id, since, until),
        "",
        _section_decisions(db, project_id, since, until),
        "",
        _section_prompt_analysis(db, project_id, since, until),
        "",
        _section_recommendation(db, project_id, day_str),
        "",
        _section_time_breakdown(db, project_id, since, until),
    ]
    return "\n".join(s for s in sections)


def run_daily_job(db: "Database") -> None:
    """
    Generate daily summaries for ALL active projects and save to disk.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rows = db._conn.execute(
        "SELECT id, name FROM projects WHERE active = 1"
    ).fetchall()

    DAILY_DIR.mkdir(parents=True, exist_ok=True)

    for row in rows:
        project_id = row["id"]
        project_name = row["name"].replace(" ", "-").lower()
        content = generate_daily_summary(db, project_id, today)

        file_path = DAILY_DIR / f"{today}-{project_name}.md"
        file_path.write_text(content, encoding="utf-8")

        # Persist to DB
        now_iso = datetime.now(timezone.utc).isoformat()
        db._conn.execute(
            """
            INSERT INTO daily_summaries (project_id, date, md_content, generated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(project_id, date) DO UPDATE SET
                md_content = excluded.md_content,
                generated_at = excluded.generated_at
            """,
            (project_id, today, content, now_iso),
        )
    db._conn.commit()


def check_missing_summaries(db: "Database") -> None:
    """
    Check the last 7 days for missing daily summaries and generate them.

    This provides catch-up logic for days where the job did not run.
    """
    today = datetime.now(timezone.utc).date()
    rows = db._conn.execute(
        "SELECT id, name FROM projects WHERE active = 1"
    ).fetchall()

    DAILY_DIR.mkdir(parents=True, exist_ok=True)

    for row in rows:
        project_id = row["id"]
        project_name = row["name"].replace(" ", "-").lower()

        for delta in range(7):
            check_date = today - timedelta(days=delta)
            day_str = check_date.strftime("%Y-%m-%d")

            existing = db._conn.execute(
                "SELECT id FROM daily_summaries WHERE project_id = ? AND date = ?",
                (project_id, day_str),
            ).fetchone()

            if existing:
                continue

            content = generate_daily_summary(db, project_id, day_str)
            file_path = DAILY_DIR / f"{day_str}-{project_name}.md"
            file_path.write_text(content, encoding="utf-8")

            now_iso = datetime.now(timezone.utc).isoformat()
            db._conn.execute(
                """
                INSERT INTO daily_summaries (project_id, date, md_content, generated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(project_id, date) DO NOTHING
                """,
                (project_id, day_str, content, now_iso),
            )
    db._conn.commit()
