import typer
from pathlib import Path
from rich.console import Console
from rich.table import Table
from ndev.constants import PHP_DIR, CURRENT_LINK
from ndev.runtime.fpm import get_fpm_status
from ndev.logger import logger

console = Console()

def list_cmd():
    """List all locally installed PHP versions."""
    if not PHP_DIR.exists():
        logger.info("No PHP versions installed yet. Install one with 'ndev install <version>'.")
        return
        
    installed_versions = []
    for path in PHP_DIR.iterdir():
        if path.is_dir():
            installed_versions.append(path.name)
            
    if not installed_versions:
        logger.info("No PHP versions installed yet. Install one with 'ndev install <version>'.")
        return
        
    from packaging.version import parse as parse_version
    installed_versions = sorted(installed_versions, key=parse_version)
    
    active_version = None
    if CURRENT_LINK.exists() and CURRENT_LINK.is_symlink():
        active_version = CURRENT_LINK.resolve().name
        
    table = Table(title="Installed PHP Versions")
    table.add_column("Version", style="bold cyan")
    table.add_column("Status")
    table.add_column("Active", justify="center")
    
    for v in installed_versions:
        status = get_fpm_status(v)
        status_text = "[green]Running[/green]" if status["running"] else "Stopped"
        
        is_active = v == active_version
        active_text = "[bold green]* (active)[/bold green]" if is_active else ""
        
        table.add_row(v, status_text, active_text)
        
    console.print(table)
