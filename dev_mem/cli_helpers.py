"""
cli_helpers.py — Helper logic for doctor and analyze commands.

Kept separate from cli.py to stay within the 500-line budget.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


# ---------------------------------------------------------------------------
# Doctor helpers
# ---------------------------------------------------------------------------

def _check_shell_hooks() -> tuple[bool, str]:
    """Return (ok, detail) for precmd/preexec detection in shell rc files."""
    home = Path.home()
    rc_files = [
        home / ".zshrc",
        home / ".bashrc",
        home / ".bash_profile",
        home / ".profile",
    ]
    marker = "dev-mem"
    for rc in rc_files:
        if rc.exists() and marker in rc.read_text(errors="ignore"):
            return True, f"Found in {rc.name}"
    return False, "Not found in ~/.zshrc / ~/.bashrc"


def _check_db(db_path: Path) -> tuple[bool, str]:
    """Return (ok, detail) for the SQLite database."""
    if not db_path.exists():
        return False, f"Database not found: {db_path}"
    try:
        import sqlite3

        with sqlite3.connect(str(db_path)) as conn:
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [r[0] for r in cur.fetchall()]
            if not tables:
                return False, "Database exists but contains no tables (run: dev-mem upgrade)"
            cur.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
            (n_tables,) = cur.fetchone()
            # Attempt row count on the events table if present
            if "events" in tables:
                cur.execute("SELECT COUNT(*) FROM events")
                (n_rows,) = cur.fetchone()
                detail = f"{n_tables} tables, {n_rows} events"
            else:
                detail = f"{n_tables} tables"
        return True, detail
    except Exception as exc:  # noqa: BLE001
        return False, f"DB error: {exc}"


def _check_git_hooks(projects: list[str]) -> tuple[bool, str]:
    """Return (ok, detail) for git hooks in registered projects."""
    if not projects:
        return True, "No projects registered"
    installed = 0
    missing = []
    for p in projects:
        hook = Path(p) / ".git" / "hooks" / "post-commit"
        if hook.exists() and "dev-mem" in hook.read_text(errors="ignore"):
            installed += 1
        else:
            missing.append(Path(p).name)
    if missing:
        return False, f"Missing in: {', '.join(missing)}"
    return True, f"Installed in {installed} project(s)"


def _check_cron() -> tuple[bool, str]:
    """Return (ok, detail) for the dev-mem cron entry."""
    try:
        result = subprocess.run(
            ["crontab", "-l"], capture_output=True, text=True, timeout=5
        )
        if "dev-mem" in result.stdout:
            return True, "Cron job present"
        return False, "No dev-mem cron entry (run: dev-mem install)"
    except FileNotFoundError:
        return False, "crontab not available on this system"
    except Exception as exc:  # noqa: BLE001
        return False, f"cron check error: {exc}"


def _check_file_watcher() -> tuple[bool, str]:
    """Return (ok, detail) for the watchdog daemon process."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "dev.mem.*watch"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            pid = result.stdout.strip().split()[0]
            return True, f"Running (pid {pid})"
        return False, "Daemon not running (start with: dev-mem install)"
    except Exception as exc:  # noqa: BLE001
        return False, f"check error: {exc}"


def _check_claude_code() -> tuple[bool, str]:
    """Return (ok, detail) for Claude Code in PATH."""
    path = shutil.which("claude")
    if path:
        return True, path
    return False, "Not found in PATH (analysis will fall back to $EDITOR)"


def run_doctor(db_path: Path, projects: list[str]) -> None:
    """Print a rich diagnostic report."""
    checks = [
        ("Shell hooks (zsh/bash precmd)", _check_shell_hooks()),
        ("Database health", _check_db(db_path)),
        ("Git hooks (per project)", _check_git_hooks(projects)),
        ("Cron job", _check_cron()),
        ("File watcher daemon", _check_file_watcher()),
        ("Claude Code in PATH", _check_claude_code()),
    ]

    table = Table(title="dev-mem Doctor", show_header=True, header_style="bold cyan")
    table.add_column("Check", style="bold")
    table.add_column("Status", justify="center")
    table.add_column("Detail")

    all_ok = True
    for label, (ok, detail) in checks:
        status = "[green]OK[/green]" if ok else "[red]FAIL[/red]"
        if not ok:
            all_ok = False
        table.add_row(label, status, detail)

    console.print(table)
    if all_ok:
        console.print(Panel("[green]All checks passed.[/green]", expand=False))
    else:
        console.print(
            Panel(
                "[yellow]Some checks failed. Run [bold]dev-mem install[/bold] to fix most issues.[/yellow]",
                expand=False,
            )
        )


# ---------------------------------------------------------------------------
# Analyze helpers
# ---------------------------------------------------------------------------

