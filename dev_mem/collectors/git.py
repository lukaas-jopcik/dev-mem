"""
dev_mem.collectors.git — post-commit hook handler.

Invoked as a short-lived subprocess directly from .git/hooks/post-commit:

    python3 -m dev_mem.collectors.git

Must complete within 200 ms; a threading.Timer kills it otherwise.
Requires gitpython (listed in pyproject.toml dependencies).
"""

from __future__ import annotations

import os
import signal
import threading
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Hard timeout: 200 ms
# ---------------------------------------------------------------------------

_TIMEOUT_SECONDS = 0.200


def _self_kill() -> None:  # pragma: no cover
    os.kill(os.getpid(), signal.SIGKILL)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    timer = threading.Timer(_TIMEOUT_SECONDS, _self_kill)
    timer.daemon = True
    timer.start()
    try:
        _run()
    finally:
        timer.cancel()


def _run() -> None:
    try:
        import git as gitpython  # gitpython
    except ImportError:
        return  # soft-fail: gitpython not installed

    from dev_mem.db import Database
    from dev_mem.settings import DB_PATH

    # Discover repository from current working directory
    try:
        repo = gitpython.Repo(search_parent_directories=True)
    except gitpython.InvalidGitRepositoryError:
        return

    # Extract the most recent commit
    try:
        commit = repo.head.commit
    except Exception:
        return

    repo_root = str(Path(repo.working_dir).resolve())
    commit_hash: str = commit.hexsha
    message: str = (commit.message or "").strip()

    # Collect changed file paths
    changed_files: list[str] = []
    insertions = 0
    deletions = 0

    try:
        if commit.parents:
            diff = commit.parents[0].diff(commit)
        else:
            diff = commit.diff(gitpython.NULL_TREE)

        for d in diff:
            path = d.b_path or d.a_path
            if path:
                changed_files.append(path)

        stats = commit.stats
        insertions = stats.total.get("insertions", 0)
        deletions = stats.total.get("deletions", 0)
    except Exception:
        pass

    db = Database(DB_PATH)
    try:
        project_id: Optional[int] = None
        row = db.get_project_by_path(repo_root)
        if row:
            project_id = row["id"]

        db.insert_git_event(
            project_id=project_id,
            hash=commit_hash,
            message=message,
            files=changed_files,
            insertions=insertions,
            deletions=deletions,
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Module entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    main()
