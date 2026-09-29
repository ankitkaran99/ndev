"""
shim generator and manager for ndev on Windows.

Provides native Windows .exe shims using shim.exe + <name>.shim config pairs.
"""
from __future__ import annotations

import filecmp
import ntpath
import os
import re
import shutil
import sys
import warnings
from pathlib import Path

from . import paths

# By default, use ndev's central SHIM_DIR
SHIM_DIR = paths.SHIM_DIR


def _find_shim_exe() -> Path:
    """Find prebuilt shim.exe binary across installed package or repository."""
    # 1. Check explicit environment override
    env_exe = os.environ.get("NDEV_SHIM_EXE")
    if env_exe:
        p = Path(env_exe)
        if p.exists():
            return p

    # 2. Check bundled package binary (ndev/win/bin/shim.exe)
    pkg_exe = Path(__file__).parent.parent / "bin" / "shim.exe"
    if pkg_exe.exists():
        return pkg_exe

    # 3. Check development repository root (shimgen/shim.exe)
    repo_exe = Path(__file__).resolve().parent.parent.parent.parent / "shimgen" / "shim.exe"
    if repo_exe.exists():
        return repo_exe

    return pkg_exe


SHIM_EXE = _find_shim_exe()

_NAME_RE = re.compile(r"^[\w.+\-]+$")

_RESERVED = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


def _check_name(name: str) -> str:
    if (
        not _NAME_RE.match(name)
        or name.endswith(".")
        or name.split(".")[0].lower() in _RESERVED
    ):
        raise ValueError(f"invalid shim name: {name!r}")
    return name


def _write(path: Path, text: str, encoding: str = "utf-8") -> None:
    """Atomic write: a shim starting mid-update never sees a half-written file."""
    tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    with open(tmp, "w", encoding=encoding, newline="\r\n") as f:
        f.write(text)
    try:
        os.replace(tmp, path)
    except OSError:
        # Fallback if target is momentarily locked
        try:
            if path.exists():
                _unlink(path)
            os.replace(tmp, path)
        except OSError:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            raise


def _unlink(p: Path) -> bool:
    """Delete p. A running .exe can't be deleted on Windows but can be renamed,
    so rename it out of the way and sweep it later."""
    if not p.exists():
        return False
    try:
        p.unlink()
    except PermissionError:
        try:
            os.replace(p, p.with_name(f"{p.name}.old-{os.getpid()}"))
        except OSError:
            pass
    except OSError:
        return False
    return True


def _sweep(shim_dir: Path) -> None:
    for p in shim_dir.glob("*.old-*"):
        try:
            p.unlink()
        except OSError:
            pass  # still running; sweep next time


def _same(a: Path, b: Path) -> bool:
    try:
        return os.path.samefile(a, b) or filecmp.cmp(a, b, shallow=False)
    except OSError:
        return False


def _install_exe(dst: Path) -> None:
    if dst.exists():
        if _same(SHIM_EXE, dst):
            return  # already current (also avoids touching an exe that is running)
        try:
            os.replace(dst, dst.with_name(f"{dst.name}.old-{os.getpid()}"))
        except OSError:
            pass
    try:
        os.link(SHIM_EXE, dst)  # hard link: fast, zero disk copy overhead
    except OSError:
        shutil.copyfile(SHIM_EXE, dst)  # cross-volume or non-NTFS fallback


