"""
Redis in-memory database management on Windows.

Downloads precompiled Redis for Windows (redis-windows / tporadowski) and manages
the background server process (redis-server.exe), status checking, and port tracking.

Default Port: 6379
"""
from __future__ import annotations

import json
import shutil
import socket
import subprocess
import time
import zipfile
from pathlib import Path

from . import fcgi, paths, setup as setup_core

DEFAULT_PORT = 6379
DEFAULT_VERSION = "8.10.1"
FALLBACK_VERSION = "5.0.14.1"

REDIS_DIR = paths.REDIS_DIR
_STATE_FILE = paths.RUN_DIR / "redis.json"

CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000


def server_exe() -> Path:
    return REDIS_DIR / "redis-server.exe"


def cli_exe() -> Path:
    return REDIS_DIR / "redis-cli.exe"


def is_installed() -> bool:
    return server_exe().exists()


def install(version: str = DEFAULT_VERSION) -> Path:
    """
    Download and install precompiled Redis for Windows into ~/.ndev/redis/
    and link redis-cli.exe to ~/.ndev/shims/.
    """
    paths.ensure_dirs()
    
    # Try redis-windows v8.x first, then tporadowski v5.x fallback
    urls = [
        f"https://github.com/redis-windows/redis-windows/releases/download/{version}/Redis-{version}-Windows-x64-cygwin.zip",
        f"https://github.com/tporadowski/redis/releases/download/v{FALLBACK_VERSION}/Redis-x64-{FALLBACK_VERSION}.zip",
    ]

    dl_path = paths.DOWNLOADS_DIR / f"redis-{version}.zip"
    if not dl_path.exists() or dl_path.stat().st_size == 0:
        downloaded = False
        last_err = None
        for url in urls:
            try:
                setup_core._download(url, dl_path)
                downloaded = True
                break
            except Exception as e:
                last_err = e
                continue
        if not downloaded:
            raise RuntimeError(f"Failed to download Redis for Windows: {last_err}")

    # Extract to ~/.ndev/redis/
    extract_tmp = paths.DOWNLOADS_DIR / "_extract_redis"
    if extract_tmp.exists():
        shutil.rmtree(extract_tmp)

    with zipfile.ZipFile(dl_path) as zf:
        zf.extractall(extract_tmp)

    REDIS_DIR.mkdir(parents=True, exist_ok=True)
    
    # Handle both nested folder structure and flat zip archives
    inner_dirs = [d for d in extract_tmp.iterdir() if d.is_dir()]
    source_dir = inner_dirs[0] if (len(inner_dirs) == 1 and not [f for f in extract_tmp.iterdir() if f.is_file()]) else extract_tmp

    for item in source_dir.iterdir():
        dest = REDIS_DIR / item.name
        if item.is_dir():
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(item, dest)
        else:
            shutil.copy2(item, dest)

    shutil.rmtree(extract_tmp, ignore_errors=True)

    # Ensure default redis.conf exists
    conf_path = REDIS_DIR / "redis.conf"
    if not conf_path.exists():
        conf_path.write_text(
            f"bind 127.0.0.1\nport {DEFAULT_PORT}\ntimeout 0\nappendonly yes\n",
            encoding="utf-8"
        )

    # Place redis-cli shim in ~/.ndev/shims/
    if (REDIS_DIR / "redis-cli.exe").exists():
        shim_cli = paths.SHIM_DIR / "redis-cli.exe"
        try:
            shutil.copy2(REDIS_DIR / "redis-cli.exe", shim_cli)
        except Exception:
            pass

    return REDIS_DIR


def start(port: int = DEFAULT_PORT) -> int:
    """Start Redis server in background. Returns process PID."""
    exe = server_exe()
    if not exe.exists():
        install()

    st = status()
    if st and st.get("running"):
        return st["pid"]

    # Check port availability
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        if s.connect_ex(("127.0.0.1", port)) == 0:
            raise RuntimeError(f"Port {port} is already in use by another application.")

    conf = REDIS_DIR / "redis.conf"
    if not conf.exists():
        conf = REDIS_DIR / "redis.windows.conf"

    cmd = [str(exe)]
    if conf.exists():
        # Pass filename relative to cwd (REDIS_DIR) so cygwin runtime resolves it cleanly
        cmd.append(conf.name)
    cmd.extend(["--port", str(port)])

    proc = subprocess.Popen(
        cmd,
        cwd=str(REDIS_DIR),
        creationflags=CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW,
    )


    paths.ensure_dirs()
    _STATE_FILE.write_text(
        json.dumps({"pid": proc.pid, "running": True, "port": port}),
        encoding="utf-8"
    )

    # Wait for Redis port
    deadline = time.time() + 3.0
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.1)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                break
        time.sleep(0.05)

    return proc.pid


def stop() -> None:
    """Gracefully stop Redis server."""
    cli = cli_exe()
    st = status()
    port = st["port"] if st and "port" in st else DEFAULT_PORT

    if cli.exists():
        try:
            subprocess.run([str(cli), "-p", str(port), "shutdown"], capture_output=True, timeout=5)
        except Exception:
            pass

    if st and st.get("pid"):
        pid = st["pid"]
        try:
            subprocess.run(["taskkill.exe", "/F", "/PID", str(pid), "/T"], capture_output=True)
        except Exception:
            pass

    _STATE_FILE.unlink(missing_ok=True)


def restart(port: int = DEFAULT_PORT) -> int:
    stop()
    time.sleep(0.3)
    return start(port=port)


def status() -> dict | None:
    """Return dict with running status and PID, or None."""
    if not _STATE_FILE.exists():
        return None
    try:
        data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        pid = data.get("pid")
        if pid and fcgi.is_pid_alive(pid, expected_name="redis"):
            data["running"] = True
            return data
    except Exception:
        pass
    _STATE_FILE.unlink(missing_ok=True)
    return None

