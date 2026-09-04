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


from ndev.main import main, app

if __name__ == "__main__":
    main()
