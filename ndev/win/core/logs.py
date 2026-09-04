"""
Log viewing utilities for ndev-win.
"""
from __future__ import annotations

from pathlib import Path

from . import paths, php


def get_available_logs() -> dict[str, Path]:
    """Return dictionary of log name -> log file Path."""
    logs: dict[str, Path] = {}

    # Nginx logs
    if paths.NGINX_LOGS_DIR.exists():
        for p in paths.NGINX_LOGS_DIR.glob("*.log"):
            logs[f"nginx:{p.stem}"] = p

    # MariaDB logs
    if paths.MARIADB_DIR.exists():
        data_dir = paths.MARIADB_DIR / "data"
        if data_dir.exists():
            for p in data_dir.glob("*.err"):
                logs[f"mariadb:{p.stem}"] = p

    # Redis logs
    if paths.REDIS_DIR.exists():
        for p in paths.REDIS_DIR.glob("*.log"):
            logs[f"redis:{p.stem}"] = p

    # PHP logs (look in ~/.ndev/php/<version>/ or ~/.ndev/run/ / temp)
    for v in php.list_installed():
        v_dir = paths.version_dir(v)
        for log_candidate in [v_dir / "php_error.log", v_dir / "error.log"]:
            if log_candidate.exists():
                logs[f"php:{v}"] = log_candidate

    return logs



def read_log_tail(log_path: Path, lines: int = 50) -> list[str]:
    """Efficiently read the last N lines of a file without loading large files into memory."""
    if not log_path.exists():
        return []
    try:
        file_size = log_path.stat().st_size
        if file_size == 0:
            return []

        # Read backward in chunks from the end of the file
        chunk_size = 8192
        chunks: list[bytes] = []
        newlines_found = 0
        with log_path.open("rb") as f:
            pos = file_size
            while pos > 0 and newlines_found <= lines:
                read_len = min(chunk_size, pos)
                pos -= read_len
                f.seek(pos)
                chunk = f.read(read_len)
                chunks.append(chunk)
                newlines_found += chunk.count(b"\n")

        raw = b"".join(reversed(chunks))
        text = raw.decode("utf-8", errors="ignore")
        all_lines = text.splitlines()
        return all_lines[-lines:]
    except Exception:
        return []
