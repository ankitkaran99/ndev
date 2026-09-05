import typer
from rich.console import Console
from ndev.linux.runtime.fpm import stop_fpm
from ndev.common.logger import logger
from ndev.common.modules import get_module_manager

console = Console()

def stop_cmd(target: str = typer.Argument(None, help="PHP version, core service (e.g. pma, nginx, mariadb), or module (e.g. mailpit, redis, postgres) to stop")):
    """Stop PHP-FPM for a version, core service, or dynamic module."""
    if target and target.lower() in ["pma", "phpmyadmin"]:
        from ndev.linux.runtime.pma import stop_pma
        stop_pma()
        return

    if target:
        mod = get_module_manager().get_module(target)
        if mod:
            mod.stop()
            console.print(f"[bold green]✓ {mod.display_name} stopped.[/bold green]")
            return

    from ndev.common.utils import get_version_or_prompt
    try:
        version = get_version_or_prompt(target, "PHP version or service to stop")
        if version and version.lower() in ["pma", "phpmyadmin"]:
            from ndev.linux.runtime.pma import stop_pma
            stop_pma()
            return
        if version:
            mod = get_module_manager().get_module(version)
            if mod:
                mod.stop()
                console.print(f"[bold green]✓ {mod.display_name} stopped.[/bold green]")
                return
        if not version:
            logger.error("No version or service specified.")
            raise typer.Exit(code=1)
        stop_fpm(version)
    except Exception as e:
        logger.error(f"Failed to stop service: {e}")
        raise typer.Exit(code=1)


