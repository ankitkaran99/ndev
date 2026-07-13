import os
import sys
import shutil
import subprocess
import typer
import httpx
from pathlib import Path
from rich.console import Console
from ndev.constants import CURRENT_LINK
from ndev.logger import logger

console = Console()

def chown_to_sudo_user(path: Path):
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user:
        try:
            import pwd
            pw = pwd.getpwnam(sudo_user)
            os.chown(str(path), pw.pw_uid, pw.pw_gid)
        except Exception:
            pass

def get_user_local_bin_dir() -> Path:
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user:
        try:
            import pwd
            return Path(pwd.getpwnam(sudo_user).pw_dir) / ".local" / "bin"
        except Exception:
            pass
    return Path(os.path.expanduser("~/.local/bin"))

def setup_cmd():
    """Install MariaDB, Nginx, and Composer on the system (elevates with sudo for system packages)."""
    if not shutil.which("apt-get"):
        logger.error("This setup command is only supported on Debian-based systems with apt.")
        raise typer.Exit(code=1)
        
    if not shutil.which("sudo"):
        logger.error("sudo command not found. This command requires sudo to install system packages.")
        raise typer.Exit(code=1)
        
    try:
        # 1. Update Package Lists
        console.print("[bold yellow]Updating package lists (sudo apt-get update)...[/bold yellow]")
        subprocess.run(["sudo", "apt-get", "update"], check=True)
        
        # 2. Install MariaDB and Nginx
        console.print("\n[bold yellow]Installing MariaDB and Nginx (sudo apt-get install)...[/bold yellow]")
        subprocess.run(["sudo", "apt-get", "install", "-y", "mariadb-server", "nginx", "curl"], check=True)
        console.print("[bold green]MariaDB and Nginx installed successfully![/bold green]\n")
        
        # 3. Install Composer
        local_bin = get_user_local_bin_dir()
        composer_bin = local_bin / "composer"
        if composer_bin.exists():
            console.print(f"[bold green]Composer is already installed at {composer_bin}[/bold green]")
        else:
            # Find PHP binary
            php_bin = None
            if CURRENT_LINK.exists() or CURRENT_LINK.is_symlink():
                potential_php = CURRENT_LINK / "bin" / "php"
                if potential_php.exists():
                    php_bin = potential_php
            if not php_bin:
                system_php = shutil.which("php")
                if system_php:
                    php_bin = Path(system_php)
                    
            if not php_bin:
                console.print("[bold yellow]PHP is not installed on the system (neither active ndev PHP nor system php).[/bold yellow]")
                console.print("[bold yellow]Skipping Composer installation. Please install a PHP version first using 'ndev install <version>' and run setup again.[/bold yellow]")
            else:
                console.print("[bold yellow]Installing Composer...[/bold yellow]")
                installer_url = "https://getcomposer.org/installer"
                res = httpx.get(installer_url, follow_redirects=True)
                if res.status_code != 200:
                    raise RuntimeError(f"Failed to fetch Composer installer (HTTP status {res.status_code})")
                    
                setup_php = Path("/tmp/composer-setup.php")
                setup_php.write_text(res.text)
                
                local_bin.mkdir(parents=True, exist_ok=True)
                chown_to_sudo_user(local_bin)
                
                subprocess.run([str(php_bin), str(setup_php), f"--install-dir={local_bin}", "--filename=composer"], check=True)
                if setup_php.exists():
                    setup_php.unlink()
                
                chown_to_sudo_user(composer_bin)
                console.print(f"[bold green]Composer installed successfully under {composer_bin}[/bold green]")
                
        # 4. Create ndev symlink in ~/.local/bin/ndev pointing to the virtualenv ndev executable
        ndev_venv_path = Path(sys.executable).parent / "ndev"
        if ndev_venv_path.exists():
            ndev_link = local_bin / "ndev"
            if ndev_link.exists() or ndev_link.is_symlink():
                ndev_link.unlink()
            local_bin.mkdir(parents=True, exist_ok=True)
            chown_to_sudo_user(local_bin)
            ndev_link.symlink_to(ndev_venv_path)
            chown_to_sudo_user(ndev_link)
            console.print(f"[bold green]Created symlink {ndev_link} -> {ndev_venv_path}[/bold green]")
            
        console.print("\n[bold green]System setup completed successfully![/bold green]")
        
    except subprocess.CalledProcessError as e:
        logger.error(f"Command execution failed: {e}")
        raise typer.Exit(code=1)
    except Exception as e:
        logger.error(f"Setup failed: {e}")
        raise typer.Exit(code=1)
