import typer
from ndev.linux.runtime.fpm import start_fpm
from ndev.common.logger import logger

def start_cmd(target: str = typer.Argument(None, help="PHP version or service (e.g. 8.4, pma, mailpit) to start")):
    """Start PHP-FPM for a version or a service like phpmyadmin (pma) or mailpit."""
    if target and target.lower() in ["pma", "phpmyadmin"]:
        from ndev.linux.runtime.pma import start_pma
        start_pma()
        return
    if target and target.lower() in ["mailpit", "mail"]:
        from ndev.linux.runtime.mailpit import start_mailpit
        start_mailpit()
        return
    from ndev.common.utils import get_version_or_prompt
    try:
        version = get_version_or_prompt(target, "PHP version or service to start")
        if version and version.lower() in ["pma", "phpmyadmin"]:
            from ndev.linux.runtime.pma import start_pma
            start_pma()
            return
        if version and version.lower() in ["mailpit", "mail"]:
            from ndev.linux.runtime.mailpit import start_mailpit
            start_mailpit()
            return
        if not version:
            logger.error("No version or service specified.")
            raise typer.Exit(code=1)
        start_fpm(version)
    except Exception as e:
        logger.error(f"Failed to start service: {e}")
        raise typer.Exit(code=1)

