import typer
from ndev.constants import CURRENT_LINK
from ndev.logger import logger

def current_cmd():
    """Show the currently active PHP version."""
    if CURRENT_LINK.exists() and CURRENT_LINK.is_symlink():
        version = CURRENT_LINK.resolve().name
        logger.info(f"Current active PHP version: {version}")
    else:
        logger.info("No active PHP version set. Use 'ndev use <version>' to set one.")
