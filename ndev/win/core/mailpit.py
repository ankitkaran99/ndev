"""
Mailpit - local email sandbox & SMTP catcher (https://github.com/axllent/mailpit).

Downloads the prebuilt Windows binary from GitHub releases and manages the
background process on Windows.

SMTP server:  127.0.0.1:1025  (default)
Web UI:       http://127.0.0.1:8025  (default)
"""
from __future__ import annotations

import json
import shutil
import socket
import subprocess
import time
import zipfile
from pathlib import Path
from typing import Optional

import httpx

from . import fcgi, paths


# ── constants ────────────────────────────────────────────────────────────────

GITHUB_REPO       = "axllent/mailpit"
RELEASES_API_URL  = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_PAGE_URL = f"https://github.com/{GITHUB_REPO}/releases"

DEFAULT_SMTP_PORT = 1025
DEFAULT_WEB_PORT  = 8025

BINARY_NAME = "mailpit.exe"
BINARY_PATH = paths.SHIM_DIR / BINARY_NAME

_STATE_FILE = paths.RUN_DIR / "mailpit.json"

CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW         = 0x08000000


# ── helpers ──────────────────────────────────────────────────────────────────

def is_installed() -> bool:
    return BINARY_PATH.exists()


def binary() -> Path:
    if BINARY_PATH.exists():
        return BINARY_PATH
    raise FileNotFoundError(
        "Mailpit binary not found. Run `ndev mailpit install` first."
    )


def _fetch_latest_release() -> dict:
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ndev/0.1.0"}
    with httpx.Client(follow_redirects=True, timeout=20.0) as client:
        resp = client.get(RELEASES_API_URL, headers=headers)
        resp.raise_for_status()
        return resp.json()


def _find_windows_asset(release: dict) -> Optional[dict]:
    """Return the windows-amd64 asset, or None."""
    for asset in release.get("assets", []):
        name = asset["name"].lower()
        if "windows" in name and "amd64" in name:
            return asset
    return None


# ── core operations ──────────────────────────────────────────────────────────

def install() -> Path:
    """
    Download the prebuilt Mailpit Windows binary from GitHub releases
    and save it to ~/.ndev/shims/mailpit.exe.
    """
    paths.ensure_dirs()

    release = _fetch_latest_release()
    version = release.get("tag_name", "unknown")
    asset   = _find_windows_asset(release)

    if asset is None:
        raise RuntimeError(
            f"No prebuilt Windows binary found in Mailpit {version}.\n"
            f"Check {RELEASES_PAGE_URL} for available assets."
        )

    url     = asset["browser_download_url"]
    name    = asset["name"]
    dl_path = paths.DOWNLOADS_DIR / name

    # Download (skip if already cached)
    if not dl_path.exists() or dl_path.stat().st_size == 0:
        tmp = dl_path.with_suffix(".part")
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ndev/0.1.0"}
        with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(connect=15.0, read=45.0, write=15.0, pool=15.0)) as client:
            with client.stream("GET", url, headers=headers) as resp:
                resp.raise_for_status()
                with open(tmp, "wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=131072):
                        if chunk:
                            f.write(chunk)
        if tmp.exists() and tmp.stat().st_size > 0:
            if dl_path.exists():
                dl_path.unlink()
            tmp.rename(dl_path)


    # Extract .exe from zip
    with zipfile.ZipFile(dl_path) as zf:
        for member in zf.namelist():
            if member.lower().endswith(".exe") and "mailpit" in member.lower():
                with zf.open(member) as src, open(BINARY_PATH, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                break
        else:
            raise RuntimeError(f"Could not find mailpit.exe inside {name}")

    return BINARY_PATH


def start(
    smtp_port: int = DEFAULT_SMTP_PORT,
    web_port: int = DEFAULT_WEB_PORT,
) -> int:
    """Start Mailpit in the background. Returns PID."""
    exe = binary()

    st = status()
    if st:
        raise RuntimeError(
            f"Mailpit is already running at http://127.0.0.1:{st['web_port']} "
            f"(PID {st['pid']})"
        )

    for port, label in [(smtp_port, "SMTP"), (web_port, "Web UI")]:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                raise RuntimeError(
                    f"Port {port} ({label}) is already in use. "
                    "Choose a different port or stop the conflicting service."
                )

    db_path = paths.NDEV_HOME / "mailpit.db"
    cmd = [
        str(exe),
        "--smtp",     f"127.0.0.1:{smtp_port}",
        "--listen",   f"127.0.0.1:{web_port}",
        "--database", str(db_path),
    ]

    proc = subprocess.Popen(
        cmd,
        creationflags=CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW,
    )

    time.sleep(1.0)
    if proc.poll() is not None:
        raise RuntimeError(
            "Mailpit exited immediately after launch. "
            "Check for port conflicts or run `mailpit --help` manually."
        )

    paths.ensure_dirs()
    state = {
        "pid":       proc.pid,
        "smtp_port": smtp_port,
        "web_port":  web_port,
        "url":       f"http://127.0.0.1:{web_port}",
        "smtp":      f"127.0.0.1:{smtp_port}",
        "database":  str(db_path),
    }
    _STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return proc.pid


def stop() -> None:
    """Stop the running Mailpit process."""
    import ctypes
    if not _STATE_FILE.exists():
        return
    try:
        state = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        pid = state.get("pid")
        if pid and fcgi.is_pid_alive(pid):
            terminated = False
            try:
                handle = ctypes.windll.kernel32.OpenProcess(0x0001, False, pid)
                if handle:
                    ctypes.windll.kernel32.TerminateProcess(handle, 0)
                    ctypes.windll.kernel32.CloseHandle(handle)
                    terminated = True
            except Exception:
                pass
            if not terminated or fcgi.is_pid_alive(pid):
                subprocess.run(
                    ["taskkill.exe", "/F", "/PID", str(pid), "/T"],
                    capture_output=True,
                )
    except Exception:
        pass
    _STATE_FILE.unlink(missing_ok=True)


def status() -> dict | None:
    """Return the current state dict if Mailpit is running, else None."""
    if not _STATE_FILE.exists():
        return None
    try:
        state = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        pid = state.get("pid")
        if pid and fcgi.is_pid_alive(pid):
            return state
    except Exception:
        pass
    _STATE_FILE.unlink(missing_ok=True)
    return None


def restart(
    smtp_port: int = DEFAULT_SMTP_PORT,
    web_port: int = DEFAULT_WEB_PORT,
) -> int:
    """Stop (if running) then start Mailpit. Returns new PID."""
    stop()
    # Wait up to 3 s for the ports to be released
    for _ in range(6):
        ports_busy = False
        for p in (smtp_port, web_port):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.3)
                if s.connect_ex(("127.0.0.1", p)) == 0:
                    ports_busy = True
                    break
        if not ports_busy:
            break
        time.sleep(0.5)
    return start(smtp_port=smtp_port, web_port=web_port)

