"""
rules/__init__.py — Rule engine runner for dev-mem alerts.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from dev_mem.analyzer.rules import (
    same_error_3x,
    same_error_5x,
    vague_commit,
    low_prompt_day,
    no_commit_3days,
    long_session,
    repeated_cmd_fail,
    decision_missing,
)

if TYPE_CHECKING:
    from dev_mem.db import Database

RULES = [
    same_error_3x,
    same_error_5x,
    vague_commit,
    low_prompt_day,
    no_commit_3days,
    long_session,
    repeated_cmd_fail,
    decision_missing,
]


def run_rules(
    db: "Database",
    project_id: int,
    date: Optional[str] = None,
) -> list[dict]:
    """
    Run all rules against *project_id* for the given *date* (YYYY-MM-DD).
    Returns a list of triggered alert dicts. Never raises.
    """
    day = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    alerts: list[dict] = []
    for rule in RULES:
        try:
            alert = rule.check(db, project_id, day)
            if alert:
                alerts.append(alert)
        except Exception:
            pass
    return alerts
