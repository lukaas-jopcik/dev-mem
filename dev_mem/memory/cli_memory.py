"""
dev_mem.memory.cli_memory — CLI commands for the memory subsystem.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


# ---------------------------------------------------------------------------
# Click group
# ---------------------------------------------------------------------------

@click.group("memory")
def memory_group() -> None:
    """Observation memory commands (search, list, save, context)."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _open_conn(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        console.print(f"[red]Database not found:[/red] {db_path}")
        console.print("Run [bold]dev-mem upgrade[/bold] to create the database.")
        sys.exit(1)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _type_color(obs_type: str) -> str:
    colors = {
        "bugfix": "red",
        "feature": "green",
        "refactor": "blue",
        "discovery": "cyan",
        "decision": "magenta",
        "change": "yellow",
    }
    return colors.get(obs_type, "white")


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------

@memory_group.command("search")
@click.argument("query")
@click.option("--limit", "-n", default=20, show_default=True, help="Max results.")
@click.option("--project", "-p", default=None, help="Filter by project name.")
@click.option("--type", "obs_type", default=None,
              help="Filter by type (bugfix|feature|refactor|discovery|decision|change).")
def cmd_memory_search(query: str, limit: int, project: Optional[str], obs_type: Optional[str]) -> None:
    """Full-text search across observations."""
    from dev_mem.memory.observations import search_observations
    from dev_mem.settings import Settings

    settings = Settings()
    conn = _open_conn(settings.db_path)
    try:
        results = search_observations(conn, query, limit=limit, project=project, obs_type=obs_type)
    finally:
        conn.close()

    if not results:
        console.print(f"[yellow]No observations found for:[/yellow] {query}")
        return

    table = Table(title=f"Search: '{query}'", header_style="bold cyan", show_lines=True)
    table.add_column("ID", style="dim", width=6)
    table.add_column("Type", width=10)
    table.add_column("Title")
    table.add_column("Project", width=15)
    table.add_column("Date", width=12)

    for obs in results:
        color = _type_color(obs["type"])
        table.add_row(
            str(obs["id"]),
            f"[{color}]{obs['type']}[/{color}]",
            obs["title"][:60],
            obs.get("project", "") or "",
            (obs.get("created_at") or "")[:10],
        )

    console.print(table)


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------

@memory_group.command("list")
@click.option("--limit", "-n", default=20, show_default=True, help="Max results.")
@click.option("--project", "-p", default=None, help="Filter by project name.")
@click.option("--type", "obs_type", default=None, help="Filter by type.")
def cmd_memory_list(limit: int, project: Optional[str], obs_type: Optional[str]) -> None:
    """List recent observations."""
    from dev_mem.memory.observations import list_observations
    from dev_mem.settings import Settings

    settings = Settings()
    conn = _open_conn(settings.db_path)
    try:
        results = list_observations(conn, limit=limit, project=project, obs_type=obs_type)
    finally:
        conn.close()

    if not results:
        console.print("[yellow]No observations recorded yet.[/yellow]")
        return

    table = Table(title="Recent Observations", header_style="bold cyan", show_lines=True)
    table.add_column("ID", style="dim", width=6)
    table.add_column("Type", width=10)
    table.add_column("Title")
    table.add_column("Project", width=15)
    table.add_column("Date", width=12)

    for obs in results:
        color = _type_color(obs["type"])
        table.add_row(
            str(obs["id"]),
            f"[{color}]{obs['type']}[/{color}]",
            obs["title"][:60],
            obs.get("project", "") or "",
            (obs.get("created_at") or "")[:10],
        )

    console.print(table)


# ---------------------------------------------------------------------------
# save
# ---------------------------------------------------------------------------

@memory_group.command("save")
@click.argument("text")
@click.option("--title", "-t", default=None, help="Short title for this observation.")
@click.option("--project", "-p", default=None, help="Project name to tag.")
@click.option(
    "--type", "obs_type", default="discovery",
    type=click.Choice(["bugfix", "feature", "refactor", "discovery", "decision", "change"]),
    show_default=True,
    help="Observation type.",
)
def cmd_memory_save(text: str, title: Optional[str], project: Optional[str], obs_type: str) -> None:
    """Save a manual observation/memory."""
    from dev_mem.memory.observations import insert_observation
    from dev_mem.settings import Settings

    settings = Settings()
    conn = _open_conn(settings.db_path)

    effective_project = project or settings.active_project or ""
    effective_title = title or text[:60]

    # Resolve project_id
    project_id: Optional[int] = None
    if effective_project:
        row = conn.execute(
            "SELECT id FROM projects WHERE name = ? AND active = 1",
            (effective_project,),
        ).fetchone()
        if row:
            project_id = row["id"]

    try:
        obs_id = insert_observation(
            conn,
            title=effective_title,
            obs_type=obs_type,
            narrative=text,
            text=text,
            project=effective_project,
            project_id=project_id,
        )
    finally:
        conn.close()

    console.print(
        Panel(
            f"[green]Observation saved[/green] (id={obs_id})\n"
            f"[bold]{effective_title}[/bold]\n"
            f"Type: [cyan]{obs_type}[/cyan]  Project: [yellow]{effective_project or 'none'}[/yellow]",
            expand=False,
        )
    )


# ---------------------------------------------------------------------------
# context
# ---------------------------------------------------------------------------

@memory_group.command("context")
@click.option("--project", "-p", default=None, help="Project name (defaults to active).")
def cmd_memory_context(project: Optional[str]) -> None:
    """Print the context block that would be injected into a new session."""
    from dev_mem.memory.context_injector import build_context_block
    from dev_mem.settings import Settings

    settings = Settings()
    conn = _open_conn(settings.db_path)

    effective_project = project or settings.active_project or ""
    project_id: Optional[int] = None
    if effective_project:
        row = conn.execute(
            "SELECT id FROM projects WHERE name = ? AND active = 1",
            (effective_project,),
        ).fetchone()
        if row:
            project_id = row["id"]

    try:
        block = build_context_block(
            conn,
            effective_project,
            project_id,
            max_observations=settings.get("context_inject_max_observations", 10),
            max_chars=settings.get("context_inject_max_chars", 8000),
        )
    finally:
        conn.close()

    if block:
        console.print(Panel(block, title="Context Block", expand=False))
    else:
        console.print("[yellow]No context available yet. Save some observations first.[/yellow]")
