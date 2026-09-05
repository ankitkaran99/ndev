"""
Mailpit module handler for ndev.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import time
import zipfile
from pathlib import Path
from typing import Any, Optional

import httpx

GITHUB_REPO = "axllent/mailpit"
RELEASES_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000


class Module:
    def __init__(self, module_dir: Path, manifest: dict) -> None:
        self.module_dir = Path(module_dir).resolve()
        self.manifest = manifest
        self.bin_dir = self.module_dir / "bin"
        self.data_dir = self.module_dir / "data"
        self.logs_dir = self.module_dir / "logs"
        self.run_dir = self.module_dir / "run"

        self.bin_name = "mailpit.exe" if platform.system() == "Windows" else "mailpit"
        self.bin_path = self.bin_dir / self.bin_name
        self.state_file = self.run_dir / "mailpit.json"
        self.db_file = self.data_dir / "mailpit.db"

    def _ensure_dirs(self) -> None:
        for d in (self.bin_dir, self.data_dir, self.logs_dir, self.run_dir):
            d.mkdir(parents=True, exist_ok=True)

    def is_installed(self) -> bool:
        # Check in module bin or global PATH / shims
        if self.bin_path.exists():
            return True
        user_shim = self.module_dir.parent.parent / "shims" / self.bin_name
        if user_shim.exists():
            return True
        return shutil.which(self.bin_name) is not None

    def get_binary(self) -> Path:
        if self.bin_path.exists():
            return self.bin_path
        user_shim = self.module_dir.parent.parent / "shims" / self.bin_name
        if user_shim.exists():
            return user_shim
        which = shutil.which(self.bin_name)
        if which:
            return Path(which)
        return self.bin_path

    def install(self, console: Any = None) -> Path:
        self._ensure_dirs()
        sys_name = platform.system().lower()
        arch = platform.machine().lower()
        arch_tag = "arm64" if ("arm" in arch or "aarch64" in arch) else "amd64"

        headers = {"User-Agent": "Mozilla/5.0 ndev/0.2.0"}
        with httpx.Client(follow_redirects=True, timeout=25.0) as client:
            resp = client.get(RELEASES_API_URL, headers=headers)
            resp.raise_for_status()
            release = resp.json()

        tag = release.get("tag_name", "latest")
        target_asset = None
        for asset in release.get("assets", []):
            aname = asset["name"].lower()
            if sys_name in aname and arch_tag in aname:
                target_asset = asset
                break
        
        if not target_asset:
            # Fallback search
            for asset in release.get("assets", []):
                aname = asset["name"].lower()
                if sys_name in aname:
                    target_asset = asset
                    break

        if not target_asset:
            raise RuntimeError(f"Could not find Mailpit asset for {sys_name}-{arch_tag} in {tag}")

        dl_url = target_asset["browser_download_url"]
        dl_file = self.bin_dir / target_asset["name"]

        with httpx.Client(follow_redirects=True, timeout=60.0) as client:
            with client.stream("GET", dl_url, headers=headers) as r:
                r.raise_for_status()
                with open(dl_file, "wb") as f:
                    for chunk in r.iter_bytes(chunk_size=65536):
                        f.write(chunk)

        if str(dl_file).endswith(".zip"):
            with zipfile.ZipFile(dl_file) as zf:
                zf.extractall(self.bin_dir)
        elif str(dl_file).endswith((".tar.gz", ".tgz")):
            with tarfile.open(dl_file, "r:*") as tf:
                tf.extractall(self.bin_dir)

        if dl_file.exists():
            try:
                dl_file.unlink()
            except Exception:
                pass

        if self.bin_path.exists():
            try:
                self.bin_path.chmod(0o755)
            except Exception:
                pass

        # Also copy to shims if on Windows
        if sys_name == "windows":
            shim_dir = self.module_dir.parent.parent / "shims"
            if shim_dir.exists():
                try:
                    shutil.copy2(self.bin_path, shim_dir / self.bin_name)
                except Exception:
                    pass

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
                "name": "mailpit",
                "display_name": "Mailpit",
                "installed": False,
                "running": False,
                "pid": None,
                "ports": {"smtp": 1025, "http": 8025},
                "version": self.manifest.get("version", "1.21.8"),
                "web_ui": "http://localhost:8025",
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

        # Also check port 8025 or 1025
        from ndev.common.modules.base import is_port_open
        running = (pid is not None) or is_port_open(8025)

        return {
            "name": "mailpit",
            "display_name": "Mailpit",
            "installed": True,
            "running": running,
            "pid": pid,
            "ports": {"smtp": 1025, "http": 8025},
            "version": self.manifest.get("version", "1.21.8"),
            "web_ui": "http://localhost:8025",
            "details": f"Running (PID {pid}, HTTP:8025, SMTP:1025)" if running else "Stopped"
        }

    def start(self, **kwargs) -> Any:
        self._ensure_dirs()
        st = self.status()
        if st["running"]:
            return st["pid"] or True

        if not self.is_installed():
            self.install()

        exe = self.get_binary()
        cmd = [
            str(exe),
            "--smtp", "127.0.0.1:1025",
            "--ui", "127.0.0.1:8025",
            "--db-file", str(self.db_file),
        ]

        log_path = self.logs_dir / "mailpit.log"
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

        # Wait for port 8025
        from ndev.common.modules.base import wait_for_port
        wait_for_port(8025, timeout=3.0)

        self.state_file.write_text(json.dumps({
            "pid": pid,
            "started_at": time.time(),
            "smtp_port": 1025,
            "web_port": 8025
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
            subprocess.run(["taskkill.exe", "/F", "/IM", "mailpit.exe"], capture_output=True)
        else:
            if pid and self._is_pid_alive(pid):
                try:
                    os.kill(pid, 15)
                except Exception:
                    pass
            subprocess.run(["pkill", "-f", "mailpit"], capture_output=True)

        if self.state_file.exists():
            try:
                self.state_file.unlink()
            except Exception:
                pass

        from ndev.common.modules.base import wait_for_port_closed
        wait_for_port_closed(8025, timeout=2.0)
        return True

    def restart(self, **kwargs) -> Any:
        self.stop()
        time.sleep(0.3)
        return self.start()

    def uninstall(self) -> bool:
        self.stop()
        if self.bin_path.exists():
            try:
                self.bin_path.unlink()
            except Exception:
                pass
        return True

    def open_ui(self) -> bool:
        import webbrowser
        webbrowser.open("http://localhost:8025")
        return True
