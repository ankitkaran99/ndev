import typer
from ndev.constants import CURRENT_LINK
from ndev.runtime.fpm import start_fpm
from ndev.logger import logger

def start_cmd(version: str = typer.Argument(None, help="PHP version to start (defaults to current active version)")):
    """Start PHP-FPM for a version."""
    from ndev.utils import get_version_or_prompt
    try:
        version = get_version_or_prompt(version, "PHP version to start")
        if not version:
            logger.error("No version specified.")
            raise typer.Exit(code=1)
        start_fpm(version)
    except Exception as e:
        logger.error(f"Failed to start PHP-FPM: {e}")
        raise typer.Exit(code=1)

