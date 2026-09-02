"""
phpMyAdmin management as a background service using PHP's built-in web server.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import urllib.request
import zipfile
from pathlib import Path
from typing import Optional

from . import fcgi, paths, php

DOWNLOAD_URL_TMPL = "https://files.phpmyadmin.net/phpMyAdmin/{version}/phpMyAdmin-{version}-english.zip"
DEFAULT_VERSION = "5.2.3"
DEFAULT_PORT = 8080

PMA_DIR = paths.PMA_DIR
_STATE_FILE = paths.RUN_DIR / "pma.json"

CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000


def install(version: str = DEFAULT_VERSION) -> Path:
    paths.ensure_dirs()
    url = DOWNLOAD_URL_TMPL.format(version=version)
    zip_path = paths.DOWNLOADS_DIR / f"phpMyAdmin-{version}.zip"
    if not zip_path.exists():
        req = urllib.request.Request(url, headers={"User-Agent": "ndev-win/0.1"})
        tmp = zip_path.with_suffix(".part")
        with urllib.request.urlopen(req, timeout=180) as resp, open(tmp, "wb") as f:
            shutil.copyfileobj(resp, f)
        tmp.rename(zip_path)

    if PMA_DIR.exists():
        shutil.rmtree(PMA_DIR)
    PMA_DIR.mkdir(parents=True)

    extract_tmp = paths.DOWNLOADS_DIR / "_extract_pma"
    if extract_tmp.exists():
        shutil.rmtree(extract_tmp)

    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(extract_tmp)

    # Move inner extracted dir contents to PMA_DIR
    inner_dirs = [d for d in extract_tmp.iterdir() if d.is_dir()]
    if inner_dirs:
        for item in inner_dirs[0].iterdir():
            shutil.move(str(item), str(PMA_DIR / item.name))
    else:
        for item in extract_tmp.iterdir():
            shutil.move(str(item), str(PMA_DIR / item.name))

    shutil.rmtree(extract_tmp, ignore_errors=True)
    _write_config()
    return PMA_DIR


def _get_or_create_blowfish_secret() -> str:
    import re, secrets
    cfg_file = PMA_DIR / "config.inc.php"
    if cfg_file.exists():
        try:
            content = cfg_file.read_text(encoding="utf-8", errors="ignore")
            m = re.search(r"\$cfg\['blowfish_secret'\]\s*=\s*'([^']+)'", content)
            if m and len(m.group(1)) >= 16:
                return m.group(1)
        except Exception:
            pass
    return secrets.token_hex(16)


def _write_config(mariadb_port: int = 3306) -> None:
    secret = _get_or_create_blowfish_secret()
    tmp_dir = PMA_DIR / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    clean_tmp = str(tmp_dir.resolve()).replace("\\", "/")
    config = f"""<?php
$cfg['blowfish_secret'] = '{secret}';
$i = 0;
$i++;
$cfg['Servers'][$i]['auth_type'] = 'cookie';
$cfg['Servers'][$i]['host'] = '127.0.0.1';
$cfg['Servers'][$i]['port'] = {mariadb_port};
$cfg['Servers'][$i]['compress'] = false;
$cfg['Servers'][$i]['AllowNoPassword'] = true;
$cfg['TempDir'] = '{clean_tmp}';
$cfg['SendErrorReports'] = 'never';
$cfg['ShowPhpInfo'] = true;
$cfg['MaxRows'] = 50;
$cfg['UploadDir'] = '';
$cfg['SaveDir'] = '';
"""
    (PMA_DIR / "config.inc.php").write_text(config, encoding="utf-8")


def start(php_version: Optional[str] = None, port: int = DEFAULT_PORT) -> int:
    if not PMA_DIR.exists() or not (PMA_DIR / "index.php").exists():
        install()

    # Check if already running
    st = status()
    if st:
        raise RuntimeError(f"phpMyAdmin is already running at http://127.0.0.1:{st['port']} (PID {st['pid']})")

    # Check if target port is in use
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        if s.connect_ex(("127.0.0.1", port)) == 0:
            raise RuntimeError(f"Port {port} is already in use by another application.")

    version = php_version or paths.get_current_version()
    if not version:
        installed = php.list_installed()
        if installed:
            version = installed[-1]
        else:
            raise RuntimeError("No PHP version installed -- run `ndev install <version>` first")

    exe = php.php_exe(version)
    if not exe.exists():
        raise FileNotFoundError(f"PHP binary not found for version {version} at {exe}")

    proc = subprocess.Popen(
        [str(exe), "-S", f"127.0.0.1:{port}", "-t", str(PMA_DIR)],
        creationflags=CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW,
    )
    paths.ensure_dirs()
    state_data = {"pid": proc.pid, "port": port, "php_version": version, "url": f"http://127.0.0.1:{port}"}
    _STATE_FILE.write_text(json.dumps(state_data, indent=2), encoding="utf-8")
    return proc.pid


def stop() -> None:
    import ctypes
    if not _STATE_FILE.exists():
        return
    try:
        state = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        pid = state.get("pid")
        if pid and fcgi.is_pid_alive(pid, expected_name="php"):
            terminated = False
            try:
                handle = ctypes.windll.kernel32.OpenProcess(0x0001, False, pid)
                if handle:
                    ctypes.windll.kernel32.TerminateProcess(handle, 0)
                    ctypes.windll.kernel32.CloseHandle(handle)
                    terminated = True
            except Exception:
                pass
            if not terminated or fcgi.is_pid_alive(pid, expected_name="php"):
                try:
                    subprocess.run(["taskkill.exe", "/F", "/PID", str(pid), "/T"], capture_output=True)
                except Exception:
                    pass
    except Exception:
        pass
    _STATE_FILE.unlink(missing_ok=True)


def status() -> dict | None:
    if not _STATE_FILE.exists():
        return None
    try:
        state = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        pid = state.get("pid")
        if pid and fcgi.is_pid_alive(pid):
            return state
    except Exception:
        pass
    _STATE_FILE.unlink(missing_ok=True)
    return None


def restart(php_version: Optional[str] = None, port: int = DEFAULT_PORT) -> int:
    import socket as _socket, time as _time
    stop()
    # Wait up to 3 s for the port to be released before attempting start
    for _ in range(6):
        with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as s:
            s.settimeout(0.3)
            if s.connect_ex(("127.0.0.1", port)) != 0:
                break  # port is free
        _time.sleep(0.5)
    return start(php_version, port)
