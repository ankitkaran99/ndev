import os
import sys
import re
import subprocess
import shutil
import typer
from pathlib import Path
from rich.console import Console
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

def get_php_sockets() -> list[tuple[str, Path]]:
    sockets = []
    # ndev sockets
    ndev_run = get_user_ndev_dir() / "run"
    if ndev_run.exists():
        for sock in ndev_run.glob("php*.sock"):
            name = sock.stem
            if name.startswith("php"):
                name = name[3:]
            if len(name) == 2 and name.isdigit():
                ver = f"{name[0]}.{name[1]}"
            else:
                ver = name
            sockets.append((ver, sock))
            
    return sockets

def vhost_cmd(
    domain: str = typer.Option(None, "--domain", "-d", help="Domain (e.g. project.local)"),
    root: str = typer.Option(None, "--root", "-r", help="Project Root Directory"),
    php: str = typer.Option(None, "--php", "-p", help="PHP socket alias or index"),
    ssl: bool = typer.Option(False, "--ssl", help="Enable SSL/HTTPS with local certificate generation")
):
    """Create Nginx Virtual Host config, map to hosts file, and reload Nginx."""
    if os.geteuid() != 0:
        logger.error("Please run as root (e.g., sudo ndev vhost)")
        raise typer.Exit(code=1)
        
    if not domain:
        domain = typer.prompt("Domain (e.g. project.local)").strip()
    if not domain:
        logger.error("Domain is required.")
        raise typer.Exit(code=1)
        
    if not root:
        root = typer.prompt("Project Root").strip()
    root_path = Path(root)
    if not root_path.exists() or not root_path.is_dir():
        logger.error(f"Project root directory does not exist: {root}")
        raise typer.Exit(code=1)
        
    sockets = get_php_sockets()
    if not sockets:
        logger.error("No active PHP-FPM sockets found.")
        raise typer.Exit(code=1)
        
    selected_sock = None
    if php:
        # Check if match alias
        clean_php = php.lower()
        if clean_php.startswith("ndev "):
            clean_php = clean_php[len("ndev "):]
        for label, sock in sockets:
            if clean_php in label.lower():
                selected_sock = sock
                break
        if not selected_sock:
            try:
                idx = int(php)
                if 1 <= idx <= len(sockets):
                    selected_sock = sockets[idx - 1][1]
            except ValueError:
                pass
        if not selected_sock:
            logger.error(f"Invalid PHP selection: {php}")
            raise typer.Exit(code=1)
    else:
        console.print("\n[bold]Available PHP Versions[/bold]")
        console.print("----------------------")
        for i, (label, sock) in enumerate(sockets):
            console.print(f" {i + 1}) {label}")
        console.print("")
        choice = typer.prompt("Select PHP version index", type=int)
        if choice < 1 or choice > len(sockets):
            logger.error("Invalid selection.")
            raise typer.Exit(code=1)
        selected_sock = sockets[choice - 1][1]
        
    nginx_available = Path("/etc/nginx/sites-available")
    nginx_enabled = Path("/etc/nginx/sites-enabled")
    hosts_file = Path("/etc/hosts")
    
    if not nginx_available.exists() or not nginx_enabled.exists():
        logger.error("Nginx configuration directories not found.")
        raise typer.Exit(code=1)
        
    conf_file = nginx_available / f"{domain}.conf"
    
    cert_path, key_path = None, None
    if ssl:
        if not shutil.which("mkcert"):
            logger.error("mkcert binary not found. Please install mkcert to generate local certificates.")
            raise typer.Exit(code=1)
        certs_dir = get_user_ndev_dir() / "certs"
        try:
            cert_path, key_path = generate_local_cert(domain, certs_dir)
            console.print(f"Generated SSL Certificates:")
            console.print(f"  Cert: {cert_path}")
            console.print(f"  Key : {key_path}")
        except Exception as e:
            logger.error(f"Failed to generate SSL certificate: {e}")
            raise typer.Exit(code=1)

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
        
        # Add to /etc/hosts if not present
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
                
        # Test Nginx
        res = subprocess.run(["nginx", "-t"], capture_output=True, text=True)
        if res.returncode != 0:
            logger.error(f"Nginx config test failed:\n{res.stderr}")
            enabled_link.unlink(missing_ok=True)
            conf_file.unlink(missing_ok=True)
            raise typer.Exit(code=1)
            
        # Reload Nginx
        subprocess.run(["systemctl", "reload", "nginx"], check=True)
        
        console.print(f"\n[bold green]VHost Created Successfully[/bold green]")
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
