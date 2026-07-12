import typer
from ndev.php.installer import install_version
from ndev.logger import logger

def install_cmd(
    version: str = typer.Argument(..., help="PHP version to install (e.g. 8.4, 8.3.12)"),
    show_logs: bool = typer.Option(
        False,
        "--show-logs",
        "-s",
        help="Show verbose compilation and installation logs"
    )
):
    """Compile and install a PHP version from source."""
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
