"""
PostgreSQL module handler for ndev.
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

DEFAULT_VERSION = "17.2-1"


class Module:
    def __init__(self, module_dir: Path, manifest: dict) -> None:
        self.module_dir = Path(module_dir).resolve()
        self.manifest = manifest
        self.bin_dir = self.module_dir / "bin"
        self.data_dir = self.module_dir / "data"
        self.logs_dir = self.module_dir / "logs"
        self.run_dir = self.module_dir / "run"

        is_win = platform.system() == "Windows"
        self.pg_ctl_name = "pg_ctl.exe" if is_win else "pg_ctl"
        self.postgres_name = "postgres.exe" if is_win else "postgres"
        self.initdb_name = "initdb.exe" if is_win else "initdb"
        self.psql_name = "psql.exe" if is_win else "psql"

        self.state_file = self.run_dir / "postgres.json"

    def _ensure_dirs(self) -> None:
        for d in (self.bin_dir, self.data_dir, self.logs_dir, self.run_dir):
            d.mkdir(parents=True, exist_ok=True)

    def _find_binary(self, name: str) -> Optional[Path]:
        # 1. Look in module bin/ or module pgsql/bin/
        candidates = [
            self.bin_dir / name,
            self.module_dir / "pgsql" / "bin" / name,
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
        return self._find_binary(self.pg_ctl_name) is not None

    def install(self, version: str = DEFAULT_VERSION) -> Path:
        self._ensure_dirs()
        sys_name = platform.system().lower()

        if sys_name == "windows":
            # Download EnterpriseDB portable PostgreSQL binary zip
            # Fallback URL pattern
            url = f"https://get.enterprisedb.com/postgresql/postgresql-{version}-windows-x64-binaries.zip"
            dl_file = self.bin_dir / f"postgresql-{version}.zip"

            headers = {"User-Agent": "Mozilla/5.0 ndev/0.2.0"}
            if not dl_file.exists() or dl_file.stat().st_size == 0:
                with httpx.Client(follow_redirects=True, timeout=120.0) as client:
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

            # Look for pgsql/bin directory
            src = extract_tmp / "pgsql" if (extract_tmp / "pgsql").exists() else extract_tmp
            for item in src.iterdir():
                dest = self.module_dir / item.name if item.name in ["lib", "share", "include"] else (self.bin_dir / item.name if item.name != "bin" else self.bin_dir)
                if item.is_dir() and item.name == "bin":
                    for bin_item in item.iterdir():
                        shutil.copy2(bin_item, self.bin_dir / bin_item.name)
                elif item.is_dir():
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

            # Copy key cli binaries to ~/.ndev/shims/
            shim_dir = self.module_dir.parent.parent / "shims"
            if shim_dir.exists():
                for tool in ["psql.exe", "pg_ctl.exe", "pg_dump.exe", "createdb.exe", "dropdb.exe"]:
                    src_tool = self.bin_dir / tool
                    if src_tool.exists():
                        try:
                            shutil.copy2(src_tool, shim_dir / tool)
                        except Exception:
                            pass
        else:
            # Linux: try installing via system package manager
            if not shutil.which("pg_ctl"):
                try:
                    subprocess.run(["sudo", "apt-get", "update"], capture_output=True)
                    subprocess.run(["sudo", "apt-get", "install", "-y", "postgresql", "postgresql-client"], capture_output=True)
                except Exception:
                    pass

        # Initialize database cluster if data/ is empty
        self._init_cluster()

        exe = self._find_binary(self.pg_ctl_name)
        if not exe:
            raise RuntimeError("PostgreSQL installation completed but pg_ctl binary could not be found.")
        return exe

    def _init_cluster(self) -> None:
        """Initialize data cluster in self.data_dir."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if (self.data_dir / "PG_VERSION").exists():
            return

        initdb_exe = self._find_binary(self.initdb_name)
        if not initdb_exe:
            return

        cmd = [
            str(initdb_exe),
            "-D", str(self.data_dir),
            "-U", "postgres",
            "-E", "UTF8",
            "-A", "trust",
            "--no-locale"
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            # Try without --no-locale
            cmd_alt = [str(initdb_exe), "-D", str(self.data_dir), "-U", "postgres", "-E", "UTF8", "-A", "trust"]
            subprocess.run(cmd_alt, capture_output=True, text=True)

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
                "name": "postgres",
                "display_name": "PostgreSQL",
                "installed": False,
                "running": False,
                "pid": None,
                "ports": {"postgres": 5432},
                "version": self.manifest.get("version", "17.2"),
                "web_ui": None,
                "details": "Not installed"
            }

        pid = None
        pid_file = self.data_dir / "postmaster.pid"
        if pid_file.exists():
            try:
                lines = pid_file.read_text().splitlines()
                if lines and lines[0].strip().isdigit():
                    cand_pid = int(lines[0].strip())
                    if self._is_pid_alive(cand_pid):
                        pid = cand_pid
            except Exception:
                pass

        if not pid and self.state_file.exists():
            try:
                data = json.loads(self.state_file.read_text(encoding="utf-8"))
                cand_pid = data.get("pid")
                if cand_pid and self._is_pid_alive(cand_pid):
                    pid = cand_pid
            except Exception:
                pass

        from ndev.common.modules.base import is_port_open
        running = (pid is not None) or is_port_open(5432)

        return {
            "name": "postgres",
            "display_name": "PostgreSQL",
            "installed": True,
            "running": running,
            "pid": pid,
            "ports": {"postgres": 5432},
            "version": self.manifest.get("version", "17.2"),
            "web_ui": None,
            "details": f"Running (PID {pid}, Port 5432)" if running else "Stopped"
        }

    def start(self, **kwargs) -> Any:
        self._ensure_dirs()
        st = self.status()
        if st["running"]:
            return st["pid"] or True

        if not self.is_installed():
            self.install()

        self._init_cluster()

        pg_ctl_exe = self._find_binary(self.pg_ctl_name)
        log_path = self.logs_dir / "postgres.log"

        if pg_ctl_exe:
            cmd = [
                str(pg_ctl_exe),
                "-D", str(self.data_dir),
                "-l", str(log_path),
                "-o", "-p 5432",
                "start"
            ]
            subprocess.run(cmd, capture_output=True)
        else:
            postgres_exe = self._find_binary(self.postgres_name)
            if not postgres_exe:
                raise RuntimeError("Could not find pg_ctl or postgres executable.")
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
            subprocess.Popen([str(postgres_exe), "-D", str(self.data_dir), "-p", "5432"], **kwargs_proc)

        from ndev.common.modules.base import wait_for_port
        wait_for_port(5432, timeout=4.0)

        # Record status
        st_after = self.status()
        if st_after["pid"]:
            self.state_file.write_text(json.dumps({
                "pid": st_after["pid"],
                "started_at": time.time(),
                "port": 5432
            }, indent=2), encoding="utf-8")
        return st_after["pid"] or True

    def stop(self, **kwargs) -> bool:
        pg_ctl_exe = self._find_binary(self.pg_ctl_name)
        if pg_ctl_exe and self.data_dir.exists():
            subprocess.run([str(pg_ctl_exe), "-D", str(self.data_dir), "-m", "fast", "stop"], capture_output=True)

        if platform.system() == "Windows":
            subprocess.run(["taskkill.exe", "/F", "/IM", "postgres.exe"], capture_output=True)
        else:
            subprocess.run(["pkill", "-f", "postgres"], capture_output=True)

        if self.state_file.exists():
            try:
                self.state_file.unlink()
            except Exception:
                pass

        from ndev.common.modules.base import wait_for_port_closed
        wait_for_port_closed(5432, timeout=2.0)
        return True

    def restart(self, **kwargs) -> Any:
        self.stop()
        time.sleep(0.4)
        return self.start()

    def uninstall(self) -> bool:
        self.stop()
        if self.bin_dir.exists():
            shutil.rmtree(self.bin_dir, ignore_errors=True)
        return True