ANALYZE_PROMPTS: dict[str, str] = {
    "today": (
        "You are a senior software engineer reviewing a developer's activity log.\n"
        "Summarize what was accomplished today, identify patterns, flag recurring errors,\n"
        "and suggest one concrete improvement for tomorrow.\n\n"
        "CONTEXT:\n{context}"
    ),
    "prompts": (
        "Analyze the following AI prompts used by the developer.\n"
        "Identify which were most effective, which could be improved, and suggest\n"
        "3 reusable prompt templates based on the patterns you see.\n\n"
        "CONTEXT:\n{context}"
    ),
    "project": (
        "Perform a deep analysis of this project's recent activity.\n"
        "Cover: velocity, error hotspots, architectural patterns, and tech debt signals.\n\n"
        "CONTEXT:\n{context}"
    ),
    "errors": (
        "Analyze the error log below. Group errors by root cause, identify the top 3\n"
        "recurring issues, and propose a fix or mitigation for each.\n\n"
        "CONTEXT:\n{context}"
    ),
    "week": (
        "Generate a weekly productivity report based on this developer's activity.\n"
        "Include: work distribution, focus time vs context-switching, key deliverables,\n"
        "and one actionable suggestion for next week.\n\n"
        "CONTEXT:\n{context}"
    ),
    "learning": (
        "Extract learnings from this developer's notes and error patterns.\n"
        "Synthesize into: concepts mastered, knowledge gaps, and a personalised\n"
        "learning plan for the next two weeks.\n\n"
        "CONTEXT:\n{context}"
    ),
}


def build_context(analysis_type: str, db_path: Path, project: Optional[str]) -> str:
    """Build a plain-text context block from the database for the given analysis type."""
    lines: list[str] = [
        f"Analysis type: {analysis_type}",
        f"Date: {date.today().isoformat()}",
        f"Active project: {project or 'unknown'}",
        "",
    ]

    try:
        import sqlite3

        with sqlite3.connect(str(db_path)) as conn:
            cur = conn.cursor()

            if analysis_type in ("today", "project", "errors"):
                cur.execute(
                    "SELECT timestamp, event_type, summary FROM events "
                    "WHERE DATE(timestamp) = DATE('now') "
                    "ORDER BY timestamp DESC LIMIT 200"
                )
                rows = cur.fetchall()
                lines.append(f"Events today ({len(rows)}):")
                for ts, etype, summary in rows:
                    lines.append(f"  [{ts}] {etype}: {summary}")

            elif analysis_type == "week":
                cur.execute(
                    "SELECT DATE(timestamp) as day, event_type, COUNT(*) "
                    "FROM events WHERE timestamp >= DATE('now', '-7 days') "
                    "GROUP BY day, event_type ORDER BY day DESC"
                )
                rows = cur.fetchall()
                lines.append("Events last 7 days (by day + type):")
                for day, etype, cnt in rows:
                    lines.append(f"  {day}  {etype}: {cnt}")

            elif analysis_type == "prompts":
                cur.execute(
                    "SELECT timestamp, prompt_text FROM claude_sessions "
                    "ORDER BY timestamp DESC LIMIT 100"
                )
                rows = cur.fetchall()
                lines.append(f"Recent Claude prompts ({len(rows)}):")
                for ts, prompt in rows:
                    lines.append(f"  [{ts}] {prompt[:200]}")

            elif analysis_type == "learning":
                cur.execute(
                    "SELECT created_at, content FROM notes ORDER BY created_at DESC LIMIT 50"
                )
                notes = cur.fetchall()
                lines.append(f"Notes ({len(notes)}):")
                for ts, content in notes:
                    lines.append(f"  [{ts}] {content[:300]}")

                cur.execute(
                    "SELECT timestamp, summary FROM events WHERE event_type = 'error' "
                    "ORDER BY timestamp DESC LIMIT 50"
                )
                errors = cur.fetchall()
                lines.append(f"\nRecent errors ({len(errors)}):")
                for ts, summary in errors:
                    lines.append(f"  [{ts}] {summary[:200]}")

    except Exception as exc:  # noqa: BLE001
        lines.append(f"[warning: could not read database — {exc}]")

    return "\n".join(lines)


def launch_analysis(analysis_type: str, context: str, context_dir: Path) -> None:
    """Write context to a temp file then open it in Claude Code or $EDITOR."""
    context_dir.mkdir(parents=True, exist_ok=True)

    prompt_template = ANALYZE_PROMPTS.get(analysis_type, "Analyze the following context:\n\n{context}")
    full_prompt = prompt_template.format(context=context)

    filename = context_dir / f"{date.today().isoformat()}-{analysis_type}.context.md"
    filename.write_text(full_prompt, encoding="utf-8")

    claude_bin = shutil.which("claude")
    if claude_bin:
        console.print(f"Launching Claude Code with context file: {filename}")
        os.execv(claude_bin, [claude_bin, "--file", str(filename)])
    else:
        editor = os.environ.get("EDITOR", "vi")
        console.print(
            f"Claude Code not found. Opening in [bold]{editor}[/bold]: {filename}"
        )
        subprocess.run([editor, str(filename)])
