"""cli.py — Click entry point for dev-mem."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


def _db():
    from dev_mem.db import Database  # noqa: PLC0415
    return Database


def _settings() -> "Settings":
    from dev_mem.settings import Settings  # noqa: PLC0415
    return Settings()


# ---------------------------------------------------------------------------
# Root group
# ---------------------------------------------------------------------------

@click.group()
@click.version_option(package_name="dev-mem")
def main() -> None:
    """dev-mem — local developer memory system."""


# ---------------------------------------------------------------------------
# install
# ---------------------------------------------------------------------------

@main.command()
def install() -> None:
    """First-time global setup: shell hooks, cron job, directory structure."""
    console.print(Panel("[bold cyan]dev-mem install[/bold cyan]", expand=False))

    steps = [
        "Creating data directories",
        "Installing shell hooks (zsh / bash)",
        "Registering daily cron job",
        "Running database migrations",
        "Starting file watcher daemon",
    ]
    for step in steps:
        console.print(f"  [cyan]...[/cyan] {step}")

    try:
        settings = _settings()
        db = _db()(settings.db_path)
        db.migrate()

        from dev_mem.install import run_install  # noqa: PLC0415
        run_install(settings)
        console.print("\n[green]Installation complete.[/green] Restart your shell to activate hooks.")
    except ImportError:
        console.print("\n[yellow]Install module not yet implemented — run migrations manually:[/yellow]")
        console.print("  dev-mem upgrade")


# ---------------------------------------------------------------------------
# install-claude
# ---------------------------------------------------------------------------

@main.command("install-claude")
def install_claude() -> None:
    """Configure Claude Code hooks in ~/.claude/settings.json."""
    import json
    import os

    settings_path = Path.home() / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)

    # Load existing settings
    existing: dict = {}
    if settings_path.exists():
        try:
            existing = json.loads(settings_path.read_text())
        except Exception:
            existing = {}

    hooks = existing.setdefault("hooks", {})

    def _ensure_hook(event: str, command: str) -> None:
        entries = hooks.setdefault(event, [])
        for entry in entries:
            for h in entry.get("hooks", []):
                if h.get("command") == command:
                    return  # already present
        entries.append({"hooks": [{"type": "command", "command": command}]})

    def _ensure_posttooluse_hook(command: str) -> None:
        entries = hooks.setdefault("PostToolUse", [])
        for entry in entries:
            if entry.get("matcher") == ".*":
                for h in entry.get("hooks", []):
                    if h.get("command") == command:
                        return
        entries.append({"matcher": ".*", "hooks": [{"type": "command", "command": command}]})

    _ensure_hook("SessionStart", "dev-mem collect session-start")
    _ensure_hook("UserPromptSubmit", "dev-mem collect user-prompt")
    _ensure_hook("Stop", "dev-mem collect session-stop")
    _ensure_hook("PreCompact", "dev-mem collect compact")
    _ensure_posttooluse_hook("dev-mem collect claude-tool")

    # Add MCP server
    mcp_servers = existing.setdefault("mcpServers", {})
    if "dev-mem" not in mcp_servers:
        mcp_servers["dev-mem"] = {"type": "stdio", "command": "dev-mem", "args": ["mcp-server"]}

    settings_path.write_text(json.dumps(existing, indent=2))
    console.print(f"[green]Claude Code hooks configured[/green] in {settings_path}")
    console.print("Restart Claude Code to activate session memory.")


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------

@main.command()
def init() -> None:
    """Register current git repository as a tracked project.

    Note: commit tracking is automatic via the global git hook set up by
    'dev-mem install' — no per-repo setup is required for that.
    This command only registers the project name/path in dev-mem settings.
    """
    cwd = Path.cwd()
    git_dir = cwd / ".git"
    if not git_dir.is_dir():
        console.print(f"[red]Error:[/red] {cwd} is not a git repository root.")
        sys.exit(1)

    try:
        settings = _settings()
        from dev_mem.install import init_project  # noqa: PLC0415
        init_project(cwd, settings)
        console.print(f"[green]Initialized dev-mem in[/green] {cwd}")
        console.print("Run [bold]dev-mem doctor[/bold] to verify the setup.")
    except ImportError:
        settings = _settings()
        settings.add_project(str(cwd))
        settings.save()
        console.print(f"[green]Project registered:[/green] {cwd}")
        console.print("[dim]Commit tracking is automatic via global git hook.[/dim]")


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

@main.command()
def status() -> None:
    """Show today's activity summary."""
    try:
        settings = _settings()
        db = _db()(settings.db_path)
        stats = db.today_stats()
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Could not load stats:[/red] {exc}")
        stats = {}

    table = Table(title="Today's Activity", show_header=True, header_style="bold cyan")
    table.add_column("Metric", style="bold")
    table.add_column("Count", justify="right")

    rows = [
        ("Commands logged", stats.get("commands", 0)),
        ("Git commits", stats.get("git_events", 0)),
        ("Claude sessions", stats.get("claude_sessions", 0)),
        ("Errors logged", stats.get("errors", 0)),
    ]
    for label, value in rows:
        table.add_row(label, str(value))

    console.print(table)
    active = stats.get("active_project") or settings.active_project if "settings" in locals() else "unknown"
    console.print(f"\nActive project: [bold]{active or 'none'}[/bold]")


