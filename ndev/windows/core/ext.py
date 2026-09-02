"""
PECL extension manager for Windows (precompiled DLL downloads from downloads.php.net).
"""
from __future__ import annotations

import re
import shutil
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Optional

from . import paths, php

PECL_RELEASES_BASE = "https://downloads.php.net/~windows/pecl/releases"
KNOWN_TOOLSETS = ["vs17", "vs16", "vc15", "vc14", "vc11"]


def _http_get_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "ndev-win/0.1"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def list_ext_versions(ext: str) -> list[str]:
    """Directory listing of available versions for a PECL extension."""
    try:
        html = _http_get_text(f"{PECL_RELEASES_BASE}/{ext}/")
    except Exception as e:
        raise RuntimeError(f"Could not fetch PECL listing for '{ext}': {e}")
    raw_versions = set(re.findall(r'href="([\d][\w.\-]*)/"', html))
    return sorted(raw_versions, key=php._version_key)


def _is_thread_safe(php_version: str) -> bool:
    target_ver = php_version
    try:
        target_ver = php.resolve_installed(php_version)
    except Exception:
        pass
    import subprocess
    exe = php.php_exe(target_ver)
    if exe.exists():
        try:
            out = subprocess.run([str(exe), "-i"], capture_output=True, text=True, timeout=10).stdout
            if "Thread Safety => disabled" in out:
                return False
            if "Thread Safety => enabled" in out:
                return True
        except Exception:
            pass
    # ndev-win installs Thread Safe (TS) builds by default
    return True


def find_release_zip(
    ext: str,
    ext_version: Optional[str],
    php_version: str,
    arch: str = "x64",
    thread_safe: Optional[bool] = None,
) -> str:
    major_minor = ".".join(php_version.split(".")[:2])
    is_ts = thread_safe if thread_safe is not None else _is_thread_safe(php_version)
    ts_tag = "ts" if is_ts else "nts"

    # If no extension version specified, search versions in descending order
    versions = [ext_version] if ext_version else list_ext_versions(ext)[::-1]
    if not versions:
        raise FileNotFoundError(f"No versions found on PECL for extension '{ext}'")

    for v in versions:
        if not v:
            continue
        dir_url = f"{PECL_RELEASES_BASE}/{ext}/{v}/"
        try:
            html = _http_get_text(dir_url)
        except Exception:
            continue
        available = set(re.findall(r'href="(php_[\w.\-]+\.zip)"', html))

        for toolset in KNOWN_TOOLSETS:
            name = f"php_{ext}-{v}-{major_minor}-{ts_tag}-{toolset}-{arch}.zip"
            if name in available:
                return dir_url + name
            # Also try case-insensitive or without arch if matching
            for avail_name in available:
                if avail_name.lower() == name.lower():
                    return dir_url + avail_name

    raise FileNotFoundError(
        f"No precompiled {ext} build found for PHP {major_minor} ({ts_tag}, {arch}). "
        f"Checked versions: {versions[:5]}"
    )


def install(
    ext: str,
    ext_version: Optional[str],
    php_version: str,
    arch: str = "x64",
    thread_safe: Optional[bool] = None,
) -> Path:
    zip_url = find_release_zip(ext, ext_version, php_version, arch, thread_safe)
    zip_path = paths.DOWNLOADS_DIR / Path(zip_url).name
    if not zip_path.exists() or zip_path.stat().st_size == 0:
        req = urllib.request.Request(zip_url, headers={"User-Agent": "ndev-win/0.1"})
        tmp = zip_path.with_suffix(".part")
        try:
            with urllib.request.urlopen(req, timeout=90) as resp, open(tmp, "wb") as f:
                chunk_size = 65536
                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
            if tmp.exists() and tmp.stat().st_size > 0:
                if zip_path.exists():
                    zip_path.unlink()
                tmp.rename(zip_path)
            else:
                raise RuntimeError(f"Download from {zip_url} resulted in empty file.")
        except Exception:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
            raise

    ext_dir = paths.version_dir(php_version) / "ext"
    ext_dir.mkdir(parents=True, exist_ok=True)

    v_dir = paths.version_dir(php_version)
    with zipfile.ZipFile(zip_path) as zf:
        dll_names = [n for n in zf.namelist() if n.lower().endswith(".dll")]
        if not dll_names:
            raise RuntimeError(f"No .dll found inside {zip_path.name}")
        for name in dll_names:
            data = zf.read(name)
            filename = Path(name).name
            if filename.lower().startswith("php_"):
                (ext_dir / filename).write_bytes(data)
            else:
                # Place runtime dependency DLLs (e.g. libssh2.dll) in PHP root for Windows DLL loader
                (v_dir / filename).write_bytes(data)

    enable(ext, php_version)
    return ext_dir


