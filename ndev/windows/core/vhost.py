"""
Virtual host management for Windows:
- Writes Nginx server blocks under ~/.ndev/nginx/conf/ndev-vhosts/<domain>.conf
- Updates C:\\Windows\\System32\\drivers\\etc\\hosts (127.0.0.1)
- Generates local SSL certificates with mkcert
- Controls php-cgi FastCGI worker pool
"""
from __future__ import annotations

import base64
import re
from pathlib import Path
from typing import Optional

from . import fcgi, mkcert, paths
from .elevate import is_admin, run_elevated

TEMPLATE_PATH = Path(__file__).parent.parent / "templates" / "vhost.conf.tmpl"
SSL_TEMPLATE_PATH = Path(__file__).parent.parent / "templates" / "vhost_ssl.conf.tmpl"


def _load_templates() -> tuple[str, str]:
    user_tmpl = paths.TEMPLATES_DIR / "vhost.conf.tmpl"
    user_ssl_tmpl = paths.TEMPLATES_DIR / "vhost_ssl.conf.tmpl"

    tmpl = (
        user_tmpl.read_text(encoding="utf-8")
        if user_tmpl.exists()
        else TEMPLATE_PATH.read_text(encoding="utf-8")
    )
    ssl_tmpl = (
        user_ssl_tmpl.read_text(encoding="utf-8")
        if user_ssl_tmpl.exists()
        else SSL_TEMPLATE_PATH.read_text(encoding="utf-8")
    )
    return tmpl, ssl_tmpl


def write_vhost_conf(domain: str, root: str | Path, php_version: str, ssl: bool = False) -> Path:
    tmpl, ssl_tmpl = _load_templates()
    
    upstream_name = fcgi.nginx_upstream_name(php_version, domain=domain)
    upstream_block = fcgi.render_upstream_block(php_version, domain=domain)
    
    root_clean = str(Path(root).resolve()).replace("\\", "/")
    ndev_home = str(paths.NDEV_HOME.resolve()).replace("\\", "/")

    # Ensure logs directory exists
    paths.NGINX_LOGS_DIR.mkdir(parents=True, exist_ok=True)

    if ssl:
        cert_path, key_path = mkcert.generate_cert(domain)
        conf = ssl_tmpl.format(
            domain=domain,
            root=root_clean,
            ndev_home=ndev_home,
            upstream_name=upstream_name,
            upstream_block=upstream_block,
            cert_path=cert_path,
            key_path=key_path,
        )
    else:
        conf = tmpl.format(
            domain=domain,
            root=root_clean,
            ndev_home=ndev_home,
            upstream_name=upstream_name,
            upstream_block=upstream_block,
        )

    conf_header = f"# ndev-domain: {domain}\n# ndev-php: {php_version}\n"
    full_conf = conf_header + conf

    paths.NGINX_CONF_D.mkdir(parents=True, exist_ok=True)
    conf_path = paths.NGINX_CONF_D / f"{domain}.conf"
    conf_path.write_text(full_conf, encoding="utf-8")
    return conf_path


def _ensure_writable(path: Path) -> None:
    if path.exists():
        import stat
        try:
            mode = path.stat().st_mode
            if not (mode & stat.S_IWRITE):
                path.chmod(mode | stat.S_IWRITE)
        except Exception:
            pass


def add_hosts_entry(domain: str) -> bool:
    """
    Add domain -> 127.0.0.1 mapping to Windows hosts file.
    Uses direct write if admin, or elevated PowerShell if unprivileged.
    """
    domain = domain.strip().lower()
    text = ""
    if paths.HOSTS_PATH.exists():
        text = paths.HOSTS_PATH.read_text(encoding="utf-8", errors="ignore")

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 2 and domain in [p.lower() for p in parts[1:]]:
            return False  # Already mapped

    if is_admin():
        _ensure_writable(paths.HOSTS_PATH)
        with paths.HOSTS_PATH.open("a", encoding="utf-8") as f:
            f.write(f"\n127.0.0.1\t{domain}\n")
        return True

    entry_bytes = f"\r\n127.0.0.1\t{domain}\r\n".encode("utf-8")
    b64_entry = base64.b64encode(entry_bytes).decode("ascii")
    ps_script = (
        f"Set-ItemProperty -Path '{paths.HOSTS_PATH}' -Name IsReadOnly -Value $false -ErrorAction SilentlyContinue; "
        f"$bytes = [System.Convert]::FromBase64String('{b64_entry}'); "
        f"$stream = [System.IO.File]::Open('{paths.HOSTS_PATH}', [System.IO.FileMode]::Append); "
        f"$stream.Write($bytes, 0, $bytes.Length); $stream.Close()"
    )
    encoded = base64.b64encode(ps_script.encode("utf-16le")).decode("ascii")
    exit_code = run_elevated(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded])
    if exit_code != 0:
        raise RuntimeError(f"Failed to update hosts file (exit code {exit_code})")
    return True


