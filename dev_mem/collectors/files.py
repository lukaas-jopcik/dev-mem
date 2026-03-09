"""
dev_mem.collectors.files — watchdog-based file-change daemon.

Runs as a long-lived daemon:

    python3 -m dev_mem.collectors.files

Watches all project directories registered in the database.
Writes a PID file to ~/.dev-mem/file-watcher.pid and logs to
~/.dev-mem/logs/files.log.  Stops cleanly on SIGTERM / SIGINT.
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from dev_mem.settings import DATA_DIR

if TYPE_CHECKING:
    from dev_mem.db import Database

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PID_FILE: Path = DATA_DIR / "file-watcher.pid"
LOG_DIR: Path = DATA_DIR / "logs"
LOG_FILE: Path = LOG_DIR / "files.log"

# Extensions treated as binary / uninteresting
_BINARY_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".pyc", ".pyo", ".pyd",
        ".so", ".dylib", ".dll", ".exe",
        ".o", ".a", ".lib",
        ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".ico", ".webp",
        ".mp3", ".mp4", ".wav", ".avi", ".mov", ".mkv",
        ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
        ".pdf", ".docx", ".xlsx", ".pptx",
        ".db", ".sqlite", ".sqlite3",
        ".DS_Store",
    }
)

# Directory names to exclude entirely
_EXCLUDED_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        "node_modules",
        "__pycache__",
        ".tox",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        "dist",
        "build",
        ".venv",
        "venv",
        "env",
        ".env",
    }
)

# File name fragments that mark a file as sensitive / ignorable
_SENSITIVE_NAME_FRAGMENTS: tuple[str, ...] = (
    ".env",
    "id_rsa",
    "id_ed25519",
    "credentials",
    ".pem",
)


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def _setup_logging() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("dev_mem.files")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        )
        logger.addHandler(handler)
    return logger


# ---------------------------------------------------------------------------
# Path filters
# ---------------------------------------------------------------------------

def _should_ignore(path_str: str) -> bool:
    """Return True if this path should be skipped."""
    p = Path(path_str)
    for part in p.parts:
        if part in _EXCLUDED_DIRS:
            return True
    name_lower = p.name.lower()
    if any(frag in name_lower for frag in _SENSITIVE_NAME_FRAGMENTS):
        return True
    if p.suffix.lower() in _BINARY_EXTENSIONS:
        return True
    return False


# ---------------------------------------------------------------------------
# Watchdog event handler factory
# ---------------------------------------------------------------------------

def _make_handler(db: "Database", logger: logging.Logger):
    """Return a watchdog FileSystemEventHandler bound to *db*."""
    from watchdog.events import FileSystemEventHandler  # type: ignore[import]

    class _Handler(FileSystemEventHandler):
        def _record(self, action: str, src_path: str) -> None:
            if _should_ignore(src_path):
                return
            try:
                project_id: Optional[int] = None
                row = db.get_project_by_path(os.path.dirname(src_path))
                if row:
                    project_id = row["id"]
                db._conn.execute(
                    "INSERT INTO file_events (project_id, path, action, ts) "
                    "VALUES (?, ?, ?, datetime('now'))",
                    (project_id, src_path, action),
                )
                db._conn.commit()
                logger.debug("%s %s", action, src_path)
            except Exception as exc:
                logger.warning("file_event error: %s", exc)

        def on_created(self, event) -> None:  # type: ignore[override]
            if not event.is_directory:
                self._record("created", event.src_path)

        def on_modified(self, event) -> None:  # type: ignore[override]
            if not event.is_directory:
                self._record("modified", event.src_path)

        def on_deleted(self, event) -> None:  # type: ignore[override]
            if not event.is_directory:
                self._record("deleted", event.src_path)

    return _Handler()


# ---------------------------------------------------------------------------
# PID file helpers
# ---------------------------------------------------------------------------

def _write_pid() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")


def _remove_pid() -> None:
    try:
        PID_FILE.unlink(missing_ok=True)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    logger = _setup_logging()
    logger.info("dev-mem file-watcher starting (pid=%d)", os.getpid())

    try:
        from watchdog.observers import Observer  # type: ignore[import]
    except ImportError:
        logger.error("watchdog not installed; run: pip install watchdog")
        sys.exit(1)

    from dev_mem.db import Database
    from dev_mem.settings import DB_PATH

    _write_pid()
    _running = True

    def _shutdown(signum: int, frame: object) -> None:  # noqa: ARG001
        nonlocal _running
        logger.info("Received signal %d — shutting down", signum)
        _running = False

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    db = Database(DB_PATH)
    observer = Observer()
    handler = _make_handler(db, logger)

    # Discover watched directories from the projects table
    watched: list[str] = []
    try:
        rows = db._conn.execute(
            "SELECT path FROM projects WHERE active = 1"
        ).fetchall()
        for row in rows:
            path = row[0]
            if os.path.isdir(path):
                observer.schedule(handler, path, recursive=True)
                watched.append(path)
                logger.info("Watching: %s", path)
    except Exception as exc:
        logger.warning("Could not load projects: %s", exc)

    if not watched:
        logger.warning("No active project directories — watcher is idle.")

    observer.start()
    logger.info("Observer started; watching %d director(y/ies)", len(watched))

    try:
        while _running:
            time.sleep(0.5)
    finally:
        observer.stop()
        observer.join()
        db.close()
        _remove_pid()
        logger.info("dev-mem file-watcher stopped")


# ---------------------------------------------------------------------------
# Module entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    main()
