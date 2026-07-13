import os
import tomllib
from pathlib import Path
from ndev.constants import (
    NDEV_DIR, CACHE_DIR, DOWNLOADS_DIR, BUILDS_DIR, CHROOT_DIR,
    LOGS_DIR, RUN_DIR, PHP_DIR, CERTS_DIR, CONFIG_FILE, DEFAULT_CONFIG
)
from ndev.logger import logger

def init_layout():
    """Create all required directories in ~/.ndev if they do not exist."""
    for directory in [NDEV_DIR, CACHE_DIR, DOWNLOADS_DIR, BUILDS_DIR, CHROOT_DIR, LOGS_DIR, RUN_DIR, PHP_DIR, CERTS_DIR]:
        directory.mkdir(parents=True, exist_ok=True)
    
    if not CONFIG_FILE.exists():
        CONFIG_FILE.write_text(DEFAULT_CONFIG)
        logger.info(f"Initialized default configuration in {CONFIG_FILE}")
    else:
        try:
            content = CONFIG_FILE.read_text()
            new_flags = [
                "--enable-fpm",
                "--enable-mbstring",
                "--enable-xml",
                "--with-openssl",
                "--with-zlib",
                "--enable-pdo",
                "--with-pdo-mysql",
                "--with-mysqli",
                "--with-curl",
                "--enable-bcmath",
                "--enable-calendar",
                "--enable-exif",
                "--enable-ftp",
                "--enable-intl",
                "--enable-pcntl",
                "--enable-sockets",
                "--enable-opcache",
                "--enable-soap",
                "--enable-gd",
                "--with-jpeg",
                "--with-webp",
                "--with-freetype",
                "--with-zip",
                "--with-sodium",
                "--with-bz2",
                "--with-gmp",
                "--with-readline"
            ]
            missing_flags = [f for f in new_flags if f not in content]
            if "configure_flags" in content and missing_flags:
                with open(CONFIG_FILE, "rb") as f:
                    config = tomllib.load(f)
                build_sec = config.setdefault("build", {})
                flags = build_sec.setdefault("configure_flags", [])
                
                updated = False
                for flag in new_flags:
                    if flag not in flags:
                        flags.append(flag)
                        updated = True
                
                if updated:
                    lines = []
                    for section, s_content in config.items():
                        lines.append(f"[{section}]")
                        for k, v in s_content.items():
                            if isinstance(v, list):
                                v_str = "[" + ", ".join(f'"{item}"' for item in v) + "]"
                            elif isinstance(v, str):
                                v_str = f'"{v}"'
                            else:
                                v_str = str(v)
                            lines.append(f"{k} = {v_str}")
                        lines.append("")
                    CONFIG_FILE.write_text("\n".join(lines))
                    logger.info("Automatically added missing build flags to existing configuration flags.")
        except Exception as e:
            logger.warning(f"Failed to migrate configuration file: {e}")

def load_config():
    """Load configuration from ~/.ndev/config.toml."""
    init_layout()
    try:
        with open(CONFIG_FILE, "rb") as f:
            return tomllib.load(f)
    except Exception as e:
        logger.warning(f"Failed to load configuration: {e}. Using defaults.")
        return tomllib.loads(DEFAULT_CONFIG)

def update_config(key_path: str, value):
    """Simple configuration updater. key_path is dot-separated (e.g. 'general.default_version')."""
    config = load_config()
    
    keys = key_path.split(".")
    d = config
    for k in keys[:-1]:
        d = d.setdefault(k, {})
    d[keys[-1]] = value
    
    lines = []
    for section, content in config.items():
        lines.append(f"[{section}]")
        for k, v in content.items():
            if isinstance(v, list):
                v_str = "[" + ", ".join(f'"{item}"' for item in v) + "]"
            elif isinstance(v, str):
                v_str = f'"{v}"'
            else:
                v_str = str(v)
            lines.append(f"{k} = {v_str}")
        lines.append("")
    
    CONFIG_FILE.write_text("\n".join(lines))