def remove_hosts_entry(domain: str) -> bool:
    """Remove domain from Windows hosts file."""
    domain = domain.strip().lower()
    if not paths.HOSTS_PATH.exists():
        return False

    text = paths.HOSTS_PATH.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()
    new_lines = []
    removed = False

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            new_lines.append(line)
            continue
        parts = stripped.split()
        if len(parts) >= 2 and domain in [p.lower() for p in parts[1:]]:
            remaining_hosts = [p for p in parts[1:] if p.lower() != domain]
            if remaining_hosts:
                new_lines.append(f"{parts[0]}\t" + " ".join(remaining_hosts))
            removed = True
        else:
            new_lines.append(line)

    if not removed:
        return False

    new_content = "\r\n".join(new_lines) + "\r\n"
    if is_admin():
        _ensure_writable(paths.HOSTS_PATH)
        paths.HOSTS_PATH.write_text(new_content, encoding="utf-8")
        return True

    b64_content = base64.b64encode(new_content.encode("utf-8")).decode("ascii")
    ps_script = (
        f"Set-ItemProperty -Path '{paths.HOSTS_PATH}' -Name IsReadOnly -Value $false -ErrorAction SilentlyContinue; "
        f"$bytes = [System.Convert]::FromBase64String('{b64_content}'); "
        f"[System.IO.File]::WriteAllBytes('{paths.HOSTS_PATH}', $bytes)"
    )
    encoded = base64.b64encode(ps_script.encode("utf-16le")).decode("ascii")
    exit_code = run_elevated(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded])
    if exit_code != 0:
        raise RuntimeError(f"Failed to update hosts file (exit code {exit_code})")
    return True


def create_vhost(domain: str, root: str | Path, php_version: str, ssl: bool = False,
                 auto_start_pool: bool = True) -> Path:
    """
    Creates an Nginx virtual host, ensures php-cgi pool is running, and maps to hosts file.
    """
    root_path = Path(root).resolve()
    if not root_path.exists():
        root_path.mkdir(parents=True, exist_ok=True)
    if not any(root_path.iterdir()):
        (root_path / "index.php").write_text(
            f"<?php\n"
            f"// Virtual host: {domain}\n"
            f"echo '<h1>Welcome to {domain}</h1>';\n"
            f"echo '<p>Served by Nginx & PHP {php_version} via ndev</p>';\n"
            f"phpinfo();\n",
            encoding="utf-8"
        )

    # Local import to avoid circular dependencies
    from . import php, services

    try:
        resolved_php = php.resolve_installed(php_version)
    except Exception:
        resolved_php = php_version

    if not fcgi.status(resolved_php):
        if not auto_start_pool:
            raise RuntimeError(
                f"PHP {resolved_php} pool is not running -- run "
                f"`ndev pool start {resolved_php}` first, or pass auto_start_pool=True"
            )
        cfg = paths.load_config()
        fcgi.start(resolved_php, php.php_cgi_exe(resolved_php),
                   cfg["fcgi_workers_per_version"], cfg["fcgi_base_port"])

    conf_path = write_vhost_conf(domain, root_path, resolved_php, ssl=ssl)
    add_hosts_entry(domain)

    # If Nginx is installed and running, reload it
    if (paths.NGINX_DIR / "nginx.exe").exists():
        try:
            services.nginx_reload()
        except Exception:
            pass

    return conf_path


def remove_vhost(domain: str) -> bool:
    """Remove a virtual host config and hosts file entry."""
    clean_domain = re.sub(r"^https?://", "", domain.strip().lower()).rstrip("/")
    conf_path = paths.NGINX_CONF_D / f"{clean_domain}.conf"
    cert_dir = paths.CERTS_DIR / clean_domain
    if not conf_path.exists() and not cert_dir.exists():
        return False

    removed = False
    if conf_path.exists():
        conf_path.unlink()
        removed = True
    remove_hosts_entry(clean_domain)

    # Clean up SSL cert directory if present
    if cert_dir.exists():
        import shutil
        try:
            shutil.rmtree(cert_dir)
        except Exception:
            pass

    # If Nginx is installed and running, reload it
    from . import services
    if (paths.NGINX_DIR / "nginx.exe").exists():
        try:
            services.nginx_reload()
        except Exception:
            pass

    return removed


def list_vhosts() -> list[dict]:
    """List all configured virtual hosts."""
    if not paths.NGINX_CONF_D.exists():
        return []
    vhosts = []
    for p in sorted(paths.NGINX_CONF_D.glob("*.conf")):
        if p.name.startswith("_"):
            continue
        domain = p.stem
        content = p.read_text(encoding="utf-8", errors="ignore")
        root_m = re.search(r'root\s+["\']?([^";\r\n]+?)["\']?;', content)
        root = root_m.group(1).strip() if root_m else "N/A"

        # Check explicit comment header first, then upstream pattern
        m_comment = re.search(r'#\s*ndev-php:\s*([\w.\-]+)', content)
        if m_comment:
            php_ver = m_comment.group(1)
        else:
            clean_domain = re.sub(r"[^a-zA-Z0-9_]", "_", domain.lower())
            m_up = re.search(rf'upstream\s+php_([\d_]+)_{clean_domain}\b', content) or re.search(r'upstream\s+php_([\d_]+)\b', content)
            php_ver = m_up.group(1).replace("_", ".") if m_up else "unknown"

        has_ssl = "listen 443 ssl" in content
        vhosts.append({
            "domain": domain,
            "root": root,
            "php": php_ver,
            "ssl": has_ssl,
            "conf": str(p),
        })
    return vhosts
