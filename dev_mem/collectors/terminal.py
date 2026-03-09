"""
dev_mem.collectors.terminal — PROMPT_COMMAND / preexec shell hook handler.

Invoked as a short-lived subprocess by the shell after each command:

    python3 -m dev_mem.collectors.terminal \\
        --cmd "git status" \\
        --duration 1234 \\
        --exit-code 0 \\
        --cwd "/home/user/project"

The process must finish within 10 ms; a threading.Timer kills it otherwise.
Deduplication (same cmd hash within 1 second) is handled by db.insert_command.
"""

from __future__ import annotations

import argparse
import os
import signal
import threading
from typing import Optional

# ---------------------------------------------------------------------------
# Hard timeout: 10 ms
# ---------------------------------------------------------------------------

_TIMEOUT_SECONDS = 0.010


def _self_kill() -> None:  # pragma: no cover
    os.kill(os.getpid(), signal.SIGKILL)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="dev_mem.collectors.terminal",
        description="Record a shell command to the dev-mem database.",
        add_help=False,
    )
    parser.add_argument("--cmd",       required=True)
    parser.add_argument("--duration",  type=int, default=0)
    parser.add_argument("--exit-code", type=int, default=0, dest="exit_code")
    parser.add_argument("--cwd",       default=os.getcwd())
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> None:
    timer = threading.Timer(_TIMEOUT_SECONDS, _self_kill)
    timer.daemon = True
    timer.start()
    try:
        _run(argv)
    finally:
        timer.cancel()


def _run(argv: Optional[list[str]] = None) -> None:
    args = _parse_args(argv)

    raw_cmd = args.cmd.strip()
    if not raw_cmd:
        return

    # Lazy imports after arg parsing (faster failure on bad invocations)
    from dev_mem.collectors.sensitive_filter import filter_command
    from dev_mem.db import Database
    from dev_mem.settings import Settings, DB_PATH

    settings = Settings()
    ignore_commands: list[str] = settings.get("ignore_commands", [])

    # Skip ignored base commands
    base_cmd = raw_cmd.split()[0]
    if base_cmd in ignore_commands:
        return

    # Sensitive data filtering
    filtered_cmd = filter_command(raw_cmd)

    db = Database(DB_PATH)
    try:
        # Auto-detect project from cwd
        project_id: Optional[int] = None
        row = db.get_project_by_path(args.cwd)
        if row:
            project_id = row["id"]

        # insert_command handles dedup internally (same hash within 1 s)
        db.insert_command(
            project_id=project_id,
            cmd=filtered_cmd,
            duration_ms=args.duration,
            exit_code=args.exit_code,
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Module entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    main()
