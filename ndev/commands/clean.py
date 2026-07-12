import shutil
import typer
from ndev.constants import BUILDS_DIR, DOWNLOADS_DIR
from ndev.logger import logger

def clean_cmd(
    builds: bool = typer.Option(True, "--builds/--no-builds", help="Clean extracted build source folders"),
    downloads: bool = typer.Option(False, "--downloads", help="Clean cached download tarballs")
):
    """Clean up build files and optionally downloaded archives to free disk space."""
    try:
        if builds and BUILDS_DIR.exists():
            logger.info(f"Cleaning build directory: {BUILDS_DIR}")
            shutil.rmtree(BUILDS_DIR)
            BUILDS_DIR.mkdir()
            
        if downloads and DOWNLOADS_DIR.exists():
            logger.info(f"Cleaning downloads cache: {DOWNLOADS_DIR}")
            shutil.rmtree(DOWNLOADS_DIR)
            DOWNLOADS_DIR.mkdir()
            
        logger.info("Cleanup completed successfully.")
    except Exception as e:
        logger.error(f"Cleanup failed: {e}")
        raise typer.Exit(code=1)
