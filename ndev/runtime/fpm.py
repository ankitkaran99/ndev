import time
import signal
from pathlib import Path
import subprocess
from ndev.constants import PHP_DIR
from ndev.logger import logger
from ndev.runtime.process import is_pid_running, read_pid_file, kill_process
from ndev.runtime.sockets import get_pid_path, get_socket_path

def get_fpm_binary(version: str) -> Path:
    """Get the path to php-fpm binary for a version."""
    prefix = PHP_DIR / version
    return prefix / "sbin" / "php-fpm"

def start_fpm(version: str):
    """Start PHP-FPM daemon for a version."""
    pid_file = get_pid_path(version)
    pid = read_pid_file(pid_file)
    
    if pid and is_pid_running(pid):
        logger.info(f"PHP-FPM {version} is already running with PID {pid}.")
        return
        
    fpm_bin = get_fpm_binary(version)
    if not fpm_bin.exists():
        raise FileNotFoundError(f"PHP-FPM binary not found at {fpm_bin} for version {version}")
        
    prefix = PHP_DIR / version
    conf_file = prefix / "etc" / "php-fpm.conf"
    ini_file = prefix / "etc" / "php.ini"
    
    cmd = [
        str(fpm_bin),
        "-y", str(conf_file),
        "-c", str(ini_file)
    ]
    
    logger.info(f"Starting PHP-FPM {version}...")
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"Failed to start PHP-FPM {version}: {res.stderr or res.stdout}")
        
    for _ in range(10):
        time.sleep(0.2)
        pid = read_pid_file(pid_file)
        if pid and is_pid_running(pid):
            logger.info(f"PHP-FPM {version} started successfully (PID {pid}).")
            return
            
    logger.warning(f"PHP-FPM {version} launched, but PID file could not be verified.")

def stop_fpm(version: str):
    """Stop PHP-FPM daemon for a version."""
    pid_file = get_pid_path(version)
    pid = read_pid_file(pid_file)
    
    if not pid or not is_pid_running(pid):
        logger.info(f"PHP-FPM {version} is not running.")
        if pid_file.exists():
            pid_file.unlink()
        return
        
    logger.info(f"Stopping PHP-FPM {version} (PID {pid})...")
    kill_process(pid, signal.SIGTERM)
    
    for _ in range(20):
        time.sleep(0.2)
        if not is_pid_running(pid):
            logger.info(f"PHP-FPM {version} stopped.")
            if pid_file.exists():
                pid_file.unlink()
            sock_file = get_socket_path(version)
            if sock_file.exists():
                sock_file.unlink()
            return
            
    logger.warning("FPM process did not exit. Force killing...")
    kill_process(pid, signal.SIGKILL)
    if pid_file.exists():
        pid_file.unlink()
    sock_file = get_socket_path(version)
    if sock_file.exists():
        sock_file.unlink()

def reload_fpm(version: str):
    """Gracefully reload PHP-FPM daemon (SIGUSR2)."""
    pid_file = get_pid_path(version)
    pid = read_pid_file(pid_file)
    
    if not pid or not is_pid_running(pid):
        logger.warning(f"PHP-FPM {version} is not running. Starting it instead...")
        start_fpm(version)
        return
        
    logger.info(f"Reloading PHP-FPM {version} (PID {pid})...")
    kill_process(pid, signal.SIGUSR2)
    logger.info("SIGUSR2 reload signal sent.")

def restart_fpm(version: str):
    """Restart PHP-FPM daemon."""
    stop_fpm(version)
    start_fpm(version)

def get_fpm_status(version: str) -> dict:
    """Get the status of PHP-FPM for a version."""
    pid_file = get_pid_path(version)
    pid = read_pid_file(pid_file)
    running = is_pid_running(pid) if pid else False
    socket_path = get_socket_path(version)
    
    return {
        "version": version,
        "pid": pid if running else None,
        "running": running,
        "socket": str(socket_path) if socket_path.exists() else str(socket_path),
        "socket_exists": socket_path.exists()
    }
