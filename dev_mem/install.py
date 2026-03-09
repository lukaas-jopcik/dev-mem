"""
install.py — Programmatic installation helpers for dev-mem.

Called by:
  dev-mem install   → run_install(settings)
  dev-mem init      → init_project(cwd, settings)
  dev-mem rollback-hooks → rollback(settings)
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dev_mem.settings import Settings

_HOOKS_MARKER = "# dev-mem hooks"
_GLOBAL_HOOKS_DIR = Path.home() / ".config" / "git" / "hooks"


def run_install(settings: "Settings") -> None:
    """
    Full first-time setup:
      1. Create data directories
      2. Run database migrations
      3. Install shell hooks (zsh/bash)
      4. Install global git post-commit hook
      5. Register cron job for daily analysis
      6. Start file watcher daemon
    """
    _create_dirs(settings)
    _run_migrations(settings)
    _install_shell_hooks()
    _install_git_hook()
    _install_cron()
    _start_file_watcher()


def init_project(cwd: Path, settings: "Settings") -> None:
    """Register *cwd* as a tracked project in settings."""
    settings.add_project(str(cwd))
    settings.save()


def rollback(settings: "Settings") -> None:
    """Remove all dev-mem hooks from shell RC files and git config."""
    _remove_shell_hooks()
    _remove_git_hook()
    _remove_cron()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _create_dirs(settings: "Settings") -> None:
    for attr in ("db_path", "context_dir", "daily_dir"):
        p = Path(getattr(settings, attr, ""))
        if p.suffix:
            p = p.parent
        p.mkdir(parents=True, exist_ok=True)


def _run_migrations(settings: "Settings") -> None:
    from dev_mem.db import Database  # noqa: PLC0415
    db = Database(settings.db_path)
    db.migrate()
    db.close()


def _install_shell_hooks() -> None:
    """Append dev-mem hooks to ~/.zshrc and/or ~/.bashrc if not already present."""
    _inject_rc(Path.home() / ".zshrc", _zsh_hooks())
    _inject_rc(Path.home() / ".bashrc", _bash_hooks())


def _inject_rc(rc_file: Path, block: str) -> None:
    if rc_file.exists() and _HOOKS_MARKER in rc_file.read_text(encoding="utf-8"):
        return  # Already installed
    with rc_file.open("a", encoding="utf-8") as f:
        f.write("\n" + block + "\n")


def _zsh_hooks() -> str:
    return """\
# dev-mem hooks
function preexec() { _DEV_MEM_CMD="$1"; _DEV_MEM_START=$SECONDS; }
function precmd() {
  local exit_code=$?
  local duration=$(( (SECONDS - ${_DEV_MEM_START:-SECONDS}) * 1000 ))
  [ -n "$_DEV_MEM_CMD" ] && dev-mem collect terminal --cmd "$_DEV_MEM_CMD" --duration $duration --exit-code $exit_code --cwd "$PWD" &
  unset _DEV_MEM_CMD
}"""


def _bash_hooks() -> str:
    return """\
# dev-mem hooks
_dev_mem_preexec() { _DEV_MEM_CMD="$BASH_COMMAND"; _DEV_MEM_START=$SECONDS; }
trap '_dev_mem_preexec' DEBUG
PROMPT_COMMAND='_dev_mem_prompt; '$PROMPT_COMMAND
_dev_mem_prompt() {
  local exit_code=$?
  local duration=$(( (SECONDS - ${_DEV_MEM_START:-SECONDS}) * 1000 ))
  [ -n "$_DEV_MEM_CMD" ] && dev-mem collect terminal --cmd "$_DEV_MEM_CMD" --duration $duration --exit-code $exit_code --cwd "$PWD" &
  unset _DEV_MEM_CMD
}"""


def _install_git_hook() -> None:
    """Install global git post-commit hook and set core.hooksPath."""
    _GLOBAL_HOOKS_DIR.mkdir(parents=True, exist_ok=True)
    hook = _GLOBAL_HOOKS_DIR / "post-commit"
    if not hook.exists() or "dev-mem" not in hook.read_text(encoding="utf-8"):
        hook.write_text(
            "#!/usr/bin/env bash\n# dev-mem global post-commit hook\ndev-mem collect git-commit &\n",
            encoding="utf-8",
        )
        hook.chmod(0o755)
    subprocess.run(
        ["git", "config", "--global", "core.hooksPath", str(_GLOBAL_HOOKS_DIR)],
        check=False,
    )


def _install_cron() -> None:
    """Add daily analysis cron job if not already present."""
    marker = "dev-mem analyze today"
    try:
        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        existing = result.stdout if result.returncode == 0 else ""
        if marker not in existing:
            new_cron = existing.rstrip("\n") + "\n0 20 * * * dev-mem analyze today\n"
            subprocess.run(["crontab", "-"], input=new_cron, text=True, check=False)
    except FileNotFoundError:
        pass  # crontab not available


def _remove_shell_hooks() -> None:
    for rc_file in [Path.home() / ".zshrc", Path.home() / ".bashrc"]:
        if not rc_file.exists():
            continue
        text = rc_file.read_text(encoding="utf-8")
        if _HOOKS_MARKER not in text:
            continue
        # Remove from marker to end of hook block (next blank line after closing brace)
        lines = text.splitlines(keepends=True)
        out, skip = [], False
        for line in lines:
            if _HOOKS_MARKER in line:
                skip = True
            if not skip:
                out.append(line)
            elif skip and line.strip() == "" and out and out[-1].strip() == "}":
                skip = False  # end of block
        rc_file.write_text("".join(out), encoding="utf-8")


def _remove_git_hook() -> None:
    hook = _GLOBAL_HOOKS_DIR / "post-commit"
    if hook.exists() and "dev-mem" in hook.read_text(encoding="utf-8"):
        hook.unlink()
    # Only unset hooksPath if the directory is now empty
    remaining = list(_GLOBAL_HOOKS_DIR.iterdir()) if _GLOBAL_HOOKS_DIR.exists() else []
    if not remaining:
        subprocess.run(
            ["git", "config", "--global", "--unset", "core.hooksPath"],
            check=False,
        )


def _start_file_watcher() -> None:
    """Start the file watcher daemon in the background if not already running."""
    import shutil as _shutil
    import sys
    # Check if already running
    result = subprocess.run(
        ["pgrep", "-f", "dev.mem.*watch"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0 and result.stdout.strip():
        return  # Already running
    dev_mem_bin = _shutil.which("dev-mem") or sys.executable
    # Use the same Python that runs dev-mem (from pipx venv)
    python = Path(dev_mem_bin).parent / "python3"
    if not python.exists():
        python = Path(sys.executable)
    subprocess.Popen(
        [str(python), "-m", "dev_mem.collectors.files"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _remove_cron() -> None:
    marker = "dev-mem analyze today"
    try:
        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        if result.returncode != 0:
            return
        new_lines = [l for l in result.stdout.splitlines(keepends=True) if marker not in l]
        subprocess.run(["crontab", "-"], input="".join(new_lines), text=True, check=False)
    except FileNotFoundError:
        pass
