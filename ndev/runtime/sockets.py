from pathlib import Path
from ndev.constants import RUN_DIR

def get_major_minor(version: str) -> str:
    parts = version.split(".")
    return f"{parts[0]}{parts[1]}"

def get_socket_path(version: str) -> Path:
    """Return the UNIX socket path for a PHP version."""
    mm = get_major_minor(version)
    return RUN_DIR / f"php{mm}.sock"

def get_pid_path(version: str) -> Path:
    """Return the PID file path for a PHP-FPM daemon version."""
    mm = get_major_minor(version)
    return RUN_DIR / f"php-fpm-{mm}.pid"
