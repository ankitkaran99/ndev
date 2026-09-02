"""
Central path/config definitions for ndev-win.

Mirrors the Linux ndev layout (~/.ndev/...) but rooted under the
user's profile directory on Windows.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

NDEV_HOME = Path(os.environ.get("NDEV_HOME", Path.home() / ".ndev"))

PHP_DIR = NDEV_HOME / "php"                 # ~/.ndev/php/<version>/
DOWNLOADS_DIR = NDEV_HOME / "downloads"     # cached zip downloads
RUN_DIR = NDEV_HOME / "run"                 # pid files / worker state
CERTS_DIR = NDEV_HOME / "certs"             # mkcert-generated certs
CACERT_PATH = CERTS_DIR / "cacert.pem"       # Mozilla root CA bundle for PHP cURL/OpenSSL
NGINX_DIR = NDEV_HOME / "nginx"             # native nginx install
NGINX_CONF_D = NGINX_DIR / "conf" / "ndev-vhosts"
NGINX_LOGS_DIR = NGINX_DIR / "logs"
MARIADB_DIR = NDEV_HOME / "mariadb"
PMA_DIR = NDEV_HOME / "pma"
TEMPLATES_DIR = NDEV_HOME / "templates"
CONFIG_FILE = NDEV_HOME / "config.json"
CURRENT_FILE = NDEV_HOME / "current"        # active PHP version, plain text
SHIM_DIR = NDEV_HOME / "shims"              # php.exe / php-cgi.exe shims for PATH
TEMP_DIR = NDEV_HOME / "temp"                # temporary files and fastcgi temp buffers
SESSIONS_DIR = TEMP_DIR / "sessions"         # PHP isolated session storage

HOSTS_PATH = Path(r"C:\Windows\System32\drivers\etc\hosts")

DEFAULT_CONFIG = {
    "fcgi_base_port": 9000,
    "fcgi_workers_per_version": 4,
    "ngrok_path": None,
    "mkcert_path": None,
}


def ensure_dirs() -> None:
    for d in (PHP_DIR, DOWNLOADS_DIR, RUN_DIR, CERTS_DIR, NGINX_CONF_D,
              NGINX_LOGS_DIR, MARIADB_DIR, PMA_DIR, TEMPLATES_DIR, SHIM_DIR,
              TEMP_DIR, SESSIONS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    ensure_dirs()
    if not CONFIG_FILE.exists():
        CONFIG_FILE.write_text(json.dumps(DEFAULT_CONFIG, indent=2), encoding="utf-8")
        return dict(DEFAULT_CONFIG)
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    merged = dict(DEFAULT_CONFIG)
    merged.update(data)
    return merged


def save_config(cfg: dict) -> None:
    ensure_dirs()
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def version_dir(version: str) -> Path:
    return PHP_DIR / version


def get_current_version() -> str | None:
    if CURRENT_FILE.exists():
        try:
            v = CURRENT_FILE.read_text(encoding="utf-8").strip()
            return v or None
        except Exception:
            return None
    return None


def set_current_version(version: str) -> None:
    ensure_dirs()
    CURRENT_FILE.write_text(version, encoding="utf-8")
