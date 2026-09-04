import typer
from ndev.linux.runtime.fpm import restart_fpm
from ndev.common.logger import logger

def restart_cmd(target: str = typer.Argument(None, help="PHP version or service (e.g. 8.4, pma, mailpit) to restart")):
    """Restart PHP-FPM for a version or a service like phpmyadmin (pma) or mailpit."""
    if target and target.lower() in ["pma", "phpmyadmin"]:
        from ndev.linux.runtime.pma import restart_pma
        restart_pma()
        return
    if target and target.lower() in ["mailpit", "mail"]:
        from ndev.linux.runtime.mailpit import restart_mailpit
        restart_mailpit()
        return
    from ndev.common.utils import get_version_or_prompt
    try:
        version = get_version_or_prompt(target, "PHP version or service to restart")
        if version and version.lower() in ["pma", "phpmyadmin"]:
            from ndev.linux.runtime.pma import restart_pma
            restart_pma()
            return
        if version and version.lower() in ["mailpit", "mail"]:
            from ndev.linux.runtime.mailpit import restart_mailpit
            restart_mailpit()
            return
        if not version:
            logger.error("No version or service specified.")
            raise typer.Exit(code=1)
        restart_fpm(version)
    except Exception as e:
        logger.error(f"Failed to restart service: {e}")
        raise typer.Exit(code=1)

