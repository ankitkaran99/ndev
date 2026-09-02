"""
Mailpit management for Linux ndev.
Downloads prebuilt Linux amd64/arm64 binaries from GitHub releases and manages
the background daemon.
"""
import os
import platform
import shutil
import socket
import subprocess
import tarfile
import time
import webbrowser
import httpx
from pathlib import Path
from rich.console import Console
from rich.progress import Progress, TextColumn, BarColumn, DownloadColumn, TransferSpeedColumn, TimeRemainingColumn, SpinnerColumn

from ndev.constants import NDEV_DIR, RUN_DIR, LOGS_DIR
from ndev.logger import logger
from ndev.runtime.process import is_pid_running, read_pid_file, kill_process

console = Console()

GITHUB_REPO = "axllent/mailpit"
RELEASES_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

BIN_DIR = NDEV_DIR / "bin"
MAILPIT_BIN = BIN_DIR / "mailpit"
MAILPIT_PID_FILE = RUN_DIR / "mailpit.pid"
MAILPIT_PORT_FILE = RUN_DIR / "mailpit.port"
MAILPIT_LOG_FILE = LOGS_DIR / "mailpit.log"
MAILPIT_DB_FILE = NDEV_DIR / "mailpit.db"

DEFAULT_SMTP_PORT = 1025
DEFAULT_WEB_PORT = 8025


def is_installed() -> bool:
    """Check if mailpit binary is present."""
    return MAILPIT_BIN.exists() or bool(shutil.which("mailpit"))


def get_binary_path() -> Path:
    if MAILPIT_BIN.exists():
        return MAILPIT_BIN
    system_bin = shutil.which("mailpit")
    if system_bin:
        return Path(system_bin)
    raise FileNotFoundError("Mailpit binary not found. Run `ndev mailpit install` first.")


def _get_arch_asset_name() -> str:
    machine = platform.machine().lower()
    if machine in ["x86_64", "amd64"]:
        return "mailpit-linux-amd64.tar.gz"
    elif machine in ["aarch64", "arm64"]:
        return "mailpit-linux-arm64.tar.gz"
    elif machine in ["i386", "i686"]:
        return "mailpit-linux-386.tar.gz"
    elif "arm" in machine:
        return "mailpit-linux-arm.tar.gz"
    return "mailpit-linux-amd64.tar.gz"


def setup_mailpit():
    """Download and set up prebuilt Mailpit binary if missing."""
    if is_installed():
        return

    console.print("[bold yellow]Mailpit is not installed. Downloading prebuilt binary...[/bold yellow]")
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    temp_dir = NDEV_DIR / "mailpit_temp"
    tar_path = NDEV_DIR / "mailpit.tar.gz"

    try:
        # Fetch release metadata
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(RELEASES_API_URL, headers={"User-Agent": "ndev/0.1.0"})
            if resp.status_code != 200:
                raise RuntimeError(f"Failed to fetch Mailpit releases. HTTP {resp.status_code}")
            release_data = resp.json()

        target_asset = _get_arch_asset_name()
        download_url = None
        for asset in release_data.get("assets", []):
            if asset.get("name") == target_asset:
                download_url = asset.get("browser_download_url")
                break

        if not download_url:
            raise RuntimeError(f"Could not find asset '{target_asset}' in Mailpit {release_data.get('tag_name')}")

        # Download tarball
        with tar_path.open("wb") as f:
            with httpx.stream("GET", download_url, follow_redirects=True, timeout=60.0) as r:
                if r.status_code != 200:
                    raise RuntimeError(f"Failed to download Mailpit: HTTP {r.status_code}")
                total = int(r.headers.get("Content-Length", 0))
                with Progress(
                    TextColumn("[bold blue]{task.description}"),
                    BarColumn(),
                    DownloadColumn(),
                    TransferSpeedColumn(),
                    TimeRemainingColumn(),
                    console=console,
                ) as progress:
                    task = progress.add_task("Downloading Mailpit...", total=total)
                    for chunk in r.iter_bytes(chunk_size=16384):
                        f.write(chunk)
                        progress.update(task, advance=len(chunk))

        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        temp_dir.mkdir(parents=True, exist_ok=True)

        with tarfile.open(tar_path, "r:gz") as tf:
            tf.extractall(temp_dir)

        extracted_bin = temp_dir / "mailpit"
        if not extracted_bin.exists():
            raise RuntimeError("mailpit binary not found in archive")

        shutil.move(str(extracted_bin), str(MAILPIT_BIN))
        MAILPIT_BIN.chmod(0o755)
        console.print("[bold green]Mailpit installed successfully![/bold green]\n")

    except Exception as e:
        logger.error(f"Failed to install Mailpit: {e}")
        if MAILPIT_BIN.exists():
            MAILPIT_BIN.unlink()
        raise RuntimeError(f"Mailpit setup failed: {e}")
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        if tar_path.exists():
            tar_path.unlink()


