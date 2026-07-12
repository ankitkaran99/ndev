import typer
from packaging.version import parse as parse_version
from rich.console import Console
from rich.table import Table
from ndev.constants import PHP_DIR
from ndev.github import fetch_releases
from ndev.logger import logger

console = Console()

def update_cmd():
    """Check if installed PHP versions have newer patch releases available."""
    if not PHP_DIR.exists():
        logger.info("No PHP versions installed yet.")
        return
        
    installed_versions = []
    for path in PHP_DIR.iterdir():
        if path.is_dir():
            installed_versions.append(path.name)
            
    if not installed_versions:
        logger.info("No PHP versions installed yet.")
        return
        
    logger.info("Checking for newer patch releases...")
    
    table = Table(title="PHP Update Check")
    table.add_column("Installed Version", style="bold cyan")
    table.add_column("Latest Available")
    table.add_column("Status")
    
    for v in installed_versions:
        parts = v.split(".")
        try:
            major = int(parts[0])
            minor_prefix = f"{parts[0]}.{parts[1]}."
        except (ValueError, IndexError):
            continue
            
        releases = fetch_releases(major)
        if not releases:
            table.add_row(v, "Unknown", "[yellow]Network Error[/yellow]")
            continue
            
        matching = [rel for rel in releases.keys() if rel.startswith(minor_prefix)]
        if not matching:
            table.add_row(v, v, "Up to date")
            continue
            
        latest = max(matching, key=parse_version)
        if parse_version(latest) > parse_version(v):
            table.add_row(v, latest, f"[bold yellow]Update Available[/bold yellow] (run 'ndev install {latest}')")
        else:
            table.add_row(v, v, "Up to date")
            
    console.print(table)
