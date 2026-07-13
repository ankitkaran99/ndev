import os
from pathlib import Path

NDEV_DIR = Path(os.path.expanduser("~/.ndev")).resolve()
CACHE_DIR = NDEV_DIR / "cache"
DOWNLOADS_DIR = NDEV_DIR / "downloads"
BUILDS_DIR = NDEV_DIR / "builds"
CHROOT_DIR = NDEV_DIR / "chroot"
LOGS_DIR = NDEV_DIR / "logs"
RUN_DIR = NDEV_DIR / "run"
PHP_DIR = NDEV_DIR / "php"
CERTS_DIR = NDEV_DIR / "certs"
CURRENT_LINK = NDEV_DIR / "current"
CONFIG_FILE = NDEV_DIR / "config.toml"

DEFAULT_CONFIG = """# ndev Configuration

[general]
default_version = ""

[build]
configure_flags = [
    "--enable-fpm",
    "--enable-mbstring",
    "--enable-xml",
    "--with-openssl",
    "--with-zlib",
    "--enable-pdo",
    "--with-pdo-mysql",
    "--with-mysqli"
]
"""
