"""
Process and service control for Nginx and MariaDB.
"""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
from pathlib import Path
from typing import Optional

from . import fcgi, paths

CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000
PROCESS_TERMINATE = 0x0001


# ---- Nginx ------------------------------------------------------------------

def nginx_exe() -> Path:
    return paths.NGINX_DIR / "nginx.exe"


def nginx_is_installed() -> bool:
    return nginx_exe().exists()


def nginx_is_running() -> bool:
    if not nginx_is_installed():
        return False
    pid_file = paths.NGINX_LOGS_DIR / "nginx.pid"
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            if fcgi.is_pid_alive(pid):
                return True
        except Exception:
            pass
    # Fallback to tasklist check
    try:
        out = subprocess.run(
            ["tasklist.exe", "/FI", "IMAGENAME eq nginx.exe", "/NH"],
            capture_output=True, text=True
        ).stdout
        return "nginx.exe" in out.lower()
    except Exception:
        return False


def _wait_for_port(port: int, timeout: float = 3.0) -> bool:
    """Poll TCP port until accepting connections or timeout occurs."""
    import socket, time
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.1)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.05)
    return False


def _wait_for_port_closed(port: int, timeout: float = 1.5) -> bool:
    """Poll TCP port until it is closed or timeout occurs."""
    import socket, time
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.1)
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return True
        time.sleep(0.05)
    return False


def _find_port_owner(port: int) -> tuple[int | None, str | None]:
    """Find PID and process name listening on a TCP port on Windows."""
    try:
        res = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command",
             f"(Get-NetTCPConnection -LocalPort {port} -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty OwningProcess)"],
            capture_output=True, text=True, timeout=3
        )
        pid_str = res.stdout.strip()
        if pid_str.isdigit():
            pid = int(pid_str)
            proc_res = subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command",
                 f"(Get-Process -Id {pid} -ErrorAction SilentlyContinue).ProcessName"],
                capture_output=True, text=True, timeout=3
            )
            name = proc_res.stdout.strip() or f"PID {pid}"
            return pid, name
    except Exception:
        pass
    return None, None


def nginx_start() -> None:
    exe = nginx_exe()
    if not exe.exists():
        raise FileNotFoundError("Nginx isn't installed -- run `ndev setup` first")

    if nginx_is_running():
        return

    # Check if port 80 is occupied by an external service (e.g. Apache / IIS / W3SVC)
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        if s.connect_ex(("127.0.0.1", 80)) == 0:
            pid, proc_name = _find_port_owner(80)
            detail = f"by '{proc_name}' (PID {pid})" if proc_name else "by another application"
            if proc_name and proc_name.lower() in ("httpd", "apache", "apache2"):
                advice = "Please stop your Apache / XAMPP / WAMP web server service before starting Nginx."
            elif proc_name and proc_name.lower() in ("system", "inetinfo", "w3wp", "iis"):
                advice = "Port 80 is occupied by Windows IIS / W3SVC. Run `iisreset /stop` in Administrator PowerShell to stop IIS."
            else:
                advice = f"Please close or stop '{proc_name or 'the conflicting process'}' to free up port 80."

            raise RuntimeError(f"Port 80 is already in use {detail}. {advice}")

    # Ensure logs and temp directories exist
    paths.NGINX_LOGS_DIR.mkdir(parents=True, exist_ok=True)
    temp_dir = paths.NGINX_DIR / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    subprocess.Popen(
        [str(exe)],
        cwd=str(paths.NGINX_DIR),
        creationflags=CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
    )
    _wait_for_port(80, timeout=2.0)


def nginx_stop() -> None:
    exe = nginx_exe()
    if not exe.exists():
        return
    try:
        subprocess.run([str(exe), "-s", "stop"], cwd=str(paths.NGINX_DIR), capture_output=True, timeout=5)
    except Exception:
        pass

    # Terminate the specific Nginx master PID tree if recorded in nginx.pid
    pid_file = paths.NGINX_LOGS_DIR / "nginx.pid"
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text(encoding="utf-8").strip())
            subprocess.run(["taskkill.exe", "/F", "/PID", str(pid), "/T"], capture_output=True)
            pid_file.unlink(missing_ok=True)
        except Exception:
            pass

    # Fallback to ensure no orphaned ndev nginx instances remain if still running
    if nginx_is_running():
        try:
            subprocess.run(["taskkill.exe", "/F", "/IM", "nginx.exe", "/T"], capture_output=True)
        except Exception:
            pass

    _wait_for_port_closed(80, timeout=1.5)


def nginx_reload() -> None:
    exe = nginx_exe()
    if not exe.exists():
        raise FileNotFoundError("Nginx isn't installed -- run `ndev setup` first")

    # Test config before reloading
    check = nginx_test_config()
    if check.returncode != 0:
        err_msg = (check.stderr.strip() + "\n" + check.stdout.strip()).strip()
        raise RuntimeError(f"Nginx configuration test (nginx -t) failed:\n{err_msg}")

    if nginx_is_running():
        subprocess.run([str(exe), "-s", "reload"], cwd=str(paths.NGINX_DIR), capture_output=True)
    else:
        nginx_start()


