"""
MongoDB module handler for ndev.
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

DEFAULT_VERSION = "7.0.14"
DEFAULT_MONGOSH_VERSION = "2.3.8"


class Module:
    def __init__(self, module_dir: Path, manifest: dict) -> None:
        self.module_dir = Path(module_dir).resolve()
        self.manifest = manifest
        self.bin_dir = self.module_dir / "bin"
        self.data_dir = self.module_dir / "data"
        self.logs_dir = self.module_dir / "logs"
        self.run_dir = self.module_dir / "run"

        is_win = platform.system() == "Windows"
        self.mongod_name = "mongod.exe" if is_win else "mongod"
        self.mongosh_name = "mongosh.exe" if is_win else "mongosh"
        self.state_file = self.run_dir / "mongodb.json"

    def _ensure_dirs(self) -> None:
        for d in (self.bin_dir, self.data_dir, self.logs_dir, self.run_dir):
            d.mkdir(parents=True, exist_ok=True)

    def _find_binary(self, name: str) -> Optional[Path]:
        candidates = [
            self.bin_dir / name,
            self.module_dir.parent.parent / "shims" / name,
        ]
        for c in candidates:
            if c.exists():
                return c
        which = shutil.which(name)
        if which:
            return Path(which)
        return None

    def is_installed(self) -> bool:
        return self._find_binary(self.mongod_name) is not None

    def install(self, version: str = DEFAULT_VERSION) -> Path:
        self._ensure_dirs()
        sys_name = platform.system().lower()

        if sys_name == "windows":
            # 1. Download official portable MongoDB community zip
            url = f"https://fastdl.mongodb.org/windows/mongodb-windows-x86_64-{version}.zip"
            dl_file = self.bin_dir / f"mongodb-{version}.zip"

            headers = {"User-Agent": "Mozilla/5.0 ndev/0.2.0"}
            if not dl_file.exists() or dl_file.stat().st_size == 0:
                with httpx.Client(verify=False, follow_redirects=True, timeout=180.0) as client:
                    with client.stream("GET", url, headers=headers) as r:
                        r.raise_for_status()
                        with open(dl_file, "wb") as f:
                            for chunk in r.iter_bytes(chunk_size=131072):
                                f.write(chunk)

            extract_tmp = self.bin_dir / "_extract"
            if extract_tmp.exists():
                shutil.rmtree(extract_tmp)

            with zipfile.ZipFile(dl_file) as zf:
                zf.extractall(extract_tmp)

            # Move bin items to self.bin_dir
            for root, dirs, files in os.walk(extract_tmp):
                for f in files:
                    if f.lower().endswith(".exe") or f.lower().endswith(".pdb"):
                        src_f = Path(root) / f
                        shutil.copy2(src_f, self.bin_dir / f)

            shutil.rmtree(extract_tmp, ignore_errors=True)
            if dl_file.exists():
                try:
                    dl_file.unlink()
                except Exception:
                    pass

            # 2. Try downloading mongosh (MongoDB Shell)
            try:
                mongosh_url = f"https://downloads.mongodb.com/compass/mongosh-{DEFAULT_MONGOSH_VERSION}-win32-x64.zip"
                dl_mongosh = self.bin_dir / "mongosh.zip"
                with httpx.Client(verify=False, follow_redirects=True, timeout=60.0) as client:
                    with client.stream("GET", mongosh_url, headers=headers) as r:
                        if r.status_code == 200:
                            with open(dl_mongosh, "wb") as f:
                                for chunk in r.iter_bytes(chunk_size=131072):
                                    f.write(chunk)
                if dl_mongosh.exists() and dl_mongosh.stat().st_size > 0:
                    extract_sh = self.bin_dir / "_extract_sh"
                    with zipfile.ZipFile(dl_mongosh) as zf:
                        zf.extractall(extract_sh)
                    for root, dirs, files in os.walk(extract_sh):
                        for f in files:
                            if f.lower().endswith(".exe"):
                                shutil.copy2(Path(root) / f, self.bin_dir / f)
                    shutil.rmtree(extract_sh, ignore_errors=True)
                    dl_mongosh.unlink(missing_ok=True)
            except Exception:
                pass

            # Copy tools to ~/.ndev/shims/
            shim_dir = self.module_dir.parent.parent / "shims"
            if shim_dir.exists():
                for tool in ["mongod.exe", "mongos.exe", "mongosh.exe"]:
                    src_tool = self.bin_dir / tool
                    if src_tool.exists():
                        try:
                            shutil.copy2(src_tool, shim_dir / tool)
                        except Exception:
                            pass
        else:
            # Linux: try installing via system package manager or apt
            if not shutil.which("mongod"):
                try:
                    subprocess.run(["sudo", "apt-get", "update"], capture_output=True)
                    subprocess.run(["sudo", "apt-get", "install", "-y", "mongodb-org", "mongodb"], capture_output=True)
                except Exception:
                    pass

        exe = self._find_binary(self.mongod_name)
        if not exe:
            raise RuntimeError("MongoDB installation completed but mongod executable could not be found.")
        return exe

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
                "name": "mongodb",
                "display_name": "MongoDB",
                "installed": False,
                "running": False,
                "pid": None,
                "ports": {"mongodb": 27017},
                "version": self.manifest.get("version", DEFAULT_VERSION),
                "web_ui": None,
                "details": "Not installed"
            }

        pid = None
        if self.state_file.exists():
            try:
                data = json.loads(self.state_file.read_text(encoding="utf-8"))
                cand_pid = data.get("pid")
                if cand_pid and self._is_pid_alive(cand_pid):
                    pid = cand_pid
            except Exception:
                pass

        from ndev.common.modules.base import is_port_open
        running = (pid is not None) or is_port_open(27017)

        return {
            "name": "mongodb",
            "display_name": "MongoDB",
            "installed": True,
            "running": running,
            "pid": pid,
            "ports": {"mongodb": 27017},
            "version": self.manifest.get("version", DEFAULT_VERSION),
            "web_ui": None,
            "details": f"Running (PID {pid}, Port 27017)" if running else "Stopped"
        }

    def start(self, **kwargs) -> Any:
        self._ensure_dirs()
        st = self.status()
        if st["running"]:
            return st["pid"] or True

        if not self.is_installed():
            self.install()

        mongod_exe = self._find_binary(self.mongod_name)
        if not mongod_exe:
            raise RuntimeError("Could not find mongod executable.")

        log_path = self.logs_dir / "mongodb.log"
        cmd = [
            str(mongod_exe),
            "--dbpath", str(self.data_dir),
            "--port", "27017",
            "--bind_ip", "127.0.0.1",
            "--logpath", str(log_path),
            "--logappend"
        ]

        kwargs_proc = {
            "cwd": str(self.module_dir),
        }
        if platform.system() == "Windows":
            kwargs_proc["creationflags"] = CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
        else:
            kwargs_proc["start_new_session"] = True

        proc = subprocess.Popen(cmd, **kwargs_proc)
        pid = proc.pid

        from ndev.common.modules.base import wait_for_port
        wait_for_port(27017, timeout=5.0)

        self.state_file.write_text(json.dumps({
            "pid": pid,
            "started_at": time.time(),
            "port": 27017
        }, indent=2), encoding="utf-8")

        return pid

    def stop(self, **kwargs) -> bool:
        if platform.system() == "Windows":
            subprocess.run(["taskkill.exe", "/F", "/IM", "mongod.exe"], capture_output=True)
        else:
            subprocess.run(["pkill", "-f", "mongod"], capture_output=True)

        if self.state_file.exists():
            try:
                self.state_file.unlink()
            except Exception:
                pass

        from ndev.common.modules.base import wait_for_port_closed
        wait_for_port_closed(27017, timeout=2.0)
        return True

    def restart(self, **kwargs) -> Any:
        self.stop()
        time.sleep(0.5)
        return self.start()

    def uninstall(self) -> bool:
        self.stop()
        if self.bin_dir.exists():
            shutil.rmtree(self.bin_dir, ignore_errors=True)
        return True