def start_mailpit(smtp_port: int = DEFAULT_SMTP_PORT, web_port: int = DEFAULT_WEB_PORT):
    """Start Mailpit background service."""
    pid = read_pid_file(MAILPIT_PID_FILE)
    if pid and is_pid_running(pid):
        existing_port = MAILPIT_PORT_FILE.read_text().strip() if MAILPIT_PORT_FILE.exists() else str(DEFAULT_WEB_PORT)
        logger.info(f"Mailpit service is already running (PID {pid}, Web UI http://127.0.0.1:{existing_port}).")
        return

    setup_mailpit()
    bin_path = get_binary_path()

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    RUN_DIR.mkdir(parents=True, exist_ok=True)

    log_fd = open(MAILPIT_LOG_FILE, "a")

    cmd = [
        str(bin_path),
        "--smtp", f"127.0.0.1:{smtp_port}",
        "--listen", f"127.0.0.1:{web_port}",
        "--database", str(MAILPIT_DB_FILE),
    ]

    proc = subprocess.Popen(
        cmd,
        stdout=log_fd,
        stderr=log_fd,
        start_new_session=True,
    )

    time.sleep(0.5)
    if proc.poll() is not None:
        raise RuntimeError(f"Mailpit exited immediately. Check {MAILPIT_LOG_FILE} for details.")

    MAILPIT_PID_FILE.write_text(str(proc.pid))
    MAILPIT_PORT_FILE.write_text(f"{smtp_port}:{web_port}")

    logger.info(f"Mailpit service started on http://127.0.0.1:{web_port} (SMTP: 127.0.0.1:{smtp_port}, PID {proc.pid})")


def stop_mailpit():
    """Stop Mailpit service."""
    pid = read_pid_file(MAILPIT_PID_FILE)
    if not pid or not is_pid_running(pid):
        logger.info("Mailpit service is not running.")
        if MAILPIT_PID_FILE.exists():
            MAILPIT_PID_FILE.unlink()
        return

    logger.info(f"Stopping Mailpit service (PID {pid})...")
    kill_process(pid)
    if MAILPIT_PID_FILE.exists():
        MAILPIT_PID_FILE.unlink()
    logger.info("Mailpit service stopped.")


def restart_mailpit(smtp_port: int = DEFAULT_SMTP_PORT, web_port: int = DEFAULT_WEB_PORT):
    """Restart Mailpit service."""
    stop_mailpit()
    time.sleep(0.5)
    start_mailpit(smtp_port=smtp_port, web_port=web_port)


def get_mailpit_status() -> dict:
    """Get status details for Mailpit service."""
    pid = read_pid_file(MAILPIT_PID_FILE)
    running = is_pid_running(pid) if pid else False
    smtp_port = DEFAULT_SMTP_PORT
    web_port = DEFAULT_WEB_PORT

    if MAILPIT_PORT_FILE.exists():
        try:
            val = MAILPIT_PORT_FILE.read_text().strip()
            if ":" in val:
                s, w = val.split(":", 1)
                smtp_port = int(s)
                web_port = int(w)
            else:
                web_port = int(val)
        except Exception:
            pass

    installed = is_installed()

    return {
        "service": "mailpit",
        "running": running,
        "pid": pid if running else None,
        "smtp_port": smtp_port,
        "web_port": web_port,
        "url": f"http://127.0.0.1:{web_port}" if running else None,
        "smtp": f"127.0.0.1:{smtp_port}",
        "installed": installed,
    }


def launch_mailpit():
    """Open Mailpit web UI in default browser, starting it if stopped."""
    status = get_mailpit_status()
    if not status["running"]:
        start_mailpit()
        status = get_mailpit_status()
    url = status["url"] or f"http://127.0.0.1:{DEFAULT_WEB_PORT}"
    console.print(f"Opening [bold cyan]{url}[/bold cyan] in default browser...")
    webbrowser.open(url)
