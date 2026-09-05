"""
Redis module handler for ndev.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from typing import Any, Optional

import httpx

CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000

DEFAULT_VERSION = "8.10.1"
FALLBACK_VERSION = "5.0.14.1"


class Module:
    def __init__(self, module_dir: Path, manifest: dict) -> None:
        self.module_dir = Path(module_dir).resolve()
        self.manifest = manifest
        self.bin_dir = self.module_dir / "bin"
        self.data_dir = self.module_dir / "data"
        self.conf_dir = self.module_dir / "conf"
        self.logs_dir = self.module_dir / "logs"
        self.run_dir = self.module_dir / "run"

        self.bin_name = "redis-server.exe" if platform.system() == "Windows" else "redis-server"
        self.cli_name = "redis-cli.exe" if platform.system() == "Windows" else "redis-cli"
        self.bin_path = self.bin_dir / self.bin_name
        self.cli_path = self.bin_dir / self.cli_name
        self.conf_path = self.conf_dir / "redis.conf"
        self.state_file = self.run_dir / "redis.json"

    def _ensure_dirs(self) -> None:
        for d in (self.bin_dir, self.data_dir, self.conf_dir, self.logs_dir, self.run_dir):
            d.mkdir(parents=True, exist_ok=True)

    def is_installed(self) -> bool:
        if self.bin_path.exists():
            return True
        user_shim = self.module_dir.parent.parent / "shims" / self.bin_name
        if user_shim.exists():
            return True
        user_redis = self.module_dir.parent.parent / "redis" / self.bin_name
        if user_redis.exists():
            return True
        return shutil.which(self.bin_name) is not None

    def get_binary(self) -> Path:
        if self.bin_path.exists():
            return self.bin_path
        user_redis = self.module_dir.parent.parent / "redis" / self.bin_name
        if user_redis.exists():
            return user_redis
        user_shim = self.module_dir.parent.parent / "shims" / self.bin_name
        if user_shim.exists():
            return user_shim
        which = shutil.which(self.bin_name)
        if which:
            return Path(which)
        return self.bin_path

    def install(self, version: str = DEFAULT_VERSION) -> Path:
        self._ensure_dirs()
        sys_name = platform.system().lower()

        if sys_name == "windows":
            urls = [
                f"https://github.com/redis-windows/redis-windows/releases/download/{version}/Redis-{version}-Windows-x64-cygwin.zip",
                f"https://github.com/tporadowski/redis/releases/download/v{FALLBACK_VERSION}/Redis-x64-{FALLBACK_VERSION}.zip",
            ]

            dl_file = self.bin_dir / f"redis-{version}.zip"
            downloaded = False
            last_err = None

            headers = {"User-Agent": "Mozilla/5.0 ndev/0.2.0"}
            for url in urls:
                try:
                    with httpx.Client(follow_redirects=True, timeout=60.0) as client:
                        with client.stream("GET", url, headers=headers) as r:
                            r.raise_for_status()
                            with open(dl_file, "wb") as f:
                                for chunk in r.iter_bytes(chunk_size=65536):
                                    f.write(chunk)
                    downloaded = True
                    break
                except Exception as e:
                    last_err = e
                    continue

            if not downloaded:
                raise RuntimeError(f"Failed to download Redis for Windows: {last_err}")

            extract_tmp = self.bin_dir / "_extract"
            if extract_tmp.exists():
                shutil.rmtree(extract_tmp)

            with zipfile.ZipFile(dl_file) as zf:
                zf.extractall(extract_tmp)

            inner_dirs = [d for d in extract_tmp.iterdir() if d.is_dir()]
            src = inner_dirs[0] if (len(inner_dirs) == 1 and not [f for f in extract_tmp.iterdir() if f.is_file()]) else extract_tmp

            for item in src.iterdir():
                dest = self.bin_dir / item.name
                if item.is_dir():
                    if dest.exists():
                        shutil.rmtree(dest)
                    shutil.copytree(item, dest)
                else:
                    shutil.copy2(item, dest)

            shutil.rmtree(extract_tmp, ignore_errors=True)
            if dl_file.exists():
                try:
                    dl_file.unlink()
                except Exception:
                    pass

            # Copy redis-cli.exe to shims if available
            shim_dir = self.module_dir.parent.parent / "shims"
            if shim_dir.exists() and self.cli_path.exists():
                try:
                    shutil.copy2(self.cli_path, shim_dir / self.cli_name)
                except Exception:
                    pass
        else:
            # Linux: try system package or download/compile
            if not shutil.which("redis-server"):
                try:
                    subprocess.run(["sudo", "apt-get", "update"], capture_output=True)
                    subprocess.run(["sudo", "apt-get", "install", "-y", "redis-server"], capture_output=True)
                except Exception:
                    pass

        # Create default redis.conf
        if not self.conf_path.exists():
            data_dir_str = str(self.data_dir).replace("\\", "/")
            conf_text = f"""# ndev Redis configuration
