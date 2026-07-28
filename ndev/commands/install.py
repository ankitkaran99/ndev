import typer
from ndev.php.installer import install_version
from ndev.logger import logger

from typing import Optional

def install_cmd(
    version: str = typer.Argument(None, help="PHP version to install (e.g. 8.4, 8.3.12)"),
    show_logs: Optional[bool] = typer.Option(
        None,
        "--show-logs/--no-show-logs",
        "-s",
        help="Show verbose compilation and installation logs"
    )
):
    """Compile and install a PHP version from source."""
    if not version:
        version = typer.prompt("PHP version to install (e.g. 8.4, 8.3.12)").strip()
    if not version:
        logger.error("PHP version is required.")
        raise typer.Exit(code=1)
        
    if show_logs is None:
        show_logs = typer.confirm("Show verbose compilation and installation logs?", default=False)
        
    try:
        resolved_version = install_version(version, show_logs=show_logs)
        
        # Auto-activate the version if no active version is set
        from ndev.constants import CURRENT_LINK
        if not CURRENT_LINK.exists() and not CURRENT_LINK.is_symlink():
            logger.info(f"No active PHP version set. Setting PHP {resolved_version} as active...")
            from ndev.commands.use import use_cmd
            use_cmd(resolved_version)
            
    except Exception as e:
        logger.error(f"Installation failed: {e}")
        raise typer.Exit(code=1)

