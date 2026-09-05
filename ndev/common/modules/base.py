"""
Base module definition for ndev extensible modules system.
"""
from __future__ import annotations

import importlib.util
import json
import os
import platform
import shutil
import socket
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def is_port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.5) -> bool:
    """Check if a TCP port is open / listening."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            return s.connect_ex((host, port)) == 0
    except Exception:
        return False


def wait_for_port(port: int, host: str = "127.0.0.1", timeout: float = 3.0) -> bool:
    """Wait until port is listening or timeout expires."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if is_port_open(port, host, timeout=0.1):
            return True
        time.sleep(0.05)
    return False


def wait_for_port_closed(port: int, host: str = "127.0.0.1", timeout: float = 2.0) -> bool:
    """Wait until port is closed or timeout expires."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not is_port_open(port, host, timeout=0.1):
            return True
        time.sleep(0.05)
    return False


class NdevModule:
    """
    Represents an extensible ndev module loaded from <userdir>/.ndev/modules/<module_name>/.
    """

    def __init__(self, module_dir: Path, manifest: dict, handler_instance: Optional[Any] = None) -> None:
        self.module_dir = Path(module_dir).resolve()
        self.manifest = manifest
        self.handler = handler_instance

        self.name: str = manifest.get("name", self.module_dir.name)
        self.display_name: str = manifest.get("display_name", self.name.title())
        self.version: str = manifest.get("version", "1.0.0")
        self.description: str = manifest.get("description", "")
        self.category: str = manifest.get("category", "utility")
        self.author: str = manifest.get("author", "ndev")
        self.homepage: str = manifest.get("homepage", "")
        self.ports: Dict[str, int] = manifest.get("ports", {})
        self.web_ui: Optional[str] = manifest.get("web_ui")
        self.platforms: List[str] = manifest.get("platforms", ["windows", "linux", "darwin"])
        self.entrypoint: Optional[str] = manifest.get("entrypoint", "module.py")

    @property
    def primary_port(self) -> Optional[int]:
        if not self.ports:
            return None
        return next(iter(self.ports.values()))

    @property
    def is_supported_platform(self) -> bool:
        sys_name = platform.system().lower()
        if "all" in self.platforms or sys_name in self.platforms:
            return True
        if sys_name == "windows" and "win" in self.platforms:
            return True
        if sys_name == "linux" and "linux" in self.platforms:
            return True
        return False

    def is_installed(self) -> bool:
        if self.handler and hasattr(self.handler, "is_installed"):
            return bool(self.handler.is_installed())
        bin_dir = self.module_dir / "bin"
        if bin_dir.exists() and any(bin_dir.iterdir()):
            return True
        return False

    def install(self, **kwargs) -> bool:
        if self.handler and hasattr(self.handler, "install"):
            return bool(self.handler.install(**kwargs))
        return True

    def start(self, **kwargs) -> Any:
        if self.handler and hasattr(self.handler, "start"):
            return self.handler.start(**kwargs)
        return False

    def stop(self, **kwargs) -> bool:
        if self.handler and hasattr(self.handler, "stop"):
            return bool(self.handler.stop(**kwargs))
        return False

    def restart(self, **kwargs) -> Any:
        if self.handler and hasattr(self.handler, "restart"):
            return self.handler.restart(**kwargs)
        self.stop(**kwargs)
        return self.start(**kwargs)

    def status(self) -> dict:
        installed = self.is_installed()
        if not installed:
            return {
                "name": self.name,
                "display_name": self.display_name,
                "installed": False,
                "running": False,
                "pid": None,
                "ports": self.ports,
                "version": self.version,
                "web_ui": self.web_ui,
                "details": "Not installed"
            }

        if self.handler and hasattr(self.handler, "status"):
            res = self.handler.status()
            if isinstance(res, dict):
                res.setdefault("name", self.name)
                res.setdefault("display_name", self.display_name)
                res.setdefault("installed", True)
                res.setdefault("ports", self.ports)
                res.setdefault("version", self.version)
                res.setdefault("web_ui", self.web_ui)
                return res
            elif isinstance(res, bool):
                return {
                    "name": self.name,
                    "display_name": self.display_name,
                    "installed": True,
                    "running": res,
                    "pid": None,
                    "ports": self.ports,
                    "version": self.version,
                    "web_ui": self.web_ui,
                    "details": "Running" if res else "Stopped"
                }

        running = False
        if self.primary_port:
            running = is_port_open(self.primary_port)

        return {
            "name": self.name,
            "display_name": self.display_name,
            "installed": True,
            "running": running,
            "pid": None,
            "ports": self.ports,
            "version": self.version,
            "web_ui": self.web_ui,
            "details": f"Port {self.primary_port} active" if running else "Stopped"
        }

    def uninstall(self) -> bool:
        if self.handler and hasattr(self.handler, "uninstall"):
            return bool(self.handler.uninstall())
        return True

    def open_ui(self) -> bool:
        if self.handler and hasattr(self.handler, "open_ui"):
            return bool(self.handler.open_ui())
        if self.web_ui:
            import webbrowser
            webbrowser.open(self.web_ui)
            return True
        return False
