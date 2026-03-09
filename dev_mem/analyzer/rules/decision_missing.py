"""
decision_missing.py — Warn when a project has 10+ commits but zero decisions recorded.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from dev_mem.db import Database

COMMIT_THRESHOLD = 10


def check(
    db: "Database",
    project_id: int,
    date: Optional[str] = None,
) -> dict | None:
    """
    Return a warning if the project has >= 10 total git commits but no
    decisions have ever been recorded for it.
    """
    commit_row = db._conn.execute(
        "SELECT COUNT(*) AS n FROM git_events WHERE project_id IS ?",
        (project_id,),
    ).fetchone()

    decision_row = db._conn.execute(
        "SELECT COUNT(*) AS n FROM decisions WHERE project_id IS ?",
        (project_id,),
    ).fetchone()

    total_commits = commit_row["n"] if commit_row else 0
    total_decisions = decision_row["n"] if decision_row else 0

    if total_commits < COMMIT_THRESHOLD or total_decisions > 0:
        return None

    return {
        "rule": "decision-missing",
        "severity": "warning",
        "message": f"Project has {total_commits} commits but no architectural decisions recorded.",
        "detail": "Use `dev-mem decision add` to document key technical choices and trade-offs.",
    }
