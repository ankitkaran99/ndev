"""
mkcert wrapper for local SSL certificates on Windows.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from . import paths

_CA_INSTALLED_MARKER = paths.NDEV_HOME / ".mkcert-ca-installed"


def _mkcert_path() -> str:
    # 1. Check shim dir
    shim_exe = paths.SHIM_DIR / "mkcert.exe"
    if shim_exe.exists():
        return str(shim_exe)

    # 2. Check config
    cfg = paths.load_config()
    path = cfg.get("mkcert_path")
    if path and Path(path).exists():
        return str(path)

    # 3. Check system PATH
    which_path = shutil.which("mkcert") or shutil.which("mkcert.exe")
    if which_path:
        return which_path

    raise FileNotFoundError("mkcert isn't installed -- run `ndev setup` first")


def is_ca_installed() -> bool:
    return _CA_INSTALLED_MARKER.exists()


def ensure_ca_installed() -> None:
    if _CA_INSTALLED_MARKER.exists():
        return
    subprocess.run([_mkcert_path(), "-install"], check=True)
    paths.ensure_dirs()
    _CA_INSTALLED_MARKER.write_text("ok", encoding="utf-8")


def generate_cert(domain: str) -> tuple[str, str]:
    """
    Generates <domain>.crt and <domain>.key under ~/.ndev/certs/<domain>/.
    Returns (cert_path, key_path) as strings with forward slashes for Nginx.
    """
    import re
    clean_domain = re.sub(r"^https?://", "", domain.strip().lower()).rstrip("/")
    ensure_ca_installed()
    cert_dir = paths.CERTS_DIR / clean_domain
    cert_dir.mkdir(parents=True, exist_ok=True)
    cert_path = cert_dir / f"{clean_domain}.crt"
    key_path = cert_dir / f"{clean_domain}.key"

    if not (cert_path.exists() and key_path.exists()):
        subprocess.run(
            [_mkcert_path(), "-cert-file", str(cert_path), "-key-file", str(key_path), clean_domain, f"*.{clean_domain}"],
            check=True,
        )
    return str(cert_path).replace("\\", "/"), str(key_path).replace("\\", "/")
