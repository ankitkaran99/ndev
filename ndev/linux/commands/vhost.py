import os
import sys
import re
import subprocess
import shutil
import typer
from pathlib import Path
from rich.console import Console
from ndev.common.logger import logger
from typing import Optional

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

def generate_local_cert(domain: str, certs_dir: Path) -> tuple[Path, Path]:
    cert_path = certs_dir / f"{domain}.crt"
    key_path = certs_dir / f"{domain}.key"
    
    if cert_path.exists() and key_path.exists():
        return cert_path, key_path
        
    certs_dir.mkdir(parents=True, exist_ok=True)
    chown_to_sudo_user(certs_dir)
    
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user:
        cmd = [
            "sudo", "-u", sudo_user,
            "mkcert",
            "-cert-file", str(cert_path),
            "-key-file", str(key_path),
            domain, f"*.{domain}"
        ]
    else:
        cmd = [
            "mkcert",
            "-cert-file", str(cert_path),
            "-key-file", str(key_path),
            domain, f"*.{domain}"
        ]
        
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    chown_to_sudo_user(key_path)
    chown_to_sudo_user(cert_path)
            
    return cert_path, key_path

def get_user_ndev_dir() -> Path:
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user:
        try:
            import pwd
            return Path(pwd.getpwnam(sudo_user).pw_dir) / ".ndev"
        except Exception:
            pass
    return Path(os.path.expanduser("~/.ndev"))

def get_installed_php_versions() -> list[dict]:
    installed = []
    ndev_dir = get_user_ndev_dir()
    php_dir = ndev_dir / "php"
    if php_dir.exists():
        for path in php_dir.iterdir():
            if path.is_dir():
                ver = path.name
                # get major/minor for socket
                parts = ver.split(".")
                if len(parts) >= 2:
                    mm = f"{parts[0]}{parts[1]}"
                    label = f"{parts[0]}.{parts[1]}"
                else:
                    mm = ver
                    label = ver
                sock = ndev_dir / "run" / f"php{mm}.sock"
                
                # Check if it is running
                pid_file = ndev_dir / "run" / f"php-fpm-{mm}.pid"
                from ndev.linux.runtime.process import is_pid_running, read_pid_file
                pid = read_pid_file(pid_file)
                is_running = is_pid_running(pid) if pid else False
                
                installed.append({
                    "version": ver,
                    "label": label,
                    "socket": sock,
                    "running": is_running
                })
    # Sort by version
    from packaging.version import parse as parse_version
    try:
        installed.sort(key=lambda x: parse_version(x["version"]))
    except Exception:
        installed.sort(key=lambda x: x["version"])
    return installed

