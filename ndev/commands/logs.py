import typer
from ndev.constants import LOGS_DIR, CURRENT_LINK
from ndev.logger import logger

def logs_cmd(
    version: str = typer.Argument(None, help="PHP version to view logs for (defaults to current active version)"),
    lines: int = typer.Option(50, "--lines", "-n", help="Number of lines to display")
):
    """View PHP-FPM logs for a version."""
    if not version:
        if CURRENT_LINK.exists() and CURRENT_LINK.is_symlink():
            version = CURRENT_LINK.resolve().name
        else:
            logger.error("No version specified and no current active version set.")
            raise typer.Exit(code=1)
            
    parts = version.split(".")
    major_minor = f"{parts[0]}{parts[1]}"
    log_file = LOGS_DIR / f"php-fpm-{major_minor}.log"
    
    if not log_file.exists():
        logger.error(f"No log file found at {log_file} for version {version}.")
        raise typer.Exit(code=1)
        
    try:
        with open(log_file, "r") as f:
            content = f.readlines()
        
        last_lines = content[-lines:]
        logger.info(f"Showing last {len(last_lines)} lines of {log_file}:")
        for line in last_lines:
            print(line, end="")
    except Exception as e:
        logger.error(f"Failed to read log file: {e}")
        raise typer.Exit(code=1)
