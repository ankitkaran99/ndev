import typer
import os
import shutil
from pathlib import Path
from ndev.constants import PHP_DIR, CURRENT_LINK
from ndev.logger import logger

def use_cmd(version: str = typer.Argument(None, help="PHP version to use (must be installed)")):
    """Set a PHP version as the active version."""
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
            version = typer.prompt("PHP version to use").strip()
            
    if not version:
        logger.error("PHP version is required.")
        raise typer.Exit(code=1)
        
    target = PHP_DIR / version

    if not target.exists():
        logger.error(f"PHP version {version} is not installed. Install it first using 'ndev install {version}'.")
        raise typer.Exit(code=1)
        
    try:
        if CURRENT_LINK.exists() or CURRENT_LINK.is_symlink():
            CURRENT_LINK.unlink()
        CURRENT_LINK.symlink_to(target)
        
        # Ensure ~/.local/bin symlinks exist
        local_bin = Path(os.path.expanduser("~/.local/bin"))
        local_bin.mkdir(parents=True, exist_ok=True)
        
        links = {
            "php": CURRENT_LINK / "bin" / "php",
            "phpize": CURRENT_LINK / "bin" / "phpize",
            "php-config": CURRENT_LINK / "bin" / "php-config",
            "php-fpm": CURRENT_LINK / "sbin" / "php-fpm"
        }
        
        for name, target_path in links.items():
            link_path = local_bin / name
            if link_path.exists() or link_path.is_symlink():
                link_path.unlink()
            link_path.symlink_to(target_path)
            
        logger.info(f"Now using PHP version {version}")
        
        # Check if ~/.local/bin is in PATH
        path_env = os.environ.get("PATH", "")
        local_bin_str = str(local_bin)
        in_path = any(
            p == local_bin_str or Path(p).resolve() == local_bin.resolve()
            for p in path_env.split(os.pathsep)
        )
        if not in_path:
            logger.warning(
                f"[yellow]Warning: {local_bin} is not in your PATH. [/yellow]"
                f"You may need to add it to your shell configuration (e.g. ~/.bashrc or ~/.zshrc):\n"
                f'  export PATH="$HOME/.local/bin:$PATH"'
            )
        else:
            # Verify if the active php command resolves to the ndev symlink
            php_path = shutil.which("php")
            if php_path:
                try:
                    resolved_php = Path(php_path).resolve()
                    expected_php = (local_bin / "php").resolve()
                    if resolved_php != expected_php:
                        logger.warning(
                            f"[yellow]Warning: The active PHP command resolves to '{resolved_php}' [/yellow]\n"
                            f"which is not the ndev symlink '{expected_php}'.\n"
                            f"Please ensure '{local_bin}' appears before other PHP installations in your PATH."
                        )
                except Exception:
                    pass
            
    except Exception as e:
        logger.error(f"Failed to switch PHP version: {e}")
        raise typer.Exit(code=1)
