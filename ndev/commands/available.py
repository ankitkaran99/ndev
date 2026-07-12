import typer
from rich.console import Console
from rich.table import Table
from ndev.github import fetch_releases
from ndev.logger import logger

console = Console()

def available_cmd():
    """List all available PHP versions from php.net."""
    logger.info("Fetching available PHP versions from php.net...")
    
    releases_8 = fetch_releases(8)
    releases_7 = fetch_releases(7)
    
    all_releases = {**releases_8, **releases_7}
    
    if not all_releases:
        logger.error("Could not fetch available releases. Check your network connection.")
        raise typer.Exit(code=1)
        
    from packaging.version import parse as parse_version
    sorted_versions = sorted(all_releases.keys(), key=parse_version, reverse=True)
    
    table = Table(title="Available PHP Releases")
    table.add_column("Version", style="bold cyan")
    table.add_column("Release Date")
    table.add_column("Security Release")
    
    for v in sorted_versions:
        data = all_releases[v]
        date = data.get("date", "N/A")
        tags = data.get("tags", [])
        is_security = "Yes" if "security" in tags else "No"
        
        table.add_row(v, date, is_security)
        
    console.print(table)
