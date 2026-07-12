import shutil
import typer
from ndev.constants import PHP_DIR, CURRENT_LINK
from ndev.runtime.fpm import stop_fpm
from ndev.manifest import remove_installed_version
from ndev.logger import logger

def uninstall_cmd(version: str = typer.Argument(..., help="PHP version to uninstall (e.g. 8.4.23)")):
    """Uninstall a compiled PHP version."""
    prefix = PHP_DIR / version
    if not prefix.exists():
        logger.error(f"PHP version {version} is not installed.")
        raise typer.Exit(code=1)
        
    try:
        stop_fpm(version)
        
        logger.info(f"Removing files at {prefix}...")
        shutil.rmtree(prefix)
        
        remove_installed_version(version)
        
        if CURRENT_LINK.exists() and CURRENT_LINK.is_symlink():
            if CURRENT_LINK.resolve() == prefix.resolve():
                logger.info("Removing symlink to current version.")
                CURRENT_LINK.unlink()
                
        logger.info(f"PHP version {version} uninstalled successfully.")
    except Exception as e:
        logger.error(f"Uninstallation failed: {e}")
        raise typer.Exit(code=1)
