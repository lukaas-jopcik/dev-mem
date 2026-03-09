"""
no_commit_3days.py — Warn when an active project has no git commits for 3 days.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from dev_mem.db import Database


def check(
    db: "Database",
    project_id: int,
    date: Optional[str] = None,
) -> dict | None:
    """
    Return a warning if no git_events have been recorded for *project_id*
    in the 3 days up to and including *date*.
    """
    ref_date = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc) if date else datetime.now(timezone.utc)
    cutoff = (ref_date - timedelta(days=3)).isoformat()
    until = f"{date}T23:59:59+00:00" if date else ref_date.isoformat()

    row = db._conn.execute(
        """
        SELECT COUNT(*) AS n FROM git_events
        WHERE project_id IS ? AND ts BETWEEN ? AND ?
        """,
        (project_id, cutoff, until),
    ).fetchone()

    if row and row["n"] > 0:
        return None

    return {
        "rule": "no-commit-3days",
        "severity": "warning",
        "message": "No git commits in the last 3 days for this project.",
        "detail": "Consider committing your work-in-progress or reviewing blocked tasks.",
    }
