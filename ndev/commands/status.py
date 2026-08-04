import typer
from rich.console import Console
from rich.table import Table
from ndev.constants import CURRENT_LINK
from ndev.runtime.fpm import get_fpm_status
from ndev.logger import logger

console = Console()

def status_cmd(target: str = typer.Argument(None, help="PHP version or service (e.g. 8.4, pma) to check status for")):
    """Check status of a PHP-FPM version or service like pma."""
    if target and target.lower() in ["pma", "phpmyadmin"]:
        from ndev.runtime.pma import get_pma_status
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

    from ndev.utils import get_version_or_prompt
    try:
        version = get_version_or_prompt(target, "PHP version or service to check status")
        if version and version.lower() in ["pma", "phpmyadmin"]:
            from ndev.runtime.pma import get_pma_status
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

        if not version:
            logger.error("No version or service specified.")
            raise typer.Exit(code=1)
        status = get_fpm_status(version)
        
        table = Table(title=f"PHP-FPM {version} Status")
        table.add_column("Property", style="bold cyan")
        table.add_column("Value")
        
        status_text = "[bold green]Running[/bold green]" if status["running"] else "[bold red]Stopped[/bold red]"
        table.add_row("Version", status["version"])
        table.add_row("Status", status_text)
        table.add_row("PID", str(status["pid"]) if status["pid"] else "N/A")
        table.add_row("Socket Path", status["socket"])
        table.add_row("Socket Active", "[green]Yes[/green]" if status["socket_exists"] else "[yellow]No[/yellow]")
        
        console.print(table)
    except Exception as e:
        logger.error(f"Failed to get service status: {e}")
        raise typer.Exit(code=1)