# ---------------------------------------------------------------------------
# daily
# ---------------------------------------------------------------------------

@main.command()
def daily() -> None:
    """Print a formatted summary of today's work."""
    try:
        settings = _settings()
        db = _db()(settings.db_path)
        summary = db.daily_summary()
        console.print(Panel(summary, title="Daily Summary", expand=False))
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Could not generate daily summary:[/red] {exc}")


# ---------------------------------------------------------------------------
# note
# ---------------------------------------------------------------------------

@main.command()
@click.argument("text")
def note(text: str) -> None:
    """Save a manual learning note tied to the active project."""
    try:
        settings = _settings()
        db = _db()(settings.db_path)
        note_id = db.save_note(text, project=settings.active_project)
        console.print(f"[green]Note saved[/green] (id={note_id}): {text[:80]}")
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Failed to save note:[/red] {exc}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# decide
# ---------------------------------------------------------------------------

@main.command()
@click.argument("title")
@click.option("--context", "-c", default="", help="Context / background for this decision.")
@click.option("--decision", "-d", default="", help="What was decided.")
def decide(title: str, context: str, decision: str) -> None:
    """Log an architectural decision record (ADR)."""
    try:
        settings = _settings()
        db = _db()(settings.db_path)
        adr_id = db.save_decision(title=title, context=context, decision=decision,
                                  project=settings.active_project)
        console.print(f"[green]Decision logged[/green] (id={adr_id}): {title}")
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Failed to log decision:[/red] {exc}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# project sub-group
# ---------------------------------------------------------------------------

@main.group()
def project() -> None:
    """Project management commands."""


@project.command(name="list")
def project_list() -> None:
    """List all registered projects."""
    try:
        settings = _settings()
        projects = settings.projects
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Could not load settings:[/red] {exc}")
        return

    if not projects:
        console.print("No projects registered. Run [bold]dev-mem init[/bold] in a project directory.")
        return

    table = Table(title="Registered Projects", header_style="bold cyan")
    table.add_column("Name", style="bold")
    table.add_column("Path")
    table.add_column("Active", justify="center")

    for p in projects:
        name = p.get("name", Path(p.get("path", "")).name)
        path = p.get("path", "")
        is_active = "[green]*[/green]" if name == settings.active_project else ""
        table.add_row(name, path, is_active)

    console.print(table)


@project.command()
@click.argument("name")
def switch(name: str) -> None:
    """Override the active project by name."""
    try:
        settings = _settings()
        settings.set_active_project(name)
        settings.save()
        console.print(f"Active project set to [bold]{name}[/bold].")
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Failed to switch project:[/red] {exc}")
        sys.exit(1)


@project.command()
@click.argument("path", type=click.Path(exists=True, file_okay=False))
def add(path: str) -> None:
    """Register a directory as a tracked project."""
    project_path = Path(path).resolve()
    try:
        settings = _settings()
        db = _db()(settings.db_path)
        is_git = 1 if (project_path / ".git").is_dir() else 0
        db.upsert_project(project_path.name, str(project_path))
        db._conn.execute(
            "UPDATE projects SET is_git=? WHERE path=?", (is_git, str(project_path))
        )
        db._conn.commit()
        db.close()
        console.print(f"[green]Project added:[/green] {project_path} ({'git' if is_git else 'local'})")
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Failed to add project:[/red] {exc}")
        sys.exit(1)