def create(
    name: str,
    target: str | Path,
    args: str = "",
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
    path_prepend: str | Path | None = None,
    shim_dir: Path | None = None,
    clean_legacy: bool = True,
) -> Path:
    """Create or update a native Windows .exe shim in shim_dir (defaults to ~/.ndev/shims).

    Returns the path to the generated <shim_dir>/<name>.exe.
    """
    _check_name(name)
    shim_dir = Path(shim_dir or SHIM_DIR)
    shim_dir.mkdir(parents=True, exist_ok=True)
    target = str(target)
    env = env or {}

    if not (ntpath.isabs(target) or target.startswith("%")):
        raise ValueError(f"shim target must be an absolute Windows path, got {target!r}")
    if not os.path.isfile(os.path.expandvars(target)):
        warnings.warn(f"shim target does not exist (yet): {target}", stacklevel=2)

    _sweep(shim_dir)

    if not SHIM_EXE.is_file():
        raise FileNotFoundError(f"shim.exe not found at {SHIM_EXE}; build or place shim.exe first")

    lines = [f"path = {target}"]
    if args:
        lines.append(f"args = {args}")
    if cwd:
        lines.append(f"cwd = {cwd}")
    if path_prepend:
        lines.append(f"path_prepend = {path_prepend}")
    lines += [f"env.{k} = {v}" for k, v in sorted(env.items())]

    # Write config first, exe second: the exe never exists without its config
    _write(shim_dir / f"{name}.shim", "\n".join(lines) + "\n")
    _install_exe(shim_dir / f"{name}.exe")

    # Clean legacy script shims (.cmd, .bat, .ps1)
    if clean_legacy:
        _unlink(shim_dir / f"{name}.cmd")
        _unlink(shim_dir / f"{name}.bat")
        _unlink(shim_dir / f"{name}.ps1")

    return shim_dir / f"{name}.exe"


def remove(name: str, shim_dir: Path | None = None) -> bool:
    """Remove all shims and configs for `name` (.exe, .shim, .cmd, .bat, .ps1)."""
    _check_name(name)
    shim_dir = Path(shim_dir or SHIM_DIR)
    removed = False
    for ext in (".exe", ".shim", ".cmd", ".bat", ".ps1"):
        removed |= _unlink(shim_dir / f"{name}{ext}")
    return removed


def read_shim(name: str, shim_dir: Path | None = None) -> dict[str, str]:
    """Read a .shim config file into a dictionary."""
    shim_dir = Path(shim_dir or SHIM_DIR)
    cfg: dict[str, str] = {}
    p = shim_dir / f"{name}.shim"
    if p.exists():
        try:
            for line in p.read_text(encoding="utf-8-sig").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    cfg[k.strip()] = v.strip()
        except OSError:
            pass
    return cfg


def list_shims(shim_dir: Path | None = None) -> dict[str, str]:
    """Return dict of {name: target_path_or_description} for all native shims."""
    shim_dir = Path(shim_dir or SHIM_DIR)
    if not shim_dir.is_dir():
        return {}
    out: dict[str, str] = {}

    for p in sorted(shim_dir.iterdir()):
        if p.suffix.lower() == ".exe" and (shim_dir / f"{p.stem}.shim").exists():
            cfg = read_shim(p.stem, shim_dir)
            t = cfg.get("path", "?")
            out[p.stem] = (
                t
                if os.path.isfile(os.path.expandvars(t)) or sys.platform != "win32"
                else f"{t}  [MISSING]"
            )

    return out


def ensure_on_path(shim_dir: Path | None = None) -> bool:
    """Add the shim directory to the HKCU user PATH registry if not already present.
    Normalizes slashes/case, skips duplicate additions, and broadcasts WM_SETTINGCHANGE.
    Returns True if user PATH was updated, False if already present.
    """
    if sys.platform != "win32":
        return False

    import ctypes
    import winreg
    from ctypes import wintypes

    shim_dir_str = str(Path(shim_dir or SHIM_DIR).resolve())

    def norm(p: str) -> str:
        return os.path.normcase(os.path.normpath(os.path.expandvars(p.strip().rstrip("\\/"))))

    norm_target = norm(shim_dir_str)

    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_READ | winreg.KEY_WRITE
    ) as key:
        try:
            cur, typ = winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            cur, typ = "", winreg.REG_EXPAND_SZ

        parts = [p.strip() for p in cur.split(";") if p.strip()]
        if any(norm(p) == norm_target for p in parts):
            return False

        # Prepend to front so ndev shims take precedence
        parts.insert(0, shim_dir_str)
        winreg.SetValueEx(key, "Path", 0, typ, ";".join(parts))

    try:
        send = ctypes.windll.user32.SendMessageTimeoutW
        send.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPCWSTR,
            wintypes.UINT,
            wintypes.UINT,
            ctypes.POINTER(wintypes.DWORD),
        ]
        send.restype = wintypes.LPARAM
        result = wintypes.DWORD()
        send(0xFFFF, 0x001A, 0, "Environment", 2, 5000, ctypes.byref(result))  # HWND_BROADCAST, WM_SETTINGCHANGE
    except Exception:
        pass

    return True
