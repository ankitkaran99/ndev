import typer
from ndev.common.constants import LOGS_DIR
from ndev.common.logger import logger

def logs_cmd(
    version: str = typer.Argument(None, help="PHP version to view logs for (defaults to current active version)"),
    lines: int = typer.Option(50, "--lines", "-n", help="Number of lines to display")
):
    """View PHP-FPM logs for a version."""
    from ndev.common.utils import get_version_or_prompt
    if not version:
        version = get_version_or_prompt(version, "PHP version to view logs")
        if not version:
            logger.error("No version specified.")
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
