import typer
from ndev.constants import CURRENT_LINK
from ndev.runtime.fpm import stop_fpm
from ndev.logger import logger

def stop_cmd(version: str = typer.Argument(None, help="PHP version to stop (defaults to current active version)")):
    """Stop PHP-FPM for a version."""
    from ndev.utils import get_version_or_prompt
    try:
        version = get_version_or_prompt(version, "PHP version to stop")
        if not version:
            logger.error("No version specified.")
            raise typer.Exit(code=1)
        stop_fpm(version)
    except Exception as e:
        logger.error(f"Failed to stop PHP-FPM: {e}")
        raise typer.Exit(code=1)

