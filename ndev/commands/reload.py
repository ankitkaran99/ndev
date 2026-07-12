import typer
from ndev.constants import CURRENT_LINK
from ndev.runtime.fpm import reload_fpm
from ndev.logger import logger

def reload_cmd(version: str = typer.Argument(None, help="PHP version to reload (defaults to current active version)")):
    """Gracefully reload PHP-FPM configuration for a version."""
    try:
        if not version:
            if CURRENT_LINK.exists() and CURRENT_LINK.is_symlink():
                version = CURRENT_LINK.resolve().name
            else:
                logger.error("No version specified and no current active version set.")
                raise typer.Exit(code=1)
        reload_fpm(version)
    except Exception as e:
        logger.error(f"Failed to reload PHP-FPM: {e}")
        raise typer.Exit(code=1)
