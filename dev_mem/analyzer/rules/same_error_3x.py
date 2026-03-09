"""
same_error_3x.py — Warn when the same error hash appears 3+ times in 7 days.
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
    Return a warning alert if any error hash has count >= 3 within the last
    7 days relative to *date*. Returns the most frequent such error.
    """
    ref_date = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc) if date else datetime.now(timezone.utc)
    cutoff = (ref_date - timedelta(days=7)).isoformat()

    row = db._conn.execute(
        """
        SELECT error_hash, error_text, count FROM errors
        WHERE project_id IS ? AND last_seen >= ? AND count >= 3
        ORDER BY count DESC
        LIMIT 1
        """,
        (project_id, cutoff),
    ).fetchone()

    if not row:
        return None

    sample = row["error_text"][:120].replace("\n", " ")
    return {
        "rule": "same-error-3x",
        "severity": "warning",
        "message": f"Same error occurred {row['count']}x in the last 7 days.",
        "detail": f"Hash: {row['error_hash'][:10]}... Sample: {sample}",
    }
