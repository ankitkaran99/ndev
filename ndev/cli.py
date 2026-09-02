"""
Cross-platform CLI entrypoint for ndev.
Auto-detects the host operating system (Windows vs. Linux/POSIX)
and dispatches commands to the appropriate platform runtime engine.
"""
from __future__ import annotations

import platform
import sys

# Ensure UTF-8 output on Windows consoles to prevent glyph corruption
if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def main() -> None:
    """Main CLI entrypoint for ndev."""
    try:
        if platform.system() == "Windows":
            from ndev.windows.cli import main as win_main
            win_main()
        else:
            from ndev.linux_cli import app as linux_app
            linux_app()
    except KeyboardInterrupt:
        sys.exit(130)


# Compatibility aliases for direct imports or runners
if platform.system() == "Windows":
    from ndev.windows.cli import main as app
else:
    from ndev.linux_cli import app

if __name__ == "__main__":
    main()
