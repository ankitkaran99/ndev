import typer
from ndev.constants import CURRENT_LINK
from ndev.runtime.fpm import restart_fpm
from ndev.logger import logger

def restart_cmd(version: str = typer.Argument(None, help="PHP version to restart (defaults to current active version)")):
    """Restart PHP-FPM for a version."""
    try:
        if not version:
            if CURRENT_LINK.exists() and CURRENT_LINK.is_symlink():
                version = CURRENT_LINK.resolve().name
            else:
                logger.error("No version specified and no current active version set.")
                raise typer.Exit(code=1)
        restart_fpm(version)
    except Exception as e:
        logger.error(f"Failed to restart PHP-FPM: {e}")
        raise typer.Exit(code=1)
