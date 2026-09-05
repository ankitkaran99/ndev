"""
Linux CLI commands for managing MongoDB module.
"""
from __future__ import annotations

import typer
from rich.console import Console
from ndev.common.logger import logger
from ndev.common.modules import get_module_manager

console = Console()
mongodb_app = typer.Typer(
    help="Manage MongoDB database server module.",
    no_args_is_help=True
)


@mongodb_app.command("install")
def mongodb_install_cmd():
    """Install MongoDB binaries / packages."""
    mod = get_module_manager().get_module("mongodb")
    if not mod:
        logger.error("MongoDB module not found.")
        raise typer.Exit(code=1)
    console.print("[bold blue]Installing MongoDB...[/bold blue]")
    mod.install()
    console.print("[bold green]✓ MongoDB installed successfully.[/bold green]")


@mongodb_app.command("start")
def mongodb_start_cmd():
    """Start MongoDB database server (port 27017)."""
    mod = get_module_manager().get_module("mongodb")
    if not mod:
        logger.error("MongoDB module not found.")
        raise typer.Exit(code=1)
    mod.start()
    st = mod.status()
    console.print(f"[bold green]✓ MongoDB started ({st.get('details', 'Port 27017')}).[/bold green]")


@mongodb_app.command("stop")
def mongodb_stop_cmd():
    """Stop MongoDB database server."""
    mod = get_module_manager().get_module("mongodb")
    if not mod:
        logger.error("MongoDB module not found.")
        raise typer.Exit(code=1)
    mod.stop()
    console.print("[bold green]✓ MongoDB stopped.[/bold green]")


@mongodb_app.command("restart")
def mongodb_restart_cmd():
    """Restart MongoDB database server."""
    mod = get_module_manager().get_module("mongodb")
    if not mod:
        logger.error("MongoDB module not found.")
        raise typer.Exit(code=1)
    mod.restart()
    console.print("[bold green]✓ MongoDB restarted.[/bold green]")


@mongodb_app.command("status")
def mongodb_status_cmd():
    """Check MongoDB server status."""
    mod = get_module_manager().get_module("mongodb")
    if not mod:
        logger.error("MongoDB module not found.")
        raise typer.Exit(code=1)
    st = mod.status()
    console.print(f"MongoDB: {'[bold green]RUNNING[/bold green]' if st.get('running') else '[bold red]STOPPED[/bold red]'} ({st.get('details', '')})")