port 6379
bind 127.0.0.1
protected-mode yes
timeout 0
tcp-keepalive 300
daemonize no
loglevel notice
dir "{data_dir_str}"
dbfilename dump.rdb
maxmemory 256mb
maxmemory-policy allkeys-lru
"""
            self.conf_path.write_text(conf_text, encoding="utf-8")

        return self.bin_path

    def _is_pid_alive(self, pid: int) -> bool:
        if pid <= 0:
            return False
        if platform.system() == "Windows":
            try:
                out = subprocess.run(
                    ["tasklist.exe", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                    capture_output=True, text=True, timeout=2
                ).stdout
                return str(pid) in out
            except Exception:
                return False
        else:
            try:
                os.kill(pid, 0)
                return True
            except OSError:
                return False

    def status(self) -> dict:
        installed = self.is_installed()
        if not installed:
            return {
                "name": "redis",
                "display_name": "Redis Server",
                "installed": False,
                "running": False,
                "pid": None,
                "ports": {"redis": 6379},
                "version": self.manifest.get("version", DEFAULT_VERSION),
                "web_ui": None,
                "details": "Not installed"
            }

        pid = None
        if self.state_file.exists():
            try:
                data = json.loads(self.state_file.read_text(encoding="utf-8"))
                stored_pid = data.get("pid")
                if stored_pid and self._is_pid_alive(stored_pid):
                    pid = stored_pid
            except Exception:
                pass

        from ndev.common.modules.base import is_port_open
        running = (pid is not None) or is_port_open(6379)

        return {
            "name": "redis",
            "display_name": "Redis Server",
            "installed": True,
            "running": running,
            "pid": pid,
            "ports": {"redis": 6379},
            "version": self.manifest.get("version", DEFAULT_VERSION),
            "web_ui": None,
            "details": f"Running (PID {pid}, Port 6379)" if running else "Stopped"
        }

    def start(self, **kwargs) -> Any:
        self._ensure_dirs()
        st = self.status()
        if st["running"]:
            return st["pid"] or True

        if not self.is_installed():
            self.install()

        if not self.conf_path.exists():
            self.install()

        exe = self.get_binary()
        cmd = [str(exe), str(self.conf_path)]

        log_path = self.logs_dir / "redis.log"
        log_file = open(log_path, "a", encoding="utf-8")

        kwargs_proc = {
            "stdout": log_file,
            "stderr": subprocess.STDOUT,
            "cwd": str(self.module_dir),
        }

        if platform.system() == "Windows":
            kwargs_proc["creationflags"] = CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
        else:
            kwargs_proc["start_new_session"] = True

        proc = subprocess.Popen(cmd, **kwargs_proc)
        pid = proc.pid

        from ndev.common.modules.base import wait_for_port
        wait_for_port(6379, timeout=3.0)

        self.state_file.write_text(json.dumps({
            "pid": pid,
            "started_at": time.time(),
            "port": 6379,
            "conf": str(self.conf_path)
        }, indent=2), encoding="utf-8")

        return pid

    def stop(self, **kwargs) -> bool:
        pid = None
        if self.state_file.exists():
            try:
                data = json.loads(self.state_file.read_text(encoding="utf-8"))
                pid = data.get("pid")
            except Exception:
                pass

        if platform.system() == "Windows":
            if pid and self._is_pid_alive(pid):
                subprocess.run(["taskkill.exe", "/F", "/T", "/PID", str(pid)], capture_output=True)
            subprocess.run(["taskkill.exe", "/F", "/IM", "redis-server.exe"], capture_output=True)
        else:
            if pid and self._is_pid_alive(pid):
                try:
                    os.kill(pid, 15)
                except Exception:
                    pass
            subprocess.run(["pkill", "-f", "redis-server"], capture_output=True)

        if self.state_file.exists():
            try:
                self.state_file.unlink()
            except Exception:
                pass

        from ndev.common.modules.base import wait_for_port_closed
        wait_for_port_closed(6379, timeout=2.0)
        return True

    def restart(self, **kwargs) -> Any:
        self.stop()
        time.sleep(0.3)
        return self.start()

    def uninstall(self) -> bool:
        self.stop()
        if self.bin_dir.exists():
            try:
                shutil.rmtree(self.bin_dir, ignore_errors=True)
            except Exception:
                pass
        return True
