"""
repeated_cmd_fail.py — Warn when the same command fails (exit_code != 0) more than 3 times.
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
    Return a warning if any command recorded on *date* with a non-zero exit
    code appears more than 3 times (same cmd_hash, exit_code != 0).
    """
    day = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    since = f"{day}T00:00:00+00:00"
    until = f"{day}T23:59:59+00:00"

    row = db._conn.execute(
        """
        SELECT cmd, cmd_hash, COUNT(*) AS fail_count
        FROM commands
        WHERE project_id IS ?
          AND ts BETWEEN ? AND ?
          AND exit_code IS NOT NULL
          AND exit_code != 0
        GROUP BY cmd_hash
        HAVING fail_count > 3
        ORDER BY fail_count DESC
        LIMIT 1
        """,
        (project_id, since, until),
    ).fetchone()

    if not row:
        return None

    return {
        "rule": "repeated-cmd-fail",
        "severity": "warning",
        "message": f"Command failed {row['fail_count']}x today: `{row['cmd'][:80]}`",
        "detail": "Investigate the root cause instead of retrying the same failing command.",
    }