def vhost_cmd(
    domain: str = typer.Option(None, "--domain", "-d", help="Domain (e.g. project.local)"),
    root: str = typer.Option(None, "--root", "-r", help="Project Root Directory"),
    php: str = typer.Option(None, "--php", "-p", help="PHP socket alias, version, or index"),
    ssl: Optional[bool] = typer.Option(None, "--ssl/--no-ssl", help="Enable SSL/HTTPS with local certificate generation")
):
    """Create Nginx Virtual Host config, map to hosts file, and reload Nginx."""
    if not domain:
        domain = typer.prompt("Domain (e.g. project.local)").strip()
    if not domain:
        logger.error("Domain is required.")
        raise typer.Exit(code=1)
        
    if not root:
        sudo_user = os.environ.get("SUDO_USER")
        if sudo_user:
            try:
                import pwd
                home_dir = Path(pwd.getpwnam(sudo_user).pw_dir)
            except Exception:
                home_dir = Path.home()
        else:
            home_dir = Path.home()
        default_root = str(home_dir / "Sites" / domain)
        root = typer.prompt("Project Root", default=default_root).strip()
    if not root:
        logger.error("Project Root is required.")
        raise typer.Exit(code=1)
        
    root_path = Path(root).resolve()
    if not root_path.exists():
        root_path.mkdir(parents=True, exist_ok=True)
        chown_to_sudo_user(root_path)
    if not any(root_path.iterdir()):
        index_php = root_path / "index.php"
        index_php.write_text(
            f"<?php\n// Virtual host: {domain}\necho '<h1>Welcome to {domain}</h1>';\necho '<p>Served by Nginx & PHP via ndev</p>';\nphpinfo();\n",
            encoding="utf-8"
        )
        chown_to_sudo_user(index_php)
        
    installed_phps = get_installed_php_versions()
    if not installed_phps:
        logger.error("No installed PHP versions found. Please install PHP using 'ndev install <version>' first.")
        raise typer.Exit(code=1)
        
    selected_sock = None
    selected_ver = None
    if php:
        # Check if it is a socket path
        php_path = Path(php)
        if php_path.exists() and php_path.suffix == ".sock":
            selected_sock = php_path
        else:
            clean_php = php.lower()
            if clean_php.startswith("ndev "):
                clean_php = clean_php[len("ndev "):]
                
            for item in installed_phps:
                if clean_php == item["label"].lower() or clean_php == item["version"].lower():
                    selected_sock = item["socket"]
                    selected_ver = item["version"]
                    break
                    
            if not selected_sock:
                try:
                    idx = int(php)
                    if 1 <= idx <= len(installed_phps):
                        selected_sock = installed_phps[idx - 1]["socket"]
                        selected_ver = installed_phps[idx - 1]["version"]
                except ValueError:
                    pass
                    
            if not selected_sock:
                logger.error(f"Invalid PHP selection: {php}")
                raise typer.Exit(code=1)
    else:
        console.print("\n[bold]Available PHP Versions[/bold]")
        console.print("----------------------")
        for i, item in enumerate(installed_phps):
            status = "[green]Running[/green]" if item["running"] else "[yellow]Stopped[/yellow]"
            console.print(f" {i + 1}) PHP {item['version']} ({item['label']}) - {status}")
        console.print("")
        choice = typer.prompt("Select PHP version index", type=int)
        if choice < 1 or choice > len(installed_phps):
            logger.error("Invalid selection.")
            raise typer.Exit(code=1)
        selected_sock = installed_phps[choice - 1]["socket"]
        selected_ver = installed_phps[choice - 1]["version"]
        
    if ssl is None:
        ssl = typer.confirm("Enable SSL/HTTPS?", default=False)
        
    # If selected PHP version is stopped, start it
    if selected_ver:
        selected_item = next((item for item in installed_phps if item["version"] == selected_ver), None)
        if selected_item and not selected_item["running"]:
            console.print(f"[yellow]PHP-FPM {selected_ver} is stopped. Starting it...[/yellow]")
            try:
                from ndev.linux.runtime.fpm import start_fpm
                start_fpm(selected_ver)
            except Exception as e:
                logger.warning(f"Could not automatically start PHP-FPM: {e}")
                
    cert_path, key_path = None, None
    if ssl:
        if not shutil.which("mkcert"):
            logger.error("mkcert binary not found. Please install mkcert to generate local certificates.")
            raise typer.Exit(code=1)
        certs_dir = get_user_ndev_dir() / "certs"
        try:
            cert_path, key_path = generate_local_cert(domain, certs_dir)
            console.print("Generated SSL Certificates:")
            console.print(f"  Cert: {cert_path}")
            console.print(f"  Key : {key_path}")
        except Exception as e:
            logger.error(f"Failed to generate SSL certificate: {e}")
            raise typer.Exit(code=1)
            
    if os.geteuid() != 0:
        console.print("\n[bold yellow]Privileged operations required. Elevating via sudo...[/bold yellow]")
        cmd = [
            "sudo",
            sys.executable,
            "-m",
            "ndev",
            "vhost",
            "--domain",
            domain,
            "--root",
            root,
            "--php",
            str(selected_sock)
        ]
        if ssl:
            cmd.append("--ssl")
        else:
            cmd.append("--no-ssl")
            
        try:
            res = subprocess.run(cmd)
            raise typer.Exit(code=res.returncode)
        except KeyboardInterrupt:
            raise typer.Exit(code=1)
            
    nginx_available = Path("/etc/nginx/sites-available")
    nginx_enabled = Path("/etc/nginx/sites-enabled")
    hosts_file = Path("/etc/hosts")
    
    if not nginx_available.exists() or not nginx_enabled.exists():
        logger.error("Nginx configuration directories not found.")
        raise typer.Exit(code=1)
        
    conf_file = nginx_available / f"{domain}.conf"
    
    if ssl:
        config_template = f"""server {{
    listen 80;
    listen [::]:80;
    server_name {domain};
    return 301 https://$host$request_uri;
}}

server {{
    listen 443 ssl;
    listen [::]:443 ssl;

    server_name {domain};

    ssl_certificate {cert_path};
    ssl_certificate_key {key_path};

    root {root};
    index index.php index.html index.htm;

    access_log /var/log/nginx/{domain}.access.log;
    error_log  /var/log/nginx/{domain}.error.log;

    location / {{
        try_files $uri $uri/ /index.php?$query_string;
    }}

    location ~ \\.php$ {{
        include snippets/fastcgi-php.conf;
        fastcgi_pass unix:{selected_sock};
    }}

    location ~ /\\.ht {{
        deny all;
    }}
}}
"""
    else:
        config_template = f"""server {{
    listen 80;
    listen [::]:80;

    server_name {domain};

    root {root};
    index index.php index.html index.htm;

    access_log /var/log/nginx/{domain}.access.log;
    error_log  /var/log/nginx/{domain}.error.log;

    location / {{
        try_files $uri $uri/ /index.php?$query_string;
    }}

    location ~ \\.php$ {{
        include snippets/fastcgi-php.conf;
        fastcgi_pass unix:{selected_sock};
    }}

    location ~ /\\.ht {{
        deny all;
    }}
}}
"""

    try:
        conf_file.write_text(config_template)
        enabled_link = nginx_enabled / f"{domain}.conf"
        if enabled_link.exists() or enabled_link.is_symlink():
            enabled_link.unlink()
        enabled_link.symlink_to(conf_file)
        
        hosts_content = hosts_file.read_text()
        pattern = rf"^\s*127\.0\.0\.1\s+.*\b{re.escape(domain)}\b"
        found = False
        for line in hosts_content.splitlines():
            if re.match(pattern, line):
                found = True
                break
        if not found:
            with hosts_file.open("a") as f:
                f.write(f"\n127.0.0.1 {domain}\n")
                
        res = subprocess.run(["nginx", "-t"], capture_output=True, text=True)
        if res.returncode != 0:
            logger.error(f"Nginx config test failed:\n{res.stderr}")
            enabled_link.unlink(missing_ok=True)
            conf_file.unlink(missing_ok=True)
            raise typer.Exit(code=1)
            
        subprocess.run(["systemctl", "reload", "nginx"], check=True)
        
        console.print("\n[bold green]VHost Created Successfully[/bold green]")
        console.print("--------------------------")
        console.print(f"Domain      : {domain}")
        console.print(f"Root        : {root}")
        console.print(f"PHP Socket  : {selected_sock}")
        console.print(f"Config      : {conf_file}")
        if ssl:
            console.print(f"SSL Cert    : {cert_path}")
            console.print(f"SSL Key     : {key_path}")
            console.print(f"\nOpen: https://{domain}")
        else:
            console.print(f"\nOpen: http://{domain}")
    except Exception as e:
        logger.error(f"Failed to create virtual host: {e}")
        raise typer.Exit(code=1)

