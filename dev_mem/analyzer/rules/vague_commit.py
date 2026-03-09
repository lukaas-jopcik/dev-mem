"""
vague_commit.py — Warn when a git commit message is a single vague verb.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from dev_mem.db import Database

_VAGUE_RE = re.compile(
    r"^(fix|update|change|misc|wip|stuff|minor)$",
    re.IGNORECASE,
)


def check(
    db: "Database",
    project_id: int,
    date: Optional[str] = None,
) -> dict | None:
    """
    Return a warning if any git commit on *date* has a message matching only
    a single vague verb (fix, update, change, misc, wip, stuff, minor).
    """
    day = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    since = f"{day}T00:00:00+00:00"
    until = f"{day}T23:59:59+00:00"

    rows = db._conn.execute(
        """
        SELECT message, hash FROM git_events
        WHERE project_id IS ? AND ts BETWEEN ? AND ?
        """,
        (project_id, since, until),
    ).fetchall()

    vague = [r for r in rows if _VAGUE_RE.match(r["message"].strip())]
    if not vague:
        return None

    examples = ", ".join(f'"{r["message"]}"' for r in vague[:3])
    return {
        "rule": "vague-commit",
        "severity": "warning",
        "message": f"{len(vague)} vague commit message(s) detected today.",
        "detail": f"Examples: {examples}",
    }
