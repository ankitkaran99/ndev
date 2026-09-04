import shutil
import typer
from ndev.common.constants import PHP_DIR, CURRENT_LINK
from ndev.linux.runtime.fpm import stop_fpm
from ndev.common.manifest import remove_installed_version
from ndev.common.logger import logger

def uninstall_cmd(version: str = typer.Argument(None, help="PHP version to uninstall (e.g. 8.4.23)")):
    """Uninstall a compiled PHP version."""
    if not version:
        # Check if there are installed versions to list
        installed_versions = []
        if PHP_DIR.exists():
            for path in PHP_DIR.iterdir():
                if path.is_dir():
                    installed_versions.append(path.name)
        if installed_versions:
            from packaging.version import parse as parse_version
            try:
                installed_versions = sorted(installed_versions, key=parse_version)
            except Exception:
                installed_versions = sorted(installed_versions)
            from rich.console import Console
            console = Console()
            console.print("\n[bold]Installed PHP Versions[/bold]")
            console.print("----------------------")
            for i, v in enumerate(installed_versions):
                console.print(f" {i + 1}) {v}")
            console.print("")
            try:
                choice = typer.prompt("Select PHP version index or enter version directly", default="1")
                try:
                    idx = int(choice)
                    if 1 <= idx <= len(installed_versions):
                        version = installed_versions[idx - 1]
                except ValueError:
                    version = choice.strip()
            except Exception:
                pass
        if not version:
            version = typer.prompt("PHP version to uninstall").strip()
            
    if not version:
        logger.error("PHP version is required.")
        raise typer.Exit(code=1)
        
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
