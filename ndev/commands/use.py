import typer
from ndev.constants import PHP_DIR, CURRENT_LINK
from ndev.logger import logger

def use_cmd(version: str = typer.Argument(..., help="PHP version to use (must be installed)")):
    """Set a PHP version as the active version."""
    target = PHP_DIR / version
    if not target.exists():
        logger.error(f"PHP version {version} is not installed. Install it first using 'ndev install {version}'.")
        raise typer.Exit(code=1)
        
    try:
        if CURRENT_LINK.exists() or CURRENT_LINK.is_symlink():
            CURRENT_LINK.unlink()
        CURRENT_LINK.symlink_to(target)
        logger.info(f"Now using PHP version {version}")
    except Exception as e:
        logger.error(f"Failed to switch PHP version: {e}")
        raise typer.Exit(code=1)
