"""
shimgen - shim generator for ndev-win.

A shim is a tiny launcher in one shared directory (on PATH) that forwards to the
real executable, so ndev can switch versions (php 8.2 -> 8.3) by rewriting a
text file instead of touching PATH.

Kinds:
  exe  - hard-links (or copies) a prebuilt shim.exe to <name>.exe and writes
         <name>.shim. Proper stdio/exit-code/Ctrl+C handling; no
         "Terminate batch job (Y/N)?" prompt.
  cmd  - writes <name>.cmd. No binary needed; fallback when shim.exe is missing.

Library:
    import shimgen
    shimgen.create("php", r"C:\\ndev\\php\\8.3\\php.exe",
                   args=r"-c C:\\ndev\\php\\8.3\\php.ini",
                   path_prepend=r"C:\\ndev\\php\\8.3")
    shimgen.remove("php"); shimgen.list_shims()

CLI:
    python shimgen.py add php C:\\ndev\\php\\8.3\\php.exe --prepend C:\\ndev\\php\\8.3
    python shimgen.py add php ... --args=-v      (use '=' when the value starts with '-')
    python shimgen.py ls | rm php | init
"""
from __future__ import annotations

import argparse
import filecmp
import ntpath
import os
import re
import shutil
import sys
import warnings
from pathlib import Path

# Adjust to wherever ndev-win keeps its state.
SHIM_DIR = Path(os.path.expandvars(
    os.environ.get("NDEV_SHIM_DIR", str(Path.home() / ".ndev" / "shims"))))
SHIM_EXE = Path(os.environ.get("NDEV_SHIM_EXE", Path(__file__).with_name("shim.exe")))

_NAME_RE = re.compile(r"^[\w.+\-]+$")
_CMD_ENCODING = "oem" if sys.platform == "win32" else "utf-8"  # cmd reads .cmd files as OEM


# --------------------------------------------------------------------------- helpers

_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
             *(f"lpt{i}" for i in range(1, 10))}


def _check_name(name: str) -> str:
    if (not _NAME_RE.match(name) or name.endswith(".")
            or name.split(".")[0].lower() in _RESERVED):
        raise ValueError(f"invalid shim name: {name!r}")
    return name


def _write(path: Path, text: str, encoding="utf-8"):
    """Atomic write: a shim starting mid-update never sees a half-written file."""
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding=encoding, newline="\r\n") as f:
        f.write(text)
    os.replace(tmp, path)


def _unlink(p: Path) -> bool:
    """Delete p. A *running* .exe can't be deleted on Windows but can be renamed,
    so rename it out of the way and sweep it later."""
    if not p.exists():
        return False
    try:
        p.unlink()
    except PermissionError:
        os.replace(p, p.with_name(f"{p.name}.old-{os.getpid()}"))
    return True


def _sweep(shim_dir: Path):
    for p in shim_dir.glob("*.old-*"):
        try:
            p.unlink()
        except OSError:
            pass  # still running; next time


def _same(a: Path, b: Path) -> bool:
    try:
        return os.path.samefile(a, b) or filecmp.cmp(a, b, shallow=False)
    except OSError:
        return False


def _install_exe(dst: Path):
    if dst.exists():
        if _same(SHIM_EXE, dst):
            return  # already current (also avoids touching an exe that is running)
        os.replace(dst, dst.with_name(f"{dst.name}.old-{os.getpid()}"))
    try:
        os.link(SHIM_EXE, dst)  # hard link: no extra disk, GetModuleFileName still gives dst
    except OSError:
        shutil.copyfile(SHIM_EXE, dst)  # different volume / FS without links


_VAR_OR_PCT = re.compile(r"(%[A-Za-z_][A-Za-z0-9_]*%)|%")


def _bat_escape(s: str) -> str:
    """Escape literal '%' for a .cmd file but keep %VAR% references live, matching
    how shim.exe expands %VAR% in the .shim values."""
    return _VAR_OR_PCT.sub(lambda m: m.group(1) or "%%", s)


# --------------------------------------------------------------------------- API

def create(name, target, args="", cwd=None, env=None, path_prepend=None,
           kind="auto", shim_dir: Path = None) -> Path:
    """Create or update a shim. Returns the file that goes on PATH."""
    _check_name(name)
    shim_dir = Path(shim_dir or SHIM_DIR)
    shim_dir.mkdir(parents=True, exist_ok=True)
    target = str(target)
    env = env or {}

    if not (ntpath.isabs(target) or target.startswith("%")):  # "%NDEV_HOME%\\x.exe" is fine
        # A bare name like "php" would be resolved via PATH, find this very shim
        # first (the shim dir is on PATH), and launch itself forever.
        raise ValueError(f"shim target must be an absolute Windows path, got {target!r}")
    if not os.path.isfile(os.path.expandvars(target)):
        warnings.warn(f"shim target does not exist (yet): {target}", stacklevel=2)

    if kind == "auto":
        kind = "exe" if SHIM_EXE.is_file() else "cmd"

    _sweep(shim_dir)

    if kind == "exe":
        if not SHIM_EXE.is_file():
            raise FileNotFoundError(f"shim.exe not found at {SHIM_EXE}; build shim.c first")
        lines = [f"path = {target}"]
        if args:
            lines.append(f"args = {args}")
        if cwd:
            lines.append(f"cwd = {cwd}")
        if path_prepend:
            lines.append(f"path_prepend = {path_prepend}")
        lines += [f"env.{k} = {v}" for k, v in env.items()]
        # config first, exe second: the exe never exists without its config
        _write(shim_dir / f"{name}.shim", "\n".join(lines) + "\n")
        _install_exe(shim_dir / f"{name}.exe")
        _unlink(shim_dir / f"{name}.cmd")  # stray from a previous kind
        return shim_dir / f"{name}.exe"

    if kind == "cmd":
        body = ["@echo off", "setlocal"]
        body += [f'set "{k}={v}"' for k, v in env.items()]
        if path_prepend:
            body.append(f'set "PATH={_bat_escape(path_prepend)};%PATH%"')
        if cwd:
            body.append(f'cd /d "{_bat_escape(cwd)}"')
        body.append(f'"{_bat_escape(target)}" {args} %*')
        body.append("exit /b %ERRORLEVEL%")
        out = shim_dir / f"{name}.cmd"
        _write(out, "\n".join(body) + "\n", encoding=_CMD_ENCODING)
        _unlink(shim_dir / f"{name}.exe")  # exe would shadow the .cmd via PATHEXT
        _unlink(shim_dir / f"{name}.shim")
        return out

    raise ValueError(f"unknown kind: {kind}")


