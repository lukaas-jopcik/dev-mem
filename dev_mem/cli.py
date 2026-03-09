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


def _settings():
    from dev_mem.settings import Settings  # noqa: PLC0415
    return Settings


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
        settings = _settings().load()
        db = _db()(settings.db_path)
        db.migrate()

        from dev_mem.install import run_install  # noqa: PLC0415
        run_install(settings)
        console.print("\n[green]Installation complete.[/green] Restart your shell to activate hooks.")
    except ImportError:
        console.print("\n[yellow]Install module not yet implemented — run migrations manually:[/yellow]")
        console.print("  dev-mem upgrade")


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------

@main.command()
def init() -> None:
    """Initialize dev-mem tracking in the current git repository."""
    cwd = Path.cwd()
    git_dir = cwd / ".git"
    if not git_dir.is_dir():
        console.print(f"[red]Error:[/red] {cwd} is not a git repository root.")
        sys.exit(1)

    try:
        settings = _settings().load()
        from dev_mem.install import init_project  # noqa: PLC0415
        init_project(cwd, settings)
        console.print(f"[green]Initialized dev-mem in[/green] {cwd}")
        console.print("Run [bold]dev-mem doctor[/bold] to verify the setup.")
    except ImportError:
        # Fallback: just create the hook stub
        hook_path = git_dir / "hooks" / "post-commit"
        if not hook_path.exists():
            hook_path.write_text(
                "#!/bin/sh\ndev-mem _collect git-commit \"$PWD\"\n", encoding="utf-8"
            )
            hook_path.chmod(0o755)
            console.print(f"[green]Created git hook:[/green] {hook_path}")
        else:
            console.print(f"[yellow]Hook already exists:[/yellow] {hook_path}")


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

@main.command()
def status() -> None:
    """Show today's activity summary."""
    try:
        settings = _settings().load()
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
        ("Git commits", stats.get("commits", 0)),
        ("Claude sessions", stats.get("claude_sessions", 0)),
        ("Errors logged", stats.get("errors", 0)),
    ]
    for label, value in rows:
        table.add_row(label, str(value))

    console.print(table)
    active = stats.get("active_project") or settings.active_project if "settings" in dir() else "unknown"
    console.print(f"\nActive project: [bold]{active or 'none'}[/bold]")


# ---------------------------------------------------------------------------
# daily
# ---------------------------------------------------------------------------

@main.command()
def daily() -> None:
    """Print a formatted summary of today's work."""
    try:
        settings = _settings().load()
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
        settings = _settings().load()
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
        settings = _settings().load()
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
        settings = _settings().load()
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
        settings = _settings().load()
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
        settings = _settings().load()
        settings.add_project(str(project_path))
        settings.save()
        console.print(f"[green]Project added:[/green] {project_path}")
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Failed to add project:[/red] {exc}")
        sys.exit(1)


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
        app.run(host=host, port=port, debug=False)
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
        settings = _settings().load()
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
        settings = _settings().load()
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
        settings = _settings().load()
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
        settings = _settings().load()
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
        settings = _settings().load()
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
        settings = _settings().load()
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
        settings = _settings().load()
        threshold = days or settings.archive_after_days or 90
        db = _db()(settings.db_path)
        count = db.archive(older_than_days=threshold)
        console.print(f"[green]Archived {count} entries[/green] older than {threshold} days.")
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Archive failed:[/red] {exc}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Internal collect hook (called from shell/git hooks)
# ---------------------------------------------------------------------------

@main.command("_collect", hidden=True)
@click.argument("event_type")
@click.argument("payload", required=False, default="")
def _collect(event_type: str, payload: str) -> None:
    """Internal: record an event from a shell or git hook (not for end users)."""
    try:
        settings = _settings().load()
        db = _db()(settings.db_path)
        db.record_event(event_type=event_type, payload=payload,
                        project=settings.active_project)
    except Exception:  # noqa: BLE001
        pass  # Silent — hooks must never interrupt the developer's workflow
