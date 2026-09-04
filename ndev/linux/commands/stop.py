import typer
from ndev.common.constants import CURRENT_LINK
from ndev.linux.runtime.fpm import stop_fpm
from ndev.common.logger import logger

def stop_cmd(target: str = typer.Argument(None, help="PHP version or service (e.g. 8.4, pma, mailpit) to stop")):
    """Stop PHP-FPM for a version or a service like phpmyadmin (pma) or mailpit."""
    if target and target.lower() in ["pma", "phpmyadmin"]:
        from ndev.linux.runtime.pma import stop_pma
        stop_pma()
        return
    if target and target.lower() in ["mailpit", "mail"]:
        from ndev.linux.runtime.mailpit import stop_mailpit
        stop_mailpit()
        return
    from ndev.common.utils import get_version_or_prompt
    try:
        version = get_version_or_prompt(target, "PHP version or service to stop")
        if version and version.lower() in ["pma", "phpmyadmin"]:
            from ndev.linux.runtime.pma import stop_pma
            stop_pma()
            return
        if version and version.lower() in ["mailpit", "mail"]:
            from ndev.linux.runtime.mailpit import stop_mailpit
            stop_mailpit()
            return
        if not version:
            logger.error("No version or service specified.")
            raise typer.Exit(code=1)
        stop_fpm(version)
    except Exception as e:
        logger.error(f"Failed to stop service: {e}")
        raise typer.Exit(code=1)

