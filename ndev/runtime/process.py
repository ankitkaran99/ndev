import os
import signal
from pathlib import Path
from ndev.logger import logger

def is_pid_running(pid: int) -> bool:
    """Check if a process is running on POSIX systems."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False

def read_pid_file(pid_file: Path) -> int | None:
    """Read a PID from a file."""
    if not pid_file.exists():
        return None
    try:
        content = pid_file.read_text().strip()
        if content.isdigit():
            return int(content)
    except Exception:
        pass
    return None

def kill_process(pid: int, sig=signal.SIGTERM) -> bool:
    """Send signal to process. Return True if successful."""
    try:
        os.kill(pid, sig)
        return True
    except ProcessLookupError:
        return False
    except PermissionError as e:
        logger.error(f"Permission denied to signal process {pid}: {e}")
        return False
