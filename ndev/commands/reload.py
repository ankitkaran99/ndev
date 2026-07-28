import typer
from ndev.constants import CURRENT_LINK
from ndev.runtime.fpm import reload_fpm
from ndev.logger import logger

def reload_cmd(version: str = typer.Argument(None, help="PHP version to reload (defaults to current active version)")):
    """Gracefully reload PHP-FPM configuration for a version."""
    from ndev.utils import get_version_or_prompt
    try:
        version = get_version_or_prompt(version, "PHP version to reload")
        if not version:
            logger.error("No version specified.")
            raise typer.Exit(code=1)
        reload_fpm(version)
    except Exception as e:
        logger.error(f"Failed to reload PHP-FPM: {e}")
        raise typer.Exit(code=1)

