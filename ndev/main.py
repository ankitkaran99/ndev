"""
ndev Main Entrypoint
====================
Detects the host operating system (Windows vs Linux/POSIX)
and dispatches execution to the appropriate platform subsystem:

    ndev
     ├── ndev.common  (shared constants, logger, config, utils)
     ├── ndev.win     (Windows core runtime, CLI, TUI)
     └── ndev.linux   (Linux runtime, PHP-FPM, chroot, CLI, TUI)
"""
from __future__ import annotations

import platform
import sys


def is_windows() -> bool:
    """Return True if running on Windows."""
    return sys.platform == "win32" or platform.system() == "Windows"


def main() -> None:
    """Unified CLI entrypoint for ndev."""
    # Ensure UTF-8 output on Windows consoles
    if is_windows() and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    try:
        if is_windows():
            from ndev.win.cli import main as win_main
            win_main()
        else:
            from ndev.linux.cli import app as linux_app
            linux_app()
    except KeyboardInterrupt:
        sys.exit(130)


# Dynamic application alias
if is_windows():
    pass
else:
    pass


if __name__ == "__main__":
    main()