@project.command()
@click.argument("path", type=click.Path(exists=True, file_okay=False))
@click.option("--depth", default=1, show_default=True, help="How many levels deep to scan.")
def scan(path: str, depth: int) -> None:
    """Scan a directory and register all subdirectories as projects."""
    import os
    root = Path(path).resolve()
    settings = _settings()
    db = _db()(settings.db_path)

    added = 0
    skipped = 0

    def _scan(directory: Path, current_depth: int) -> None:
        nonlocal added, skipped
        if current_depth > depth:
            return
        try:
            entries = [e for e in directory.iterdir() if e.is_dir() and not e.name.startswith('.')]
        except PermissionError:
            return
        for entry in sorted(entries):
            is_git = 1 if (entry / ".git").is_dir() else 0
            existing = db._conn.execute(
                "SELECT id FROM projects WHERE path=?", (str(entry),)
            ).fetchone()
            if existing:
                skipped += 1
            else:
                db.upsert_project(entry.name, str(entry))
                db._conn.execute(
                    "UPDATE projects SET is_git=? WHERE path=?", (is_git, str(entry))
                )
                db._conn.commit()
                label = "[cyan]git[/cyan]" if is_git else "[dim]local[/dim]"
                console.print(f"  {label}  {entry.name}")
                added += 1
            if current_depth < depth:
                _scan(entry, current_depth + 1)

    console.print(f"Scanning [bold]{root}[/bold]…")
    _scan(root, 1)
    db.close()
    console.print(f"\n[green]Done.[/green] Added {added}, skipped {skipped} existing.")


@project.command("sync-memory")
def sync_memory() -> None:
    """Link observations to projects by matching project name, and backfill activity stats."""
    settings = _settings()
    db = _db()(settings.db_path)
    conn = db._conn

    # 1. Get all projects indexed by name (lowercase)
    projects = {
        row["name"].lower(): row
        for row in conn.execute("SELECT * FROM projects WHERE active=1").fetchall()
    }

    # 2. Get all distinct project names from observations
    obs_projects = [
        row[0] for row in conn.execute(
            "SELECT DISTINCT project FROM observations WHERE project <> '' AND project_id IS NULL"
        ).fetchall()
    ]

    linked = 0
    created = 0
    unmatched = []

    for obs_project in obs_projects:
        match = projects.get(obs_project.lower())
        if match:
            pid = match["id"]
        else:
            # Try partial match (e.g. "imaketoday-video" → imaketoday-video folder)
            partial = next(
                (p for name, p in projects.items() if obs_project.lower() in name or name in obs_project.lower()),
                None,
            )
            if partial:
                pid = partial["id"]
                match = partial
            else:
                unmatched.append(obs_project)
                continue

        count = conn.execute(
            "UPDATE observations SET project_id=? WHERE project=? AND project_id IS NULL",
            (pid, obs_project),
        ).rowcount
        conn.commit()
        linked += count
        console.print(f"  [green]linked[/green] {count:>5} obs  →  [bold]{match['name']}[/bold]")

    # 3. Backfill last_accessed on projects from observations timestamps
    conn.execute("""
        UPDATE projects SET last_accessed = (
            SELECT MAX(created_at) FROM observations WHERE observations.project_id = projects.id
        )
        WHERE last_accessed IS NULL
    """)
    conn.commit()
    db.close()

    console.print(f"\n[green]Done.[/green] Linked {linked} observations across {len(obs_projects) - len(unmatched)} projects.")
    if unmatched:
        console.print(f"[yellow]Unmatched project names:[/yellow] {', '.join(unmatched)}")
        console.print("  Run [bold]dev-mem project scan <path>[/bold] to register missing directories.")


@project.command("auto-register", hidden=True)
@click.argument("cwd")
def auto_register(cwd: str) -> None:
    """Auto-register current directory when cd-ing into it (called from shell hook)."""
    p = Path(cwd).resolve()
    if not p.is_dir():
        return
    try:
        settings = _settings()
        db = _db()(settings.db_path)
        existing = db._conn.execute(
            "SELECT id FROM projects WHERE path=?", (str(p),)
        ).fetchone()
        if not existing:
            is_git = 1 if (p / ".git").is_dir() else 0
            db.upsert_project(p.name, str(p))
            db._conn.execute(
                "UPDATE projects SET is_git=? WHERE path=?", (is_git, str(p))
            )
        db._conn.execute(
            "UPDATE projects SET last_accessed=datetime('now') WHERE path=?", (str(p),)
        )
        db._conn.commit()
        db.close()
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# web
# ---------------------------------------------------------------------------