def nginx_test_config() -> subprocess.CompletedProcess:
    exe = nginx_exe()
    if not exe.exists():
        raise FileNotFoundError("Nginx isn't installed -- run `ndev setup` first")
    return subprocess.run(
        [str(exe), "-t"],
        cwd=str(paths.NGINX_DIR),
        capture_output=True,
        text=True
    )


def nginx_status() -> dict | None:
    if not nginx_is_installed():
        return None
    running = nginx_is_running()
    pid = None
    pid_file = paths.NGINX_LOGS_DIR / "nginx.pid"
    if pid_file.exists() and running:
        try:
            pid = int(pid_file.read_text(encoding="utf-8").strip())
        except Exception:
            pass
    return {"installed": True, "running": running, "pid": pid, "port": 80}


# ---- MariaDB ----------------------------------------------------------------

_MARIADB_STATE = paths.RUN_DIR / "mariadb.json"


def mariadb_is_installed() -> bool:
    return (paths.MARIADB_DIR / "bin" / "mysqld.exe").exists()


def mariadb_is_running() -> bool:
    st = mariadb_status()
    return bool(st and st.get("running"))


def mariadb_start(root_password: str = "root") -> int:
    exe = paths.MARIADB_DIR / "bin" / "mysqld.exe"
    if not exe.exists():
        raise FileNotFoundError("MariaDB isn't installed -- run `ndev setup` first")

    st = mariadb_status()
    if st and st.get("running"):
        return st["pid"]

    # Check if port 3306 is occupied by an external MySQL / MariaDB service
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        if s.connect_ex(("127.0.0.1", 3306)) == 0:
            pid, proc_name = _find_port_owner(3306)
            detail = f"by '{proc_name}' (PID {pid})" if proc_name else "by another application"
            raise RuntimeError(
                f"Port 3306 is already in use {detail}. "
                "Please stop any existing system MySQL / MariaDB service before starting ndev MariaDB."
            )

    data_dir = paths.MARIADB_DIR / "data"
    if not data_dir.exists() or not any(data_dir.iterdir()):
        from . import setup
        setup._init_mariadb_data_dir()

    data_dir.mkdir(parents=True, exist_ok=True)
    clean_data_dir = str(data_dir.resolve()).replace("\\", "/")
    my_ini = paths.MARIADB_DIR / "my.ini"

    cmd = [str(exe)]
    if my_ini.exists():
        cmd.append(f"--defaults-file={my_ini}")
    else:
        cmd.extend([f"--datadir={clean_data_dir}", "--bind-address=127.0.0.1", "--port=3306"])
    cmd.append("--console")

    proc = subprocess.Popen(
        cmd,
        cwd=str(paths.MARIADB_DIR),
        creationflags=CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW,
    )
    paths.ensure_dirs()
    _MARIADB_STATE.write_text(json.dumps({"pid": proc.pid, "running": True, "port": 3306}), encoding="utf-8")
    _wait_for_port(3306, timeout=5.0)
    return proc.pid


def mariadb_stop(root_password: str = "root") -> None:
    admin_exe = paths.MARIADB_DIR / "bin" / "mysqladmin.exe"
    if admin_exe.exists():
        try:
            cmd = [str(admin_exe), "-u", "root"]
            if root_password:
                cmd.append(f"--password={root_password}")
            cmd.append("shutdown")
            subprocess.run(cmd, capture_output=True, timeout=5)
        except Exception:
            pass

    st = mariadb_status()
    if st and st.get("pid"):
        pid = st["pid"]
        terminated = False
        try:
            handle = ctypes.windll.kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
            if handle:
                ctypes.windll.kernel32.TerminateProcess(handle, 0)
                ctypes.windll.kernel32.CloseHandle(handle)
                terminated = True
        except Exception:
            pass
        if not terminated or fcgi.is_pid_alive(pid, expected_name="mysqld"):
            try:
                subprocess.run(["taskkill.exe", "/F", "/PID", str(pid), "/T"], capture_output=True)
            except Exception:
                pass

    _MARIADB_STATE.unlink(missing_ok=True)
    _wait_for_port_closed(3306, timeout=2.0)


def mariadb_status() -> dict | None:
    if not _MARIADB_STATE.exists():
        return None
    try:
        data = json.loads(_MARIADB_STATE.read_text(encoding="utf-8"))
        pid = data.get("pid")
        if pid and fcgi.is_pid_alive(pid):
            data["running"] = True
            return data
    except Exception:
        pass
    _MARIADB_STATE.unlink(missing_ok=True)
    return None
