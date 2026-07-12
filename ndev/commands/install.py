import typer
from ndev.php.installer import install_version
from ndev.logger import logger

def install_cmd(version: str = typer.Argument(..., help="PHP version to install (e.g. 8.4, 8.3.12)")):
    """Compile and install a PHP version from source."""
    try:
        install_version(version)
    except Exception as e:
        logger.error(f"Installation failed: {e}")
        raise typer.Exit(code=1)
