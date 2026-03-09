"""
dev_mem.collectors.session_start — SessionStart hook for Claude Code.

Prints a <dev-mem-context> block to stdout which Claude Code injects
into the system prompt at the start of each session.

Hard timeout: 500 ms.
"""

from __future__ import annotations

import os
import signal
import threading


_TIMEOUT_SECONDS = 1.5


def _self_kill() -> None:  # pragma: no cover
    os.kill(os.getpid(), signal.SIGKILL)


def main() -> None:
    timer = threading.Timer(_TIMEOUT_SECONDS, _self_kill)
    timer.daemon = True
    timer.start()
    try:
        from dev_mem.memory.context_injector import write_context_to_stdout
        write_context_to_stdout()
    except Exception:  # noqa: BLE001
        pass  # Never interrupt the session
    finally:
        timer.cancel()


if __name__ == "__main__":
    main()
