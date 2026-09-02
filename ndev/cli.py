"""
Cross-platform CLI entrypoint for ndev.
Auto-detects the host operating system (Windows vs. Linux/POSIX)
and dispatches commands to the appropriate platform runtime engine.
"""
from __future__ import annotations

import platform
import sys


def main() -> None:
    """Main CLI entrypoint for ndev."""
    if platform.system() == "Windows":
        from ndev.windows.cli import main as win_main
        win_main()
    else:
        from ndev.linux_cli import app as linux_app
        linux_app()


# Compatibility aliases for direct imports or runners
if platform.system() == "Windows":
    from ndev.windows.cli import main as app
else:
    from ndev.linux_cli import app

if __name__ == "__main__":
    main()
