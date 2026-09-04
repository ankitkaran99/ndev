"""
Cross-platform Textual TUI dashboard entrypoint for ndev.
Auto-detects host operating system and launches the corresponding TUI implementation.
"""
from __future__ import annotations

import platform


def run_dashboard() -> None:
    """Launch the interactive Textual TUI stack monitor for the current OS."""
    if platform.system() == "Windows":
        from ndev.win.tui import NdevDashboard
        app = NdevDashboard()
        app.run()
    else:
        from ndev.linux.tui import NdevDashboard
        app = NdevDashboard()
        app.run()


if __name__ == "__main__":
    run_dashboard()