@main.command()
@click.option("--port", default=8888, show_default=True, help="Port to listen on.")
@click.option("--host", default="127.0.0.1", show_default=True, help="Host to bind.")
def web(port: int, host: str) -> None:
    """Start the local web dashboard."""
    console.print(
        f"Starting dashboard at [link=http://{host}:{port}]http://{host}:{port}[/link]"
    )
    try:
        from dev_mem.web.app import create_app  # noqa: PLC0415
        app = create_app()
        app.run(host=host, port=port, debug=False, threaded=True)
    except ImportError as exc:
        console.print(f"[red]Web module not available:[/red] {exc}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# analyze sub-group
# ---------------------------------------------------------------------------

@main.group()
def analyze() -> None:
    """AI-powered analysis commands (builds context then opens Claude Code or $EDITOR)."""


def _run_analysis(analysis_type: str) -> None:
    from dev_mem.cli_helpers import build_context, launch_analysis  # noqa: PLC0415

    try:
        settings = _settings()
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Could not load settings:[/red] {exc}")
        sys.exit(1)

    db_path = Path(settings.db_path)
    context_dir = Path(settings.context_dir)
    project = settings.active_project

    console.print(f"Building context for [bold]{analysis_type}[/bold] analysis...")
    context = build_context(analysis_type, db_path, project)
    launch_analysis(analysis_type, context, context_dir)


@analyze.command()
def today() -> None:
    """Analyze today's work."""
    _run_analysis("today")


@analyze.command()
def prompts() -> None:
    """Analyze your most effective AI prompts."""
    _run_analysis("prompts")


@analyze.command()
def project_analysis() -> None:  # registered as "project" below
    """Deep-dive analysis of the active project."""
    _run_analysis("project")


# Register as "project" without conflicting with the project sub-group
analyze.add_command(project_analysis, name="project")


@analyze.command()
def errors() -> None:
    """Summarize recurring error patterns."""
    _run_analysis("errors")


@analyze.command()
def week() -> None:
    """Weekly productivity and pattern report."""
    _run_analysis("week")


@analyze.command()
def learning() -> None:
    """Synthesize learnings and knowledge gaps."""
    _run_analysis("learning")


@analyze.command()
def save() -> None:
    """Save the last generated analysis context file to the daily directory."""
    try:
        settings = _settings()
        context_dir = Path(settings.context_dir)
        daily_dir = Path(settings.daily_dir)
        daily_dir.mkdir(parents=True, exist_ok=True)

        files = sorted(context_dir.glob("*.context.md"), key=lambda f: f.stat().st_mtime, reverse=True)
        if not files:
            console.print("[yellow]No context files found to save.[/yellow]")
            return

        latest = files[0]
        dest = daily_dir / latest.name
        dest.write_text(latest.read_text(encoding="utf-8"), encoding="utf-8")
        console.print(f"[green]Saved:[/green] {dest}")
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Save failed:[/red] {exc}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------

@main.command()
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["json", "markdown", "csv"], case_sensitive=False),
    default="json",
    show_default=True,
    help="Output format.",
)
@click.option("--output", "-o", default=None, help="Output file path (stdout if omitted).")
def export(fmt: str, output: Optional[str]) -> None:
    """Export collected data to JSON, Markdown, or CSV."""
    try:
        settings = _settings()
        db = _db()(settings.db_path)
        data = db.export(fmt)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Export failed:[/red] {exc}")
        sys.exit(1)

    if output:
        Path(output).write_text(data, encoding="utf-8")
        console.print(f"[green]Exported to[/green] {output}")
    else:
        click.echo(data)


# ---------------------------------------------------------------------------
# upgrade
# ---------------------------------------------------------------------------

@main.command()
def upgrade() -> None:
    """Run database migrations after updating dev-mem."""
    try:
        settings = _settings()
        db = _db()(settings.db_path)
        version = db.migrate()
        console.print(f"[green]Database migrated.[/green] Schema version: {version}")
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Migration failed:[/red] {exc}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------

@main.command()
def doctor() -> None:
    """Diagnose system health: hooks, DB, cron, daemon, Claude Code."""
    from dev_mem.cli_helpers import run_doctor  # noqa: PLC0415

    try:
        settings = _settings()
        db_path = Path(settings.db_path)
        projects = [p.get("path", "") for p in (settings.projects or [])]
    except Exception:  # noqa: BLE001
        db_path = Path.home() / ".local" / "share" / "dev-mem" / "mem.db"
        projects = []

    run_doctor(db_path, projects)


# ---------------------------------------------------------------------------
# rollback-hooks
# ---------------------------------------------------------------------------

