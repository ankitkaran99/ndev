import typer
from ndev.constants import CURRENT_LINK
from ndev.runtime.fpm import reload_fpm
from ndev.logger import logger

def reload_cmd(target: str = typer.Argument(None, help="PHP version or service (e.g. 8.4, pma) to reload")):
    """Gracefully reload PHP-FPM configuration for a version or restart pma service."""
    if target and target.lower() in ["pma", "phpmyadmin"]:
        from ndev.runtime.pma import restart_pma
        restart_pma()
        return
    from ndev.utils import get_version_or_prompt
    try:
        version = get_version_or_prompt(target, "PHP version or service to reload")
        if version and version.lower() in ["pma", "phpmyadmin"]:
            from ndev.runtime.pma import restart_pma
            restart_pma()
            return
        if not version:
            logger.error("No version or service specified.")
            raise typer.Exit(code=1)
        reload_fpm(version)
    except Exception as e:
        logger.error(f"Failed to reload service: {e}")
        raise typer.Exit(code=1)

