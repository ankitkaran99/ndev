import typer
from ndev.constants import CURRENT_LINK
from ndev.runtime.fpm import start_fpm
from ndev.logger import logger

def start_cmd(version: str = typer.Argument(None, help="PHP version to start (defaults to current active version)")):
    """Start PHP-FPM for a version."""
    try:
        if not version:
            if CURRENT_LINK.exists() and CURRENT_LINK.is_symlink():
                version = CURRENT_LINK.resolve().name
            else:
                logger.error("No version specified and no current active version set.")
                raise typer.Exit(code=1)
        start_fpm(version)
    except Exception as e:
        logger.error(f"Failed to start PHP-FPM: {e}")
        raise typer.Exit(code=1)
