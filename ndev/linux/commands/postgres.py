"""
Linux CLI commands for managing PostgreSQL module.
"""
from __future__ import annotations

import typer
from rich.console import Console
from ndev.common.logger import logger
from ndev.common.modules import get_module_manager

console = Console()
postgres_app = typer.Typer(
    help="Manage PostgreSQL database server module.",
    no_args_is_help=True
)


@postgres_app.command("install")
def postgres_install_cmd():
    """Install PostgreSQL binaries / packages."""
    mod = get_module_manager().get_module("postgres")
    if not mod:
        logger.error("PostgreSQL module not found.")
        raise typer.Exit(code=1)
    console.print("[bold blue]Installing PostgreSQL...[/bold blue]")
    mod.install()
    console.print("[bold green]✓ PostgreSQL installed and initialized successfully.[/bold green]")


@postgres_app.command("start")
def postgres_start_cmd():
    """Start PostgreSQL database server (port 5432)."""
    mod = get_module_manager().get_module("postgres")
    if not mod:
        logger.error("PostgreSQL module not found.")
        raise typer.Exit(code=1)
    mod.start()
    st = mod.status()
    console.print(f"[bold green]✓ PostgreSQL started ({st.get('details', 'Port 5432')}).[/bold green]")


@postgres_app.command("stop")
def postgres_stop_cmd():
    """Stop PostgreSQL database server."""
    mod = get_module_manager().get_module("postgres")
    if not mod:
        logger.error("PostgreSQL module not found.")
        raise typer.Exit(code=1)
    mod.stop()
    console.print("[bold green]✓ PostgreSQL stopped.[/bold green]")


@postgres_app.command("restart")
def postgres_restart_cmd():
    """Restart PostgreSQL database server."""
    mod = get_module_manager().get_module("postgres")
    if not mod:
        logger.error("PostgreSQL module not found.")
        raise typer.Exit(code=1)
    mod.restart()
    console.print("[bold green]✓ PostgreSQL restarted.[/bold green]")


@postgres_app.command("status")
def postgres_status_cmd():
    """Check PostgreSQL server status."""
    mod = get_module_manager().get_module("postgres")
    if not mod:
        logger.error("PostgreSQL module not found.")
        raise typer.Exit(code=1)
    st = mod.status()
    console.print(f"PostgreSQL: {'[bold green]RUNNING[/bold green]' if st.get('running') else '[bold red]STOPPED[/bold red]'} ({st.get('details', '')})")