@main.command("rollback-hooks")
@click.confirmation_option(prompt="This will remove all dev-mem shell and git hooks. Continue?")
def rollback_hooks() -> None:
    """Emergency removal of all installed shell and git hooks."""
    try:
        settings = _settings()
        from dev_mem.install import rollback  # noqa: PLC0415
        rollback(settings)
        console.print("[green]All dev-mem hooks removed.[/green]")
    except ImportError:
        console.print(
            "[yellow]Install module not available. Manually remove the dev-mem block from "
            "~/.zshrc / ~/.bashrc and delete .git/hooks/post-commit in each project.[/yellow]"
        )


# ---------------------------------------------------------------------------
# archive
# ---------------------------------------------------------------------------

@main.command()
@click.option(
    "--days",
    default=None,
    type=int,
    help="Archive entries older than N days (overrides settings).",
)
def archive(days: Optional[int]) -> None:
    """Manually trigger data archiving for old entries."""
    try:
        settings = _settings()
        threshold = days or settings.archive_after_days or 90
        db = _db()(settings.db_path)
        count = db.archive(older_than_days=threshold)
        console.print(f"[green]Archived {count} entries[/green] older than {threshold} days.")
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Archive failed:[/red] {exc}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# memory sub-group (observations / claude-mem 2-in-1)
# ---------------------------------------------------------------------------

from dev_mem.memory.cli_memory import memory_group  # noqa: E402
main.add_command(memory_group)


# ---------------------------------------------------------------------------
# mcp-server
# ---------------------------------------------------------------------------

@main.command("mcp-server")
def mcp_server() -> None:
    """Start the MCP server (stdio JSON-RPC 2.0 mode)."""
    from dev_mem.mcp.server import run_server  # noqa: PLC0415
    run_server()


# ---------------------------------------------------------------------------
# Internal collect hook (called from shell/git hooks)
# ---------------------------------------------------------------------------

@main.command("_collect", hidden=True)
@click.argument("event_type")
@click.argument("payload", required=False, default="")
def _collect(event_type: str, payload: str) -> None:
    """Internal: record an event from a shell or git hook (not for end users)."""
    try:
        settings = _settings()
        db = _db()(settings.db_path)
        db.record_event(event_type=event_type, payload=payload,
                        project=settings.active_project)
    except Exception:  # noqa: BLE001
        pass  # Silent — hooks must never interrupt the developer's workflow


# ---------------------------------------------------------------------------
# collect sub-group (called from shell/git hooks via dev-mem binary)
# ---------------------------------------------------------------------------

@main.group(hidden=True)
def collect() -> None:
    """Internal: collect events from shell/git hooks."""


@collect.command()
@click.option("--cmd", required=True)
@click.option("--duration", type=int, default=0)
@click.option("--exit-code", "exit_code", type=int, default=0)
@click.option("--cwd", default=None)
def terminal(cmd: str, duration: int, exit_code: int, cwd: Optional[str]) -> None:
    """Record a shell command (called from preexec/precmd hooks)."""
    from dev_mem.collectors.terminal import main as _run  # noqa: PLC0415
    args = ["--cmd", cmd, "--duration", str(duration), "--exit-code", str(exit_code)]
    if cwd:
        args += ["--cwd", cwd]
    _run(args)


@collect.command("git-commit")
def collect_git() -> None:
    """Record the latest git commit (called from post-commit hook)."""
    from dev_mem.collectors.git import main as _run  # noqa: PLC0415
    _run()


@collect.command("session-start")
def collect_session_start() -> None:
    """SessionStart hook — injects memory context into Claude session."""
    from dev_mem.collectors.session_start import main as _run  # noqa: PLC0415
    _run()


@collect.command("user-prompt")
def collect_user_prompt() -> None:
    """UserPromptSubmit hook — injects mini context on every message + compact signal."""
    from dev_mem.collectors.user_prompt import main as _run  # noqa: PLC0415
    _run()


@collect.command("session-stop")
def collect_session_stop() -> None:
    """Stop hook — records end of Claude session."""
    from dev_mem.collectors.session_stop import main as _run  # noqa: PLC0415
    _run()


@collect.command("claude-tool")
def collect_claude_tool() -> None:
    """PostToolUse hook — records Claude tool calls and extracts observations."""
    from dev_mem.collectors.claude_code import main as _run  # noqa: PLC0415
    _run()


@collect.command("compact")
def collect_compact() -> None:
    """PreCompact hook — saves session state before context window compression."""
    from dev_mem.collectors.compact import main as _run  # noqa: PLC0415
    _run()
