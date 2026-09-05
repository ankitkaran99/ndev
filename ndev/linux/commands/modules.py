"""
Linux CLI commands for managing extensible ndev modules.
"""
from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table
from typing import Optional

from ndev.common.logger import logger
from ndev.common.modules import get_module_manager

console = Console()
module_app = typer.Typer(
    help="Manage extensible ndev modules (mailpit, redis, postgres, custom modules).",
    no_args_is_help=True
)


@module_app.command("list")
def module_list_cmd():
    """List all available and installed modules in ~/.ndev/modules/."""
    mgr = get_module_manager()
    modules = mgr.list_modules()

    if not modules:
        console.print("[yellow]No modules found in ~/.ndev/modules/.[/yellow]")
        return

    table = Table(title="ndev Modules Dashboard (~/.ndev/modules/)")
    table.add_column("Module Name", style="bold cyan")
    table.add_column("Display Name")
    table.add_column("Category", style="magenta")
    table.add_column("Version")
    table.add_column("Status")
    table.add_column("Ports / Web UI")
    table.add_column("Description", style="dim")

    for m in modules:
        st = m.status()
        if not st.get("installed"):
            st_text = "[yellow]Not Installed[/yellow]"
        elif st.get("running"):
            st_text = "[bold green]Running[/bold green]"
        else:
            st_text = "[bold red]Stopped[/bold red]"

        ports_ui = []
        if m.ports:
            ports_ui.append(", ".join(f"{k}:{v}" for k, v in m.ports.items()))
        if m.web_ui:
            ports_ui.append(f"UI: {m.web_ui}")
        ports_str = " | ".join(ports_ui) if ports_ui else "-"

        table.add_row(
            m.name,
            m.display_name,
            m.category.title(),
            m.version,
            st_text,
            ports_str,
            m.description
        )

    console.print(table)


@module_app.command("install")
def module_install_cmd(name: str = typer.Argument(..., help="Module name to install")):
    """Install or setup a module."""
    mod = get_module_manager().get_module(name)
    if not mod:
        logger.error(f"Module '{name}' not found in ~/.ndev/modules/.")
        raise typer.Exit(code=1)

    console.print(f"[bold blue]Installing {mod.display_name} module...[/bold blue]")
    try:
        mod.install()
        console.print(f"[bold green]✓ {mod.display_name} installed successfully.[/bold green]")
    except Exception as e:
        logger.error(f"Failed to install module {name}: {e}")
        raise typer.Exit(code=1)


@module_app.command("start")
def module_start_cmd(name: str = typer.Argument(..., help="Module name to start")):
    """Start a module background service."""
    mod = get_module_manager().get_module(name)
    if not mod:
        logger.error(f"Module '{name}' not found in ~/.ndev/modules/.")
        raise typer.Exit(code=1)

    if not mod.is_installed():
        console.print(f"[yellow]{mod.display_name} is not installed - installing first...[/yellow]")
        mod.install()

    try:
        pid = mod.start()
        st = mod.status()
        console.print(f"[bold green]✓ {mod.display_name} started ({st.get('details', 'Running')}).[/bold green]")
    except Exception as e:
        logger.error(f"Failed to start module {name}: {e}")
        raise typer.Exit(code=1)


@module_app.command("stop")
def module_stop_cmd(name: str = typer.Argument(..., help="Module name to stop")):
    """Stop a module background service."""
    mod = get_module_manager().get_module(name)
    if not mod:
        logger.error(f"Module '{name}' not found in ~/.ndev/modules/.")
        raise typer.Exit(code=1)

    mod.stop()
    console.print(f"[bold green]✓ {mod.display_name} stopped.[/bold green]")


@module_app.command("restart")
def module_restart_cmd(name: str = typer.Argument(..., help="Module name to restart")):
    """Restart a module background service."""
    mod = get_module_manager().get_module(name)
    if not mod:
        logger.error(f"Module '{name}' not found in ~/.ndev/modules/.")
        raise typer.Exit(code=1)

    if not mod.is_installed():
        logger.error(f"{mod.display_name} is not installed.")
        raise typer.Exit(code=1)

    try:
        pid = mod.restart()
        st = mod.status()
        console.print(f"[bold green]✓ {mod.display_name} restarted ({st.get('details', 'Running')}).[/bold green]")
    except Exception as e:
        logger.error(f"Failed to restart module {name}: {e}")
        raise typer.Exit(code=1)


@module_app.command("status")
def module_status_cmd(name: str = typer.Argument(..., help="Module name to check")):
    """Show detailed status of a module."""
    mod = get_module_manager().get_module(name)
    if not mod:
        logger.error(f"Module '{name}' not found in ~/.ndev/modules/.")
        raise typer.Exit(code=1)

    st = mod.status()
    table = Table(title=f"Module Status: {mod.display_name}")
    table.add_column("Property", style="bold cyan")
    table.add_column("Value")

    table.add_row("Name", mod.name)
    table.add_row("Display Name", mod.display_name)
    table.add_row("Version", mod.version)
    table.add_row("Category", mod.category.title())
    table.add_row("Installed", "[green]Yes[/green]" if st.get("installed") else "[red]No[/red]")
    table.add_row("Running", "[bold green]RUNNING[/bold green]" if st.get("running") else "[bold red]STOPPED[/bold red]")
    table.add_row("PID", str(st.get("pid") or "N/A"))
    if mod.ports:
        table.add_row("Ports", ", ".join(f"{k}: {v}" for k, v in mod.ports.items()))
    if mod.web_ui:
        table.add_row("Web UI", mod.web_ui)
    table.add_row("Details", st.get("details", "-"))
    table.add_row("Module Path", str(mod.module_dir))

    console.print(table)


@module_app.command("open")
def module_open_cmd(name: str = typer.Argument(..., help="Module name to open web UI for")):
    """Open web UI for a module in the browser."""
    mod = get_module_manager().get_module(name)
    if not mod:
        logger.error(f"Module '{name}' not found in ~/.ndev/modules/.")
        raise typer.Exit(code=1)

    if not mod.open_ui():
        logger.error(f"Module '{mod.display_name}' does not provide a web interface.")
        raise typer.Exit(code=1)
    console.print(f"[bold green]Opened {mod.display_name} in browser.[/bold green]")


@module_app.command("create")
def module_create_cmd(
    name: str = typer.Argument(..., help="Module folder name"),
    title: Optional[str] = typer.Option(None, "--title", "-t", help="Display title"),
    port: Optional[int] = typer.Option(None, "--port", "-p", help="Default port")
):
    """Scaffold a new custom module in ~/.ndev/modules/<name>/."""
    mgr = get_module_manager()
    mod_dir = mgr.create_module_scaffold(name, display_name=title, port=port)
    console.print(f"[bold green]✓ Created module template at:[/bold green] {mod_dir}")
    console.print(f"Edit [cyan]{mod_dir / 'manifest.json'}[/cyan] and [cyan]{mod_dir / 'module.py'}[/cyan] to customize your module.")
