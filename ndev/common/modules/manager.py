"""
Module manager for discovering, loading, and managing ndev dynamic modules.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import NdevModule


def get_user_ndev_dir() -> Path:
    """Returns ~/.ndev directory for the current user."""
    ndev_home = os.environ.get("NDEV_HOME")
    if ndev_home:
        return Path(ndev_home).resolve()
    
    # On Linux check SUDO_USER if running elevated
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user and sys.platform.startswith("linux"):
        try:
            import pwd
            return Path(pwd.getpwnam(sudo_user).pw_dir) / ".ndev"
        except Exception:
            pass
            
    return Path(os.path.expanduser("~/.ndev")).resolve()


def get_modules_dir() -> Path:
    """Returns <userdir>/.ndev/modules directory."""
    d = get_user_ndev_dir() / "modules"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_builtin_modules_dir() -> Path:
    """Returns directory containing built-in default modules."""
    return Path(__file__).parent / "builtin"


def seed_builtin_modules() -> None:
    """Seeds default built-in modules (mailpit, redis, postgres) into <userdir>/.ndev/modules/."""
    builtin_dir = get_builtin_modules_dir()
    if not builtin_dir.exists():
        return
    
    modules_dir = get_modules_dir()
    for child in builtin_dir.iterdir():
        if child.is_dir() and (child / "manifest.json").exists():
            dest = modules_dir / child.name
            manifest_dest = dest / "manifest.json"
            if not dest.exists() or not manifest_dest.exists():
                dest.mkdir(parents=True, exist_ok=True)
                for item in child.iterdir():
                    target_item = dest / item.name
                    if not target_item.exists():
                        if item.is_dir():
                            shutil.copytree(item, target_item)
                        else:
                            shutil.copy2(item, target_item)


class ModuleManager:
    """Manages all registered dynamic modules in ~/.ndev/modules/."""

    def __init__(self, modules_dir: Optional[Path] = None) -> None:
        self.modules_dir = Path(modules_dir) if modules_dir else get_modules_dir()
        self._ensure_seeded()

    def _ensure_seeded(self) -> None:
        try:
            seed_builtin_modules()
        except Exception:
            pass

    def load_module_from_dir(self, module_dir: Path) -> Optional[NdevModule]:
        """Loads a single module from its directory containing manifest.json."""
        manifest_file = module_dir / "manifest.json"
        if not manifest_file.exists():
            return None
        
        try:
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        except Exception:
            return None

        handler = None
        entrypoint = manifest.get("entrypoint", "module.py")
        if entrypoint:
            entrypoint_path = module_dir / entrypoint
            if entrypoint_path.exists():
                try:
                    mod_name = f"ndev_dynamic_module_{module_dir.name.replace('-', '_')}"
                    spec = importlib.util.spec_from_file_location(mod_name, str(entrypoint_path))
                    if spec and spec.loader:
                        py_mod = importlib.util.module_from_spec(spec)
                        sys.modules[mod_name] = py_mod
                        spec.loader.exec_module(py_mod)
                        if hasattr(py_mod, "Module"):
                            handler = py_mod.Module(module_dir=module_dir, manifest=manifest)
                        else:
                            handler = py_mod
                except Exception as e:
                    # Keep handler as None, module can still provide manifest metadata
                    pass

        return NdevModule(module_dir=module_dir, manifest=manifest, handler_instance=handler)

    def list_modules(self) -> List[NdevModule]:
        """Returns all valid modules found in ~/.ndev/modules/."""
        self._ensure_seeded()
        modules: List[NdevModule] = []
        if not self.modules_dir.exists():
            return modules

        for child in sorted(self.modules_dir.iterdir()):
            if child.is_dir() and (child / "manifest.json").exists():
                mod = self.load_module_from_dir(child)
                if mod and mod.is_supported_platform:
                    modules.append(mod)
        return modules

    def get_module(self, name: str) -> Optional[NdevModule]:
        """Finds a module by name (case-insensitive)."""
        target = name.strip().lower()
        for mod in self.list_modules():
            if mod.name.lower() == target:
                return mod
        # Try direct directory lookup
        direct_dir = self.modules_dir / target
        if direct_dir.exists() and (direct_dir / "manifest.json").exists():
            return self.load_module_from_dir(direct_dir)
        return None

    def create_module_scaffold(self, name: str, display_name: Optional[str] = None,
                               port: Optional[int] = None, description: str = "") -> Path:
        """Scaffolds a new module directory with manifest.json and module.py."""
        clean_name = name.strip().lower().replace(" ", "-")
        disp = display_name or clean_name.replace("-", " ").title()
        mod_dir = self.modules_dir / clean_name
        mod_dir.mkdir(parents=True, exist_ok=True)

        manifest = {
            "name": clean_name,
            "display_name": disp,
            "version": "1.0.0",
            "description": description or f"{disp} module for ndev",
            "category": "utility",
            "author": os.environ.get("USERNAME") or os.environ.get("USER") or "user",
            "homepage": "",
            "ports": {clean_name: port} if port else {},
            "web_ui": f"http://localhost:{port}" if port else None,
            "platforms": ["all"],
            "entrypoint": "module.py"
        }

        (mod_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        py_template = f'''"""
Module handler for {disp}
"""
from __future__ import annotations
from pathlib import Path
from typing import Any, Optional


class Module:
    def __init__(self, module_dir: Path, manifest: dict) -> None:
        self.module_dir = Path(module_dir)
        self.manifest = manifest

    def is_installed(self) -> bool:
        return True

    def install(self, **kwargs) -> bool:
        return True

    def start(self, **kwargs) -> Any:
        return True

    def stop(self, **kwargs) -> bool:
        return True

    def restart(self, **kwargs) -> Any:
        self.stop(**kwargs)
        return self.start(**kwargs)

    def status(self) -> dict:
        return {{
            "installed": True,
            "running": False,
            "pid": None,
            "details": "Stopped"
        }}
'''
        (mod_dir / "module.py").write_text(py_template, encoding="utf-8")
        return mod_dir


# Global singleton instance
_module_manager: Optional[ModuleManager] = None


def get_module_manager() -> ModuleManager:
    global _module_manager
    if _module_manager is None:
        _module_manager = ModuleManager()
    return _module_manager
