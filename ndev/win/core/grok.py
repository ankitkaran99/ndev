"""
ngrok tunnel wrapper for ndev-win virtual hosts.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from . import paths, vhost

HTTP_PORT = 80
HTTPS_PORT = 443


def list_vhosts() -> list[str]:
    """Return list of domain names with configured Nginx virtual hosts."""
    return [v["domain"] for v in vhost.list_vhosts()]


def _ngrok_exe() -> str:
    # 1. Check shim dir
    shim_exe = paths.SHIM_DIR / "ngrok.exe"
    if shim_exe.exists():
        return str(shim_exe)

    # 2. Check config
    cfg = paths.load_config()
    path = cfg.get("ngrok_path")
    if path and Path(path).exists():
        return str(path)

    # 3. Check system PATH
    which_path = shutil.which("ngrok") or shutil.which("ngrok.exe")
    if which_path:
        return which_path

    raise FileNotFoundError("ngrok isn't installed -- run `ndev setup` first")


def start_tunnel(domain: str, ssl: bool = False) -> subprocess.Popen:
    """
    Start `ngrok http` against Nginx, rewriting Host header to `domain`.
    """
    import re
    clean_domain = re.sub(r"^https?://", "", domain.strip().lower()).rstrip("/")
    known = list_vhosts()
    if clean_domain not in known:
        raise FileNotFoundError(
            f"No vhost found for '{clean_domain}'. Known vhosts: {known or '(none)'}"
        )
    target = f"https://localhost:{HTTPS_PORT}" if ssl else str(HTTP_PORT)
    cmd = [_ngrok_exe(), "http", target, f"--host-header={clean_domain}"]
    return subprocess.Popen(cmd)
