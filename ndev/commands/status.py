import typer
from rich.console import Console
from rich.table import Table
from ndev.constants import CURRENT_LINK
from ndev.runtime.fpm import get_fpm_status
from ndev.logger import logger

console = Console()

def status_cmd(version: str = typer.Argument(None, help="PHP version to check status for (defaults to current active version)")):
    """Check status of a PHP-FPM version."""
    try:
        if not version:
            if CURRENT_LINK.exists() and CURRENT_LINK.is_symlink():
                version = CURRENT_LINK.resolve().name
            else:
                logger.error("No version specified and no current active version set.")
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
        logger.error(f"Failed to get PHP-FPM status: {e}")
        raise typer.Exit(code=1)
