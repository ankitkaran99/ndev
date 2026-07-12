import typer
import os
import shutil
from pathlib import Path
from ndev.constants import PHP_DIR, CURRENT_LINK
from ndev.logger import logger

def use_cmd(version: str = typer.Argument(..., help="PHP version to use (must be installed)")):
    """Set a PHP version as the active version."""
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
