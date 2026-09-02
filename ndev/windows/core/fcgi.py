"""
FastCGI worker pool management for Windows.

Windows has no php-fpm SAPI (it's POSIX-only: relies on fork()).
The native substitute is a pool of `php-cgi.exe` processes, each
bound to its own TCP port, load-balanced by an Nginx `upstream` block.

State (pid + ports per version) is persisted as JSON under
~/.ndev/run/<version>.json so `stop`/`status` work across CLI invocations.
Process liveness is verified on every query.
"""
from __future__ import annotations

import ctypes
import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

import os

from . import paths

CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_TERMINATE = 0x0001
STILL_ACTIVE = 259


@dataclass
class WorkerState:
    pid: int
    port: int


def is_pid_alive(pid: int, expected_name: str | None = None) -> bool:
    """Check if a process with given PID is actively running on Windows, matching exe name if specified."""
    if pid <= 0:
        return False
    handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        exit_code = ctypes.c_ulong(0)
        success = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
        if not success or exit_code.value != STILL_ACTIVE:
            return False
        if expected_name:
            buf = (ctypes.c_wchar * 1024)()
            size = ctypes.c_ulong(1024)
            if ctypes.windll.kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return expected_name.lower() in buf.value.lower()
        return True
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def _state_file(version: str) -> Path:
    # Normalize version string for filenames (e.g. "8.4" or "8.4.25")
    return paths.RUN_DIR / f"php_{version}.json"


def _load_state(version: str) -> list[WorkerState]:
    f = _state_file(version)
    if not f.exists():
        return []
    try:
        raw = json.loads(f.read_text(encoding="utf-8"))
        workers = [WorkerState(**w) for w in raw]
    except Exception:
        return []
    
    # Filter out dead workers and recycled PIDs
    alive_workers = [w for w in workers if is_pid_alive(w.pid, expected_name="php-cgi")]
    if len(alive_workers) != len(workers):
        if alive_workers:
            _save_state(version, alive_workers)
        else:
            f.unlink(missing_ok=True)
    return alive_workers


def _save_state(version: str, workers: list[WorkerState]) -> None:
    paths.ensure_dirs()
    _state_file(version).write_text(json.dumps([asdict(w) for w in workers], indent=2), encoding="utf-8")


def ports_for(version: str, count: int, base_port: int) -> list[int]:
    """
    Deterministic, non-overlapping port block per version so multiple
    PHP versions can run their pools simultaneously without port collisions.
    Allocates up to 30 workers per minor version without overlap.
    """
    clean_ver = version.split()[0]
    parts = clean_ver.split(".")
    try:
        major = int(parts[0])
        minor = int(parts[1]) if len(parts) > 1 else 0
        offset = (major * 500 + minor * 30)
    except (ValueError, IndexError):
        import zlib
        offset = (zlib.crc32(clean_ver.encode("utf-8")) % 50) * 50
    return [base_port + offset + i for i in range(count)]


def _wait_for_ports(ports: list[int], timeout: float = 3.0) -> bool:
    """Poll TCP ports until all are accepting connections or timeout occurs."""
    import socket
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        all_open = True
        for port in ports:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.1)
                if s.connect_ex(("127.0.0.1", port)) != 0:
                    all_open = False
                    break
        if all_open:
            return True
        time.sleep(0.05)
    return False


def start(version: str, php_cgi_path: Path, workers: int, base_port: int) -> list[WorkerState]:
    current_state = _load_state(version)
    if current_state:
        return current_state

    if not Path(php_cgi_path).exists():
        raise FileNotFoundError(f"php-cgi.exe not found at {php_cgi_path}")

    ports = ports_for(version, workers, base_port)
    state: list[WorkerState] = []
    
    env = dict(os.environ)
    env["PHP_FCGI_CHILDREN"] = "0"
    env["PHP_FCGI_MAX_REQUESTS"] = "0"

    for port in ports:
        proc = subprocess.Popen(
            [str(php_cgi_path), "-b", f"127.0.0.1:{port}"],
            env=env,
            cwd=str(php_cgi_path.parent),
            creationflags=CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW,
        )
        state.append(WorkerState(pid=proc.pid, port=port))
    
    _wait_for_ports(ports)
    _save_state(version, state)
    return state


def stop(version: str) -> None:
    f = _state_file(version)
    if not f.exists():
        return
    try:
        raw = json.loads(f.read_text(encoding="utf-8"))
        workers = [WorkerState(**w) for w in raw]
    except Exception:
        workers = []

    for w in workers:
        if not is_pid_alive(w.pid, expected_name="php-cgi"):
            continue
        terminated = False
        try:
            handle = ctypes.windll.kernel32.OpenProcess(PROCESS_TERMINATE, False, w.pid)
            if handle:
                ctypes.windll.kernel32.TerminateProcess(handle, 0)
                ctypes.windll.kernel32.CloseHandle(handle)
                terminated = True
        except Exception:
            pass
        if not terminated or is_pid_alive(w.pid, expected_name="php-cgi"):
            try:
                subprocess.run(["taskkill.exe", "/F", "/PID", str(w.pid)], capture_output=True)
            except Exception:
                pass
            
    f.unlink(missing_ok=True)


def restart(version: str, workers: int | None = None, base_port: int | None = None) -> list[WorkerState]:
    # Local import to avoid circular imports
    from . import php
    cfg = paths.load_config()
    n_workers = workers or cfg["fcgi_workers_per_version"]
    port_base = base_port or cfg["fcgi_base_port"]
    
    stop(version)
    return start(version, php.php_cgi_exe(version), n_workers, port_base)


def status(version: str) -> list[WorkerState]:
    return _load_state(version)


def nginx_upstream_name(version: str, domain: str | None = None) -> str:
    clean_ver = version.replace(".", "_")
    if domain:
        import re
        clean_domain = re.sub(r"[^a-zA-Z0-9_]", "_", domain.strip().lower())
        return f"php_{clean_ver}_{clean_domain}"
    return f"php_{clean_ver}"


def render_upstream_block(version: str, domain: str | None = None) -> str:
    workers = status(version)
    if not workers:
        raise RuntimeError(f"PHP {version} pool is not running; start it first")
    servers = "\n".join(f"    server 127.0.0.1:{w.port};" for w in workers)
    u_name = nginx_upstream_name(version, domain=domain)
    return f"upstream {u_name} {{\n{servers}\n}}\n"
