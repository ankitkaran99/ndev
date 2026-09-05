import typer
from rich.console import Console
from rich.table import Table
from ndev.linux.runtime.fpm import get_fpm_status
from ndev.common.logger import logger
from ndev.common.modules import get_module_manager
from ndev.common.constants import PHP_DIR

console = Console()

def status_cmd(target: str = typer.Argument(None, help="PHP version, core service (e.g. pma, nginx, mariadb), or module (e.g. mailpit, redis, postgres) to check status for")):
    """Check status of all services/modules or a specific target."""
    if target and target.lower() in ["pma", "phpmyadmin"]:
        from ndev.linux.runtime.pma import get_pma_status
        status = get_pma_status()
        table = Table(title="phpMyAdmin Service Status")
        table.add_column("Property", style="bold cyan")
        table.add_column("Value")
        
        status_text = "[bold green]Running[/bold green]" if status["running"] else "[bold red]Stopped[/bold red]"
        table.add_row("Service", "phpMyAdmin (pma)")
        table.add_row("Status", status_text)
        table.add_row("PID", str(status["pid"]) if status["pid"] else "N/A")
        table.add_row("Port", str(status["port"]) if status["port"] else "N/A")
        table.add_row("URL", status["url"] if status["url"] else "N/A")
        console.print(table)
        return

    if target:
        mod = get_module_manager().get_module(target)
        if mod:
            st = mod.status()
            table = Table(title=f"Module Status: {mod.display_name}")
            table.add_column("Property", style="bold cyan")
            table.add_column("Value")
            table.add_row("Name", mod.name)
            table.add_row("Category", mod.category.title())
            table.add_row("Status", "[bold green]RUNNING[/bold green]" if st.get("running") else "[bold red]STOPPED[/bold red]")
            table.add_row("PID", str(st.get("pid") or "N/A"))
            table.add_row("Details", st.get("details", "-"))
            console.print(table)
            return

        # Check PHP version
        try:
            status = get_fpm_status(target)
            table = Table(title=f"PHP-FPM {target} Status")
            table.add_column("Property", style="bold cyan")
            table.add_column("Value")
            status_text = "[bold green]Running[/bold green]" if status["running"] else "[bold red]Stopped[/bold red]"
            table.add_row("Version", status["version"])
            table.add_row("Status", status_text)
            table.add_row("PID", str(status["pid"]) if status["pid"] else "N/A")
            table.add_row("Socket Path", status["socket"])
            table.add_row("Socket Active", "[green]Yes[/green]" if status["socket_exists"] else "[yellow]No[/yellow]")
            console.print(table)
            return
        except Exception:
            pass

    # Overall Core Services & Modules Dashboard
    table = Table(title="ndev Core Services Dashboard")
    table.add_column("Service", style="bold cyan")
    table.add_column("Type", style="magenta")
    table.add_column("Status")
    table.add_column("Details")

    # phpMyAdmin
    from ndev.linux.runtime.pma import get_pma_status
    pma_st = get_pma_status()
    table.add_row(
        "phpMyAdmin",
        "Admin Tool (Core)",
        "[bold green]RUNNING[/bold green]" if pma_st.get("running") else "[bold red]STOPPED[/bold red]",
        pma_st.get("url", "http://127.0.0.1:8080")
    )

    # PHP-FPM Pools
    if PHP_DIR.exists():
        for d in sorted(PHP_DIR.iterdir()):
            if d.is_dir():
                st = get_fpm_status(d.name)
                table.add_row(
                    f"PHP {d.name}",
                    "PHP-FPM (Core)",
                    "[bold green]RUNNING[/bold green]" if st.get("running") else "[bold red]STOPPED[/bold red]",
                    f"Socket: {st.get('socket')}"
                )

    console.print(table)

    # Modules
    modules = get_module_manager().list_modules()
    if modules:
        mod_table = Table(title="ndev Dynamic Modules (~/.ndev/modules/)")
        mod_table.add_column("Module", style="bold cyan")
        mod_table.add_column("Category", style="magenta")
        mod_table.add_column("Status")
        mod_table.add_column("Ports / Details")
        for m in modules:
            st = m.status()
            mod_table.add_row(
                m.display_name,
                m.category.title(),
                "[bold green]RUNNING[/bold green]" if st.get("running") else ("[yellow]NOT INSTALLED[/yellow]" if not st.get("installed") else "[bold red]STOPPED[/bold red]"),
                st.get("details", "-")
            )
        console.print(mod_table)

