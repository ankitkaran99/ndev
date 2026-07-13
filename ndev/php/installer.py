from pathlib import Path
from ndev.php.resolver import resolve_version
from ndev.php.downloader import download_php_source
from ndev.php.builder import build_php
from ndev.php.templates import write_default_configs
from ndev.chroot.packages import install_host_packages
from ndev.logger import logger

def install_version(version_input: str, show_logs: bool = False) -> str:
    """Resolve, download, build and configure a PHP version."""
    resolved_version, filename, sha256, download_url = resolve_version(version_input)
    
    archive_path = download_php_source(filename, sha256, download_url)
    
    # Pre-install development dependencies inside sandbox
    install_host_packages([
        "libsqlite3-dev",
        "libonig-dev",
        "libcrypt-dev",
        "libcurl4-openssl-dev",
        "libxml2-dev",
        "libssl-dev",
        "libzip-dev",
        "libicu-dev",
        "libsodium-dev",
        "libpng-dev",
        "libjpeg-dev",
        "libwebp-dev",
        "libfreetype-dev",
        "libbz2-dev",
        "libgmp-dev",
        "libreadline-dev",
        "zlib1g-dev"
    ], show_logs=show_logs)
    
    install_prefix = build_php(resolved_version, archive_path, show_logs=show_logs)
    
    write_default_configs(install_prefix, resolved_version)
    
    logger.info(f"Successfully finished installation of PHP version {resolved_version}")
    return resolved_version
