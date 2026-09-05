# ndev Module Developer Guide

This guide covers how to create, build, test, and distribute custom dynamic modules for **ndev**.

---

## 1. Overview & Architecture

`ndev` uses a modular architecture:
- **Core Stack**: `nginx`, `mariadb`, `php` (multi-version FastCGI/FPM), `phpmyadmin`, `ngrok`.
- **Dynamic Modules**: Pluggable services (`mailpit`, `redis`, `postgres`, `mongodb`, or community modules) located in `<userdir>/.ndev/modules/<module_name>/`.

Modules are discovered dynamically at runtime. When `ndev` starts (CLI or TUI), it scans the modules directory, parses each `manifest.json`, loads its entrypoint (`module.py`), and provides standard lifecycle commands (`install`, `start`, `stop`, `restart`, `status`, `open`, `uninstall`) as well as interactive UI controls in the **TUI Dashboard (`ndev ui`)**.

---

## 2. Where Modules Live

All dynamic modules reside in:
- **Windows**: `%USERPROFILE%\.ndev\modules\<module_name>\` (e.g., `C:\Users\<user>\.ndev\modules\my-service\`)
- **Linux / macOS**: `~/.ndev/modules/<module_name>/` (e.g., `/home/<user>/.ndev/modules/my-service/`)

You can also override the base directory with the `NDEV_HOME` environment variable:
```bash
export NDEV_HOME=/custom/path/.ndev
```

### Module Directory Structure
```text
~/.ndev/modules/<module_name>/
├── manifest.json       # (Required) Module configuration & metadata
├── module.py           # (Required) Python lifecycle handler
├── bin/                # (Optional) Downloaded or extracted portable binaries
├── data/               # (Optional) Persistent state or database storage
├── logs/               # (Optional) Service log files
└── run/                # (Optional) PID and state JSON files
```

---

## 3. Creating a Module (Quick Scaffold)

You can generate a starter module scaffold directly using the CLI:

```bash
ndev module create my-queue --display-name "My Queue Worker" --category queue --port 9001
```

This creates `~/.ndev/modules/my-queue/` with a boilerplate `manifest.json` and `module.py`.

---

## 4. Building `manifest.json`

The `manifest.json` file is required. It declares the metadata, ports, web UI link, and target platforms.

### Manifest Schema & Fields

| Field | Type | Required | Description | Example |
| :--- | :--- | :--- | :--- | :--- |
| `name` | `string` | **Yes** | Unique module identifier (lowercase, hyphens/underscores allowed) | `"rabbitmq"` |
| `display_name` | `string` | **Yes** | Human-readable title shown in CLI and TUI | `"RabbitMQ"` |
| `version` | `string` | **Yes** | Module or software version string | `"3.13.0"` |
| `description` | `string` | No | Short summary of what the service does | `"AMQP message broker"` |
| `category` | `string` | No | Category (`database`, `mail`, `queue`, `tool`, `cache`) | `"queue"` |
| `author` | `string` | No | Author or maintainer attribution | `"RabbitMQ Community"` |
| `homepage` | `string` | No | Project URL or docs link | `"https://www.rabbitmq.com"` |
| `ports` | `object` or `array` | No | TCP ports opened by the service (used for probing) | `{"amqp": 5672, "mgmt": 15672}` |
| `web_ui` | `string` or `null` | No | URL to web dashboard (enables 🌐 Open action) | `"http://127.0.0.1:15672"` |
| `platforms` | `array` | No | Supported OS list: `["windows", "linux", "darwin"]` | `["windows", "linux"]` |
| `entrypoint` | `string` | No | Python file name inside module folder (defaults to `module.py`) | `"module.py"` |

### Example `manifest.json`

```json
{
  "name": "rabbitmq",
  "display_name": "RabbitMQ",
  "version": "3.13.0",
  "description": "Robust and versatile AMQP message broker",
  "category": "queue",
  "author": "RabbitMQ Community",
  "homepage": "https://www.rabbitmq.com",
  "ports": {
    "amqp": 5672,
    "mgmt": 15672
  },
  "web_ui": "http://127.0.0.1:15672",
  "platforms": ["windows", "linux", "darwin"],
  "entrypoint": "module.py"
}
```

---

## 5. Writing `module.py`

The entrypoint file (`module.py`) defines a `Module` class that handles installation, process lifecycle, and status probing.

### Lifecycle Methods Overview

| Method | Return Value | Description |
| :--- | :--- | :--- |
| `is_installed()` | `bool` | Returns whether binaries are downloaded and present. |
| `install(**kwargs)` | `Path` or `bool` | Downloads/extracts binaries or installs system dependencies. |
| `status()` | `dict` | Returns status dictionary (`installed`, `running`, `pid`, `ports`, `details`). |
| `start(**kwargs)` | `int` (PID) or `bool` | Starts the background daemon/process. |
| `stop(**kwargs)` | `bool` | Stops the background process gracefully or by PID/kill. |
| `restart(**kwargs)` | `int` or `bool` | Stops and restarts the process. |
| `open_ui()` | `None` | (Optional) Opens the web dashboard in user's default browser. |
| `uninstall()` | `bool` | (Optional) Removes downloaded binaries and cleans up. |

### Complete `module.py` Template

```python
"""
Lifecycle handler for custom ndev module.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Optional

# ndev helper utilities available for import:
from ndev.common.modules.base import is_port_open, wait_for_port, wait_for_port_closed


class Module:
    def __init__(self, module_dir: Path, manifest: dict) -> None:
        self.module_dir = Path(module_dir).resolve()
        self.manifest = manifest
        self.bin_dir = self.module_dir / "bin"
        self.data_dir = self.module_dir / "data"
        self.logs_dir = self.module_dir / "logs"
        self.run_dir = self.module_dir / "run"
        self.state_file = self.run_dir / f"{self.manifest.get('name', 'service')}.json"

    def _ensure_dirs(self) -> None:
        for d in (self.bin_dir, self.data_dir, self.logs_dir, self.run_dir):
            d.mkdir(parents=True, exist_ok=True)

    def is_installed(self) -> bool:
        """Return True if the binary or runtime dependency is present."""
        exe_name = "mytool.exe" if platform.system() == "Windows" else "mytool"
        return (self.bin_dir / exe_name).exists() or shutil.which(exe_name) is not None

    def install(self, **kwargs) -> Any:
        """Download portable binary or install via package manager."""
        self._ensure_dirs()
        # 1. Download zip or tar.gz binary archive
        # 2. Extract into self.bin_dir
        # 3. Optional: copy CLI tools to ~/.ndev/shims/ for PATH access on Windows
        return True

    def status(self) -> dict:
        """Return status dictionary."""
        installed = self.is_installed()
        if not installed:
            return {
                "name": self.manifest.get("name"),
                "display_name": self.manifest.get("display_name"),
                "installed": False,
                "running": False,
                "pid": None,
                "ports": self.manifest.get("ports", {}),
                "version": self.manifest.get("version", "1.0.0"),
                "web_ui": self.manifest.get("web_ui"),
                "details": "Not installed"
            }

        running = is_port_open(9001)
        return {
            "name": self.manifest.get("name"),
            "display_name": self.manifest.get("display_name"),
            "installed": True,
            "running": running,
            "pid": None,
            "ports": self.manifest.get("ports", {}),
            "version": self.manifest.get("version", "1.0.0"),
            "web_ui": self.manifest.get("web_ui"),
            "details": "Running on Port 9001" if running else "Stopped"
        }

    def start(self, **kwargs) -> Any:
        """Start background process."""
        self._ensure_dirs()
        if not self.is_installed():
            self.install()

        log_path = self.logs_dir / "service.log"
        log_file = open(log_path, "a", encoding="utf-8")

        cmd = [str(self.bin_dir / "mytool"), "--port", "9001"]

        kwargs_proc = {
            "stdout": log_file,
            "stderr": subprocess.STDOUT,
            "cwd": str(self.module_dir),
        }
        if platform.system() == "Windows":
            kwargs_proc["creationflags"] = 0x00000200 | 0x08000000  # CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
        else:
            kwargs_proc["start_new_session"] = True

        proc = subprocess.Popen(cmd, **kwargs_proc)
        wait_for_port(9001, timeout=5.0)
        return proc.pid

    def stop(self, **kwargs) -> bool:
        """Stop process."""
        if platform.system() == "Windows":
            subprocess.run(["taskkill.exe", "/F", "/IM", "mytool.exe"], capture_output=True)
        else:
            subprocess.run(["pkill", "-f", "mytool"], capture_output=True)
        wait_for_port_closed(9001, timeout=2.0)
        return True

    def restart(self, **kwargs) -> Any:
        self.stop()
        time.sleep(0.5)
        return self.start()

    def open_ui(self) -> None:
        """Open web dashboard in browser."""
        import webbrowser
        url = self.manifest.get("web_ui")
        if url:
            webbrowser.open(url)

    def uninstall(self) -> bool:
        """Clean up downloaded binaries and data."""
        self.stop()
        if self.bin_dir.exists():
            shutil.rmtree(self.bin_dir, ignore_errors=True)
        return True
```

---

## 6. Testing & Managing Your Module

### CLI Testing Commands
```bash
# Check if discovered
ndev module list

# Install binaries
ndev module install <module_name>

# Start / Stop / Restart / Status
ndev module start <module_name>
ndev module status <module_name>
ndev module restart <module_name>
ndev module stop <module_name>

# Open Web UI
ndev module open <module_name>

# Direct commands also work seamlessly:
ndev start <module_name>
ndev stop <module_name>
```

### Interactive TUI Dashboard
Launch `ndev ui`. Your module will automatically show up under the Services table with its real-time running/stopped indicator, ports, and action shortcuts (`[S]tart`, `[T] Stop`, `[R] Restart`, `[O] Open UI`).

---

## 7. Distributing Modules

To share a module with other developers:
1. Package the module folder containing `manifest.json` and `module.py`.
2. Users place it into their `~/.ndev/modules/<module_name>/` directory.
3. The module will instantly be loaded and managed by `ndev` CLI and TUI without modifying core code!

