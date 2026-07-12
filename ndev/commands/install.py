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
        install_version(version, show_logs=show_logs)
    except Exception as e:
        logger.error(f"Installation failed: {e}")
        raise typer.Exit(code=1)