def remove(name, shim_dir: Path = None) -> bool:
    _check_name(name)
    shim_dir = Path(shim_dir or SHIM_DIR)
    removed = False
    for ext in (".exe", ".shim", ".cmd"):
        removed |= _unlink(shim_dir / f"{name}{ext}")
    return removed


def read_shim(name, shim_dir: Path = None) -> dict:
    shim_dir = Path(shim_dir or SHIM_DIR)
    cfg = {}
    p = shim_dir / f"{name}.shim"
    if p.exists():
        for line in p.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip()
    return cfg


def list_shims(shim_dir: Path = None) -> dict[str, str]:
    """Returns {name: target}."""
    shim_dir = Path(shim_dir or SHIM_DIR)
    if not shim_dir.is_dir():
        return {}
    out = {}
    for p in sorted(shim_dir.iterdir()):
        if p.suffix.lower() == ".exe" and (shim_dir / f"{p.stem}.shim").exists():
            t = read_shim(p.stem, shim_dir).get("path", "?")
            out[p.stem] = t if os.path.isfile(os.path.expandvars(t)) or sys.platform != "win32" else f"{t}  [MISSING]"
        elif p.suffix.lower() == ".cmd":
            out[p.stem] = "(cmd shim)"
    return out


def ensure_on_path(shim_dir: Path = None) -> bool:
    """Add the shim dir to the *user* PATH (registry). Returns True if changed."""
    import ctypes
    import winreg
    from ctypes import wintypes

    shim_dir = str(Path(shim_dir or SHIM_DIR))

    def norm(p):
        return os.path.normcase(os.path.normpath(os.path.expandvars(p)))

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0,
                        winreg.KEY_READ | winreg.KEY_WRITE) as key:
        try:
            cur, typ = winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            cur, typ = "", winreg.REG_EXPAND_SZ
        parts = [p for p in cur.split(";") if p]
        if any(norm(p) == norm(shim_dir) for p in parts):
            return False
        parts.insert(0, shim_dir)  # front, so shims win over system installs
        winreg.SetValueEx(key, "Path", 0, typ, ";".join(parts))

    # tell Explorer / new terminals to reload the environment
    send = ctypes.windll.user32.SendMessageTimeoutW
    send.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPCWSTR,
                     wintypes.UINT, wintypes.UINT, ctypes.POINTER(wintypes.DWORD)]
    send.restype = wintypes.LPARAM
    send(0xFFFF, 0x001A, 0, "Environment", 2, 5000, None)  # HWND_BROADCAST, WM_SETTINGCHANGE
    return True


# --------------------------------------------------------------------------- CLI

def main(argv=None):
    ap = argparse.ArgumentParser(prog="shimgen")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="create/update a shim")
    a.add_argument("name")
    a.add_argument("target")
    a.add_argument("--args", default="")
    a.add_argument("--cwd")
    a.add_argument("--prepend", help="dir to prepend to PATH for the target")
    a.add_argument("--env", action="append", default=[], metavar="K=V")
    a.add_argument("--kind", choices=["auto", "exe", "cmd"], default="auto")

    r = sub.add_parser("rm", help="remove a shim")
    r.add_argument("name")

    sub.add_parser("ls", help="list shims")
    sub.add_parser("init", help="add shim dir to user PATH")

    warnings.showwarning = lambda m, *a, **k: print(f"warning: {m}", file=sys.stderr)
    ns = ap.parse_args(argv)

    if ns.cmd == "add":
        env = {}
        for e in ns.env:
            if "=" not in e:
                ap.error(f"--env expects K=V, got {e!r}")
            k, v = e.split("=", 1)
            env[k] = v
        print(f"created {create(ns.name, ns.target, ns.args, ns.cwd, env, ns.prepend, ns.kind)}")
    elif ns.cmd == "rm":
        print("removed" if remove(ns.name) else "no such shim")
    elif ns.cmd == "ls":
        for n, t in list_shims().items():
            print(f"{n:<20} -> {t}")
    elif ns.cmd == "init":
        print("PATH updated; open a new terminal" if ensure_on_path() else "already on PATH")


if __name__ == "__main__":
    sys.exit(main())
