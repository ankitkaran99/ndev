import os
import shutil
import socket
import subprocess
import zipfile
import secrets
import httpx
from pathlib import Path
from rich.console import Console
from rich.progress import Progress, TextColumn, BarColumn, DownloadColumn, TransferSpeedColumn, TimeRemainingColumn, SpinnerColumn
from ndev.constants import NDEV_DIR, CURRENT_LINK, RUN_DIR, LOGS_DIR
from ndev.logger import logger
from ndev.runtime.process import is_pid_running, read_pid_file, kill_process

PMA_DIR = NDEV_DIR / "pma"
# Backward compatibility migration for legacy phpmyadmin directory
if not PMA_DIR.exists() and (NDEV_DIR / "phpmyadmin").exists():
    try:
        (NDEV_DIR / "phpmyadmin").rename(PMA_DIR)
    except Exception:
        PMA_DIR = NDEV_DIR / "phpmyadmin"

PMA_PID_FILE = RUN_DIR / "pma.pid"
PMA_PORT_FILE = RUN_DIR / "pma.port"
PMA_LOG_FILE = LOGS_DIR / "pma.log"

def download_file(url: str, dest_path: Path):
    with dest_path.open("wb") as f:
        with httpx.stream("GET", url, follow_redirects=True) as r:
            if r.status_code != 200:
                raise RuntimeError(f"Failed to download phpMyAdmin. HTTP Status Code: {r.status_code}")
                
            total = int(r.headers.get("Content-Length", 0))
            
            with Progress(
                TextColumn("[bold blue]{task.description}"),
                BarColumn(),
                DownloadColumn(),
                TransferSpeedColumn(),
                TimeRemainingColumn(),
                console=console
            ) as progress:
                task = progress.add_task("Downloading phpMyAdmin...", total=total)
                for chunk in r.iter_bytes(chunk_size=16384):
                    f.write(chunk)
                    progress.update(task, advance=len(chunk))

def extract_zip(zip_path: Path, extract_dir: Path):
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        console=console
    ) as progress:
        task = progress.add_task("Extracting phpMyAdmin...", total=None)
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(extract_dir)

def find_free_port(start_port=8080) -> int:
    port = start_port
    while port < 65535:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except socket.error:
                port += 1
    raise RuntimeError("No free ports found.")

def setup_pma():
    """Download and set up phpMyAdmin if not already setup."""
    if PMA_DIR.exists() and (PMA_DIR / "index.php").exists():
        return
        
    console.print("[bold yellow]phpMyAdmin is not set up. Installing now...[/bold yellow]")
    temp_dir = NDEV_DIR / "pma_temp"
    zip_path = NDEV_DIR / "phpmyadmin.zip"
    
    try:
        download_file("https://www.phpmyadmin.net/downloads/phpMyAdmin-latest-all-languages.zip", zip_path)
        
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        temp_dir.mkdir(parents=True, exist_ok=True)
        
        extract_zip(zip_path, temp_dir)
        
        subfolders = list(temp_dir.glob("phpMyAdmin-*"))
        if not subfolders:
            raise RuntimeError("Could not find extracted phpMyAdmin folder inside zip.")
        src_folder = subfolders[0]
        
        if PMA_DIR.exists():
            shutil.rmtree(PMA_DIR)
        PMA_DIR.mkdir(parents=True, exist_ok=True)
        
        for item in src_folder.iterdir():
            shutil.move(str(item), str(PMA_DIR / item.name))
            
        config_path = PMA_DIR / "config.inc.php"
        blowfish_secret = secrets.token_hex(16)
        config_content = f"""<?php
$cfg['blowfish_secret'] = '{blowfish_secret}';
$i = 0;
$i++;
$cfg['Servers'][$i]['auth_type'] = 'cookie';
$cfg['Servers'][$i]['host'] = '127.0.0.1';
$cfg['Servers'][$i]['compress'] = false;
$cfg['Servers'][$i]['AllowNoPassword'] = true;
"""
        config_path.write_text(config_content)
        console.print("[bold green]phpMyAdmin setup completed successfully![/bold green]\n")
    except Exception as e:
        logger.error(f"Failed to set up phpMyAdmin: {e}")
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        if zip_path.exists():
            zip_path.unlink()
        if PMA_DIR.exists():
            shutil.rmtree(PMA_DIR)
        raise RuntimeError(f"phpMyAdmin setup failed: {e}")
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        if zip_path.exists():
            zip_path.unlink()

def start_pma(port: int = None):
    """Start phpMyAdmin service in background."""
    pid = read_pid_file(PMA_PID_FILE)
    if pid and is_pid_running(pid):
        existing_port = None
        if PMA_PORT_FILE.exists():
            existing_port = PMA_PORT_FILE.read_text().strip()
        logger.info(f"phpMyAdmin service is already running (PID {pid}, Port {existing_port or 'unknown'}).")
        return
        
    php_path = CURRENT_LINK / "bin" / "php"
    if not php_path.exists():
        system_php = shutil.which("php")
        if system_php:
            php_path = Path(system_php)
        else:
            raise RuntimeError("No active PHP version found. Please run `ndev use <version>` or install PHP first.")
            
    setup_pma()
    
    if not port:
        if PMA_PORT_FILE.exists():
            try:
                cached_port = int(PMA_PORT_FILE.read_text().strip())
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.bind(("127.0.0.1", cached_port))
                    port = cached_port
            except Exception:
                port = None
        if not port:
            port = find_free_port(8080)
            
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    
    log_fd = open(PMA_LOG_FILE, "a")
    
    cmd = [
        str(php_path),
        "-S", f"127.0.0.1:{port}",
        "-t", str(PMA_DIR)
    ]
    
    proc = subprocess.Popen(
        cmd,
        cwd=PMA_DIR,
        stdout=log_fd,
        stderr=log_fd,
        start_new_session=True
    )
    
    PMA_PID_FILE.write_text(str(proc.pid))
    PMA_PORT_FILE.write_text(str(port))
    
    logger.info(f"phpMyAdmin service started on http://127.0.0.1:{port} (PID {proc.pid})")

def stop_pma():
    """Stop phpMyAdmin service."""
    pid = read_pid_file(PMA_PID_FILE)
    if not pid or not is_pid_running(pid):
        logger.info("phpMyAdmin service is not running.")
        if PMA_PID_FILE.exists():
            PMA_PID_FILE.unlink()
        return
        
    logger.info(f"Stopping phpMyAdmin service (PID {pid})...")
    kill_process(pid)
    if PMA_PID_FILE.exists():
        PMA_PID_FILE.unlink()
    logger.info("phpMyAdmin service stopped.")

def restart_pma(port: int = None):
    """Restart phpMyAdmin service."""
    stop_pma()
    start_pma(port=port)

def get_pma_status() -> dict:
    """Get status details for phpMyAdmin service."""
    pid = read_pid_file(PMA_PID_FILE)
    running = is_pid_running(pid) if pid else False
    port = None
    if PMA_PORT_FILE.exists():
        try:
            port = int(PMA_PORT_FILE.read_text().strip())
        except Exception:
            pass
            
    installed = PMA_DIR.exists() and (PMA_DIR / "index.php").exists()
    
    return {
        "service": "pma",
        "running": running,
        "pid": pid if running else None,
        "port": port,
        "url": f"http://127.0.0.1:{port}" if port and running else None,
        "installed": installed
    }
