"""
low_prompt_day.py — Warn when average prompt score for the day is below 50.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from dev_mem.db import Database


def check(
    db: "Database",
    project_id: int,
    date: Optional[str] = None,
) -> dict | None:
    """
    Return a warning if the average prompt score for *date* is below 50.
    Returns None if no prompts were recorded that day.
    """
    day = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    since = f"{day}T00:00:00+00:00"
    until = f"{day}T23:59:59+00:00"

    row = db._conn.execute(
        """
        SELECT AVG(score) AS avg, COUNT(*) AS n FROM prompts
        WHERE project_id IS ? AND ts BETWEEN ? AND ?
        """,
        (project_id, since, until),
    ).fetchone()

    if not row or row["n"] == 0 or row["avg"] is None:
        return None

    avg = row["avg"]
    if avg >= 50:
        return None

    return {
        "rule": "low-prompt-day",
        "severity": "warning",
        "message": f"Average prompt quality is low: {avg:.1f}/100 across {row['n']} prompt(s).",
        "detail": "Consider adding more context, output format, and examples to your prompts.",
    }