def _ini_path(php_version: str) -> Path:
    target_ver = php_version
    try:
        target_ver = php.resolve_installed(php_version)
    except Exception:
        pass
    return paths.version_dir(target_ver) / "php.ini"


ZEND_EXTENSIONS = {"xdebug", "opcache"}


def enable(ext: str, php_version: str) -> None:
    ini = _ini_path(php_version)
    if not ini.exists():
        return
    text = ini.read_text(encoding="utf-8", errors="ignore")
    directive = "zend_extension" if ext.lower() in ZEND_EXTENSIONS else "extension"
    
    # Check if already enabled
    pattern_active = rf"^\s*(?:extension|zend_extension)\s*=\s*(?:php_)?{re.escape(ext)}(?:\.dll)?\s*$"
    if re.search(pattern_active, text, flags=re.MULTILINE):
        return

    # Check if disabled with semicolon
    pattern_disabled = rf"^\s*;\s*(?:extension|zend_extension)\s*=\s*(?:php_)?{re.escape(ext)}(?:\.dll)?\s*$"
    if re.search(pattern_disabled, text, flags=re.MULTILINE):
        text = re.sub(pattern_disabled, f"{directive}={ext}", text, flags=re.MULTILINE)
    else:
        text += f"\n{directive}={ext}\n"

    ini.write_text(text, encoding="utf-8")


def disable(ext: str, php_version: str) -> None:
    ini = _ini_path(php_version)
    if not ini.exists():
        return
    text = ini.read_text(encoding="utf-8", errors="ignore")
    pattern_active = rf"^\s*((?:extension|zend_extension)\s*=\s*(?:php_)?{re.escape(ext)}(?:\.dll)?)\s*$"
    if re.search(pattern_active, text, flags=re.MULTILINE):
        text = re.sub(pattern_active, r";\1", text, flags=re.MULTILINE)
        ini.write_text(text, encoding="utf-8")


def uninstall(ext: str, php_version: str) -> None:
    target_ver = php_version
    try:
        target_ver = php.resolve_installed(php_version)
    except Exception:
        pass
    disable(ext, target_ver)
    ext_dir = paths.version_dir(target_ver) / "ext"
    if ext_dir.exists():
        for dll in ext_dir.glob(f"*{ext}*.dll"):
            try:
                dll.unlink()
            except Exception:
                pass


def list_status(php_version: str) -> dict[str, bool]:
    """Returns {ext_name: enabled} for all detected extensions in php.ini and ext/ folder."""
    target_ver = php_version
    try:
        target_ver = php.resolve_installed(php_version)
    except Exception:
        pass

    status: dict[str, bool] = {}
    ext_dir = paths.version_dir(target_ver) / "ext"
    if ext_dir.exists():
        for dll in ext_dir.glob("*.dll"):
            name = dll.stem
            if name.startswith("php_"):
                name = name[4:]
            status[name] = False

    ini = _ini_path(target_ver)
    if ini.exists():
        for line in ini.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            m = re.match(r"^(;)?\s*(?:extension|zend_extension)\s*=\s*(?:php_)?(\S+?)(?:\.dll)?\s*$", line)
            if m:
                name = m.group(2)
                # Filter out comment placeholders or paths in default template php.ini
                if "/" in name or "\\" in name or name in ("modulename", "php_modulename", "dl_test"):
                    continue
                is_enabled = m.group(1) is None
                status[name] = is_enabled

    return dict(sorted(status.items()))
