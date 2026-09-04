"""
UAC elevation helpers for Windows.

ndev (Linux) shells out to `sudo` for vhost/setup/hosts-file work.
Windows has no equivalent shell primitive: elevation is a distinct
process launch via ShellExecuteW's "runas" verb, which triggers the
UAC prompt. There is no way to elevate an already-running process,
so commands that need admin rights either:

  1. Check is_admin() and relaunch themselves elevated, or
  2. Shell out to a small elevated helper for just the privileged
     step (e.g. writing to the hosts file), keeping the rest of the
     command running unprivileged.

Option 2 is used for hosts / vhost so the bulk of ndev
never needs to run elevated.
"""
from __future__ import annotations

import ctypes
import subprocess
import sys
from pathlib import Path


def is_admin() -> bool:
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def relaunch_as_admin(argv: list[str] | None = None) -> None:
    """Re-invoke the current script elevated, then exit the caller."""
    argv = argv or sys.argv
    params = " ".join(f'"{a}"' for a in argv[1:])
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, f'"{argv[0]}" {params}', None, 1
    )
    sys.exit(0)


def run_elevated(command: list[str], wait: bool = True) -> int:
    """
    Run a single command elevated. If already running as Administrator,
    executes directly without triggering a UAC prompt.
    Otherwise uses ShellExecuteExW with the 'runas' verb.
    """
    if is_admin():
        res = subprocess.run(command)
        return res.returncode

    exe, *args = command
    params = " ".join(f'"{a}"' for a in args)
    SEE_MASK_NOCLOSEPROCESS = 0x00000040

    class SHELLEXECUTEINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", ctypes.c_ulong),
            ("fMask", ctypes.c_ulong),
            ("hwnd", ctypes.c_void_p),
            ("lpVerb", ctypes.c_wchar_p),
            ("lpFile", ctypes.c_wchar_p),
            ("lpParameters", ctypes.c_wchar_p),
            ("lpDirectory", ctypes.c_wchar_p),
            ("nShow", ctypes.c_int),
            ("hInstApp", ctypes.c_void_p),
            ("lpIDList", ctypes.c_void_p),
            ("lpClass", ctypes.c_wchar_p),
            ("hkeyClass", ctypes.c_void_p),
            ("dwHotKey", ctypes.c_ulong),
            ("hIconOrMonitor", ctypes.c_void_p),
            ("hProcess", ctypes.c_void_p),
        ]

    sei = SHELLEXECUTEINFO()
    sei.cbSize = ctypes.sizeof(sei)
    sei.fMask = SEE_MASK_NOCLOSEPROCESS
    sei.lpVerb = "runas"
    sei.lpFile = exe
    sei.lpParameters = params
    sei.nShow = 0

    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(sei)):
        raise OSError("Elevation request was rejected or cancelled (UAC).")

    if wait and sei.hProcess:
        WAIT_INFINITE = 0xFFFFFFFF
        ctypes.windll.kernel32.WaitForSingleObject(sei.hProcess, WAIT_INFINITE)
        exit_code = ctypes.c_ulong(0)
        ctypes.windll.kernel32.GetExitCodeProcess(sei.hProcess, ctypes.byref(exit_code))
        ctypes.windll.kernel32.CloseHandle(sei.hProcess)
        return exit_code.value
    return 0
