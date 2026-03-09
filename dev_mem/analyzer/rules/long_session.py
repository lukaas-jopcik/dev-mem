"""
long_session.py — Warn when a session exceeds 4 hours (14400 seconds).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from dev_mem.db import Database

THRESHOLD_SECS = 14400  # 4 hours


def check(
    db: "Database",
    project_id: int,
    date: Optional[str] = None,
) -> dict | None:
    """
    Return a warning if any session on *date* lasted longer than 4 hours.
    """
    day = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    since = f"{day}T00:00:00+00:00"
    until = f"{day}T23:59:59+00:00"

    row = db._conn.execute(
        """
        SELECT id, duration_sec, start_ts FROM sessions
        WHERE project_id IS ? AND start_ts BETWEEN ? AND ?
          AND duration_sec > ?
        ORDER BY duration_sec DESC
        LIMIT 1
        """,
        (project_id, since, until, THRESHOLD_SECS),
    ).fetchone()

    if not row:
        return None

    hours = row["duration_sec"] // 3600
    minutes = (row["duration_sec"] % 3600) // 60
    return {
        "rule": "long-session",
        "severity": "warning",
        "message": f"Session exceeded 4 hours: {hours}h {minutes}m.",
        "detail": f"Session started at {row['start_ts'][:16]}. Consider taking regular breaks.",
    }
