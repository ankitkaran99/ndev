"""
PHP version management for Windows using precompiled Windows binaries
from windows.php.net.
"""
from __future__ import annotations

import json
import re
import shutil
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import paths

RELEASES_INDEX_URL = "https://windows.php.net/downloads/releases/releases.json"
ARCHIVES_INDEX_URL = "https://windows.php.net/downloads/releases/archives/"


@dataclass
class PhpRelease:
    version: str          # e.g. "8.4.25"
    major_minor: str      # e.g. "8.4"
    thread_safe: bool     # True for TS, False for NTS
    arch: str             # "x64" or "x86"
    toolset: str          # e.g. "vs17", "vs16", "vc15"
    zip_url: str
    is_archive: bool = False


def _fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "ndev-win/0.1"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _fetch_html(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "ndev-win/0.1"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def list_available(include_archives: bool = False) -> list[PhpRelease]:
    """
    Parse current active releases from windows.php.net's releases.json.
    Optionally includes archived releases.
    """
    try:
        data = _fetch_json(RELEASES_INDEX_URL)
    except Exception:
        data = {}

    releases: list[PhpRelease] = []
    for major_minor, info in data.items():
        if not isinstance(info, dict):
            continue
        ver = info.get("version", major_minor)
        for build_key, build_info in info.items():
            if isinstance(build_info, dict) and "zip" in build_info:
                zip_path = build_info["zip"].get("path", "")
                if not zip_path:
                    continue
                is_nts = "nts" in build_key.lower()
                arch = "x86" if ("x86" in build_key.lower()) else "x64"
                m_tool = re.search(r'(vs\d+|vc\d+)', build_key.lower())
                toolset = m_tool.group(1) if m_tool else ""
                zip_url = f"https://windows.php.net/downloads/releases/{zip_path}"
                releases.append(PhpRelease(
                    version=ver,
                    major_minor=major_minor,
                    thread_safe=not is_nts,
                    arch=arch,
                    toolset=toolset,
                    zip_url=zip_url,
                    is_archive=False,
                ))

    if include_archives:
        releases.extend(list_available_archives())

    return releases


def list_available_archives() -> list[PhpRelease]:
    """Parse archived PHP builds from windows.php.net/downloads/releases/archives/."""
    try:
        html = _fetch_html(ARCHIVES_INDEX_URL)
    except Exception:
        return []

    pattern = re.compile(
        r'href="php-(\d+\.\d+\.\d+)(?:-(nts))?-Win32-([A-Za-z0-9]+)-(x64|x86)\.zip"',
        re.IGNORECASE
    )
    releases: list[PhpRelease] = []
    seen = set()
    for match in pattern.finditer(html):
        ver, nts, toolset, arch = match.groups()
        is_ts = (nts is None)
        key = (ver, is_ts, arch.lower())
        if key in seen:
            continue
        seen.add(key)
        parts = ver.split(".")
        mm = f"{parts[0]}.{parts[1]}"
        filename = match.group(0).split('"')[1]
        releases.append(PhpRelease(
            version=ver,
            major_minor=mm,
            thread_safe=is_ts,
            arch=arch.lower(),
            toolset=toolset.lower(),
            zip_url=f"https://windows.php.net/downloads/releases/archives/{filename}",
            is_archive=True,
        ))
    return releases


def _version_key(v: str) -> tuple[int, ...]:
    parts = []
    for part in v.split("."):
        try:
            parts.append(int(part))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def resolve_release(version_query: str, arch: str = "x64", thread_safe: bool = True) -> PhpRelease | None:
    """
    Resolve a version query (e.g. '8.4', '8.4.25', '7.4') to a matching PhpRelease.
    Checks active releases first, then falls back to archives.
    """
    q = version_query.strip().lower()
    if q.startswith("php-"):
        q = q[4:]
    elif q.startswith("php"):
        q = q[3:]

    # Handle 'latest' keyword
    if q == "latest":
        current_rels = list_available(include_archives=False)
        matches = [r for r in current_rels if r.arch == arch and r.thread_safe == thread_safe]
        if matches:
            matches.sort(key=lambda r: _version_key(r.version), reverse=True)
            return matches[0]

    # 1. Search in active releases
    current_rels = list_available(include_archives=False)
    matches = [
        r for r in current_rels
        if r.arch == arch and r.thread_safe == thread_safe and (
            r.version == q or r.major_minor == q or r.version.startswith(q + ".") or r.major_minor.startswith(q + ".")
        )
    ]
    if matches:
        matches.sort(key=lambda r: _version_key(r.version), reverse=True)
        return matches[0]

    # 2. Search in archives
    arch_rels = list_available_archives()
    matches = [
        r for r in arch_rels
        if r.arch == arch and r.thread_safe == thread_safe and (
            r.version == q or r.major_minor == q or r.version.startswith(q + ".") or r.major_minor.startswith(q + ".")
        )
    ]
    if matches:
        matches.sort(key=lambda r: _version_key(r.version), reverse=True)
        return matches[0]

    # 3. Looser search without TS/arch constraints if none found
    all_rels = current_rels + arch_rels
    any_matches = [
        r for r in all_rels
        if r.version == q or r.major_minor == q or r.version.startswith(q + ".") or r.major_minor.startswith(q + ".")
    ]
    if any_matches:
        any_matches.sort(key=lambda r: _version_key(r.version), reverse=True)
        return any_matches[0]

    return None


def download_release(release: PhpRelease) -> Path:
    paths.ensure_dirs()
    dest = paths.DOWNLOADS_DIR / Path(release.zip_url).name
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    tmp = dest.with_suffix(".part")
    req = urllib.request.Request(release.zip_url, headers={"User-Agent": "ndev-win/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=180) as resp, open(tmp, "wb") as f:
            chunk_size = 65536
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
        if tmp.exists() and tmp.stat().st_size > 0:
            if dest.exists():
                dest.unlink()
            tmp.rename(dest)
        else:
            raise RuntimeError(f"Download from {release.zip_url} resulted in empty file.")
    except Exception:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise
    return dest


def install(version: str, zip_path: Path) -> Path:
    """Extract a downloaded PHP zip into ~/.ndev/php/<version>/ and configure php.ini."""
    target = paths.version_dir(version)
    if target.exists():
        if (target / "php.exe").exists():
            raise FileExistsError(f"PHP {version} is already installed at {target}")
        else:
            shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(target)
    _configure_php_ini(target)

    # If this is the only installed version or no current version set, make it active
    if get_current_version() is None or len(list_installed()) == 1:
        use(version)

    return target


def _configure_php_ini(version_dir: Path) -> None:
    """
    Initialize and optimize php.ini for development:
    - Set extension_dir = "ext"
    - Enable essential extensions (curl, mbstring, mysqli, pdo_mysql, openssl, fileinfo, gd, zip, sodium, exif, intl)
    - Configure FastCGI parameters
    - Increase memory & upload limits
    """
    src_dev = version_dir / "php.ini-development"
    src_prod = version_dir / "php.ini-production"
    dst = version_dir / "php.ini"

    if not dst.exists():
        if src_dev.exists():
            shutil.copyfile(src_dev, dst)
        elif src_prod.exists():
            shutil.copyfile(src_prod, dst)

    if not dst.exists():
        return

    text = dst.read_text(encoding="utf-8", errors="ignore")

    # 1. Enable extension_dir = "ext"
    text = re.sub(r'^[;\s]*extension_dir\s*=\s*"ext"', 'extension_dir = "ext"', text, flags=re.MULTILINE)
    if 'extension_dir = "ext"' not in text:
        text = 'extension_dir = "ext"\n' + text

    # 2. Enable common extensions
    common_extensions = [
        "curl", "fileinfo", "gd", "intl", "mbstring", "exif",
        "mysqli", "openssl", "pdo_mysql", "pdo_sqlite", "sqlite3",
        "sodium", "zip"
    ]
    for ext in common_extensions:
        # If commented out, uncomment it
        text = re.sub(rf'^[;\s]*extension\s*=\s*(?:php_)?{ext}(?:\.dll)?', f'extension={ext}', text, flags=re.MULTILINE)

    # 3. Configure FastCGI, OPcache, CA certs, and dev settings
    replacements = [
        (r'^[;\s]*cgi\.force_redirect\s*=.*', 'cgi.force_redirect = 0'),
        (r'^[;\s]*cgi\.fix_pathinfo\s*=.*', 'cgi.fix_pathinfo = 1'),
        (r'^[;\s]*memory_limit\s*=.*', 'memory_limit = 512M'),
        (r'^[;\s]*upload_max_filesize\s*=.*', 'upload_max_filesize = 128M'),
        (r'^[;\s]*post_max_size\s*=.*', 'post_max_size = 128M'),
        (r'^[;\s]*max_execution_time\s*=.*', 'max_execution_time = 300'),
        (r'^[;\s]*date\.timezone\s*=.*', 'date.timezone = UTC'),
        (r'^[;\s]*opcache\.enable\s*=.*', 'opcache.enable = 1'),
        (r'^[;\s]*opcache\.enable_cli\s*=.*', 'opcache.enable_cli = 1'),
        (r'^[;\s]*opcache\.memory_consumption\s*=.*', 'opcache.memory_consumption = 128'),
        (r'^[;\s]*realpath_cache_size\s*=.*', 'realpath_cache_size = 4096k'),
        (r'^[;\s]*realpath_cache_ttl\s*=.*', 'realpath_cache_ttl = 600'),
        (r'^[;\s]*error_reporting\s*=.*', 'error_reporting = E_ALL'),
        (r'^[;\s]*display_errors\s*=.*', 'display_errors = On'),
        (r'^[;\s]*display_startup_errors\s*=.*', 'display_startup_errors = On'),
        (r'^[;\s]*default_charset\s*=.*', 'default_charset = "UTF-8"'),
        (r'^[;\s]*max_input_vars\s*=.*', 'max_input_vars = 5000'),
    ]
    sessions_dir = paths.SESSIONS_DIR
    sessions_dir.mkdir(parents=True, exist_ok=True)
    clean_sessions = str(sessions_dir.resolve()).replace("\\", "/")
    clean_temp = str(paths.TEMP_DIR.resolve()).replace("\\", "/")
    clean_vdir = str(version_dir.resolve()).replace("\\", "/")

    replacements.extend([
        (r'^[;\s]*session\.save_path\s*=.*', f'session.save_path = "{clean_sessions}"'),
        (r'^[;\s]*sys_temp_dir\s*=.*', f'sys_temp_dir = "{clean_temp}"'),
        (r'^[;\s]*error_log\s*=.*', f'error_log = "{clean_vdir}/php_error.log"'),
    ])

    if paths.CACERT_PATH.exists():
        clean_cacert = str(paths.CACERT_PATH.resolve()).replace("\\", "/")
        replacements.extend([
            (r'^[;\s]*curl\.cainfo\s*=.*', f'curl.cainfo = "{clean_cacert}"'),
            (r'^[;\s]*openssl\.cafile\s*=.*', f'openssl.cafile = "{clean_cacert}"'),
        ])

    for pattern, repl in replacements:
        text = re.sub(pattern, "", text, flags=re.MULTILINE)
        text += f"\n{repl}"

    # Clean up empty lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    dst.write_text(text, encoding="utf-8")


def _kill_processes_in_dir(directory: Path) -> None:
    """Find and terminate any active processes executing binaries from directory."""
    import ctypes
    clean_dir = str(directory.resolve()).lower()
    count = 32768
    pids = (ctypes.c_ulong * count)()
    bytes_returned = ctypes.c_ulong()
    if not ctypes.windll.psapi.EnumProcesses(ctypes.byref(pids), ctypes.sizeof(pids), ctypes.byref(bytes_returned)):
        return
    num_pids = bytes_returned.value // ctypes.sizeof(ctypes.c_ulong)
    for i in range(num_pids):
        pid = pids[i]
        if pid <= 4:
            continue
        h = ctypes.windll.kernel32.OpenProcess(0x1000 | 0x0001, False, pid)  # QUERY_LIMITED_INFO | TERMINATE
        if not h:
            continue
        try:
            buf = (ctypes.c_wchar * 1024)()
            size = ctypes.c_ulong(1024)
            if ctypes.windll.kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                exe_path = buf.value.lower()
                if exe_path.startswith(clean_dir):
                    ctypes.windll.kernel32.TerminateProcess(h, 0)
        finally:
            ctypes.windll.kernel32.CloseHandle(h)


def _safe_rmtree(path: Path, max_retries: int = 6, delay: float = 0.3) -> None:
    """Robustly delete directory tree on Windows handling read-only attributes and transient locks."""
    import gc, stat, time
    if not path.exists():
        return

    def _on_error(fn, p, exc_info):
        try:
            os.chmod(p, stat.S_IWRITE | stat.S_IREAD)
            fn(p)
        except Exception:
            pass

    gc.collect()
    for _ in range(max_retries):
        try:
            if hasattr(shutil, "rmtree") and "onexc" in shutil.rmtree.__code__.co_varnames:
                shutil.rmtree(path, onexc=lambda fn, p, err: (os.chmod(p, 0o777), fn(p)))
            else:
                shutil.rmtree(path, onerror=_on_error)
            return
        except Exception:
            time.sleep(delay)
            gc.collect()

    # Final fallback via cmd rmdir /s /q
    try:
        subprocess.run(["cmd.exe", "/c", "rmdir", "/s", "/q", str(path)], capture_output=True, timeout=10)
    except Exception:
        pass

    if path.exists():
        shutil.rmtree(path)


def uninstall(version: str) -> None:
    """Stop any running pool and remove the installed PHP version."""
    resolved_ver = version
    try:
        resolved_ver = resolve_installed(version)
    except Exception:
        pass

    # Stop FastCGI pool for this version
    from . import fcgi
    try:
        fcgi.stop(resolved_ver)
    except Exception:
        pass

    # Stop phpMyAdmin if it was running on this PHP version
    try:
        from . import pma
        pma_st = pma.status()
        if pma_st and pma_st.get("php_version") == resolved_ver:
            pma.stop()
    except Exception:
        pass

    target = paths.version_dir(resolved_ver)
    if not target.exists():
        raise FileNotFoundError(f"PHP {version} is not installed")

    # Terminate any remaining processes holding file locks in this directory
    _kill_processes_in_dir(target)
    
    # Safely remove the directory tree
    _safe_rmtree(target)

    # If this was the active version, clear current or switch to another
    if paths.get_current_version() == resolved_ver:
        remaining = list_installed()
        if remaining:
            use(remaining[-1])
        else:
            if paths.CURRENT_FILE.exists():
                paths.CURRENT_FILE.unlink(missing_ok=True)
            # Remove all PHP and Composer shims
            for shim in [
                "php.bat", "php.cmd", "php.ps1",
                "php-cgi.bat", "php-cgi.cmd", "php-cgi.ps1",
                "composer.bat", "composer.cmd", "composer.ps1",
            ]:
                (paths.SHIM_DIR / shim).unlink(missing_ok=True)


def list_installed() -> list[str]:
    """Return sorted list of locally installed PHP versions."""
    if not paths.PHP_DIR.exists():
        return []
    versions = [p.name for p in paths.PHP_DIR.iterdir() if p.is_dir() and (p / "php.exe").exists()]
    return sorted(versions, key=_version_key)


def resolve_installed(version_query: str) -> str:
    """Resolve an installed PHP version query (e.g. '8.4', '8.4.25', '8') to the exact installed version string."""
    installed = list_installed()
    if not installed:
        raise FileNotFoundError("No PHP versions are currently installed. Run `ndev install <version>` first.")

    q = version_query.strip().lower()
    if q.startswith("php-"):
        q = q[4:]
    elif q.startswith("php"):
        q = q[3:]

    # Exact match first
    for v in installed:
        if v.lower() == q:
            return v

    # Prefix / major.minor match in reverse order (newest patch first)
    matches = [
        v for v in installed
        if v == q or v.startswith(q + ".") or (len(v.split(".")) >= 2 and f"{v.split('.')[0]}.{v.split('.')[1]}" == q)
    ]
    if matches:
        matches.sort(key=_version_key, reverse=True)
        return matches[0]

    raise FileNotFoundError(
        f"PHP version matching '{version_query}' is not installed. Installed versions: {', '.join(installed)}"
    )


def php_exe(version: str) -> Path:
    target_ver = version
    try:
        target_ver = resolve_installed(version)
    except Exception:
        pass
    return paths.version_dir(target_ver) / "php.exe"


def php_cgi_exe(version: str) -> Path:
    target_ver = version
    try:
        target_ver = resolve_installed(version)
    except Exception:
        pass
    return paths.version_dir(target_ver) / "php-cgi.exe"


def get_current_version() -> str | None:
    return paths.get_current_version()


def use(version: str) -> str:
    """
    Point ndev shims (on PATH) at this version's php.exe and php-cgi.exe.
    Generates php.bat, php.cmd, php-cgi.bat, and composer.bat in ~/.ndev/shims.
    Returns the resolved version string.
    """
    resolved_ver = resolve_installed(version)
    paths.ensure_dirs()
    
    exe_path = str(paths.version_dir(resolved_ver) / "php.exe")
    cgi_path = str(paths.version_dir(resolved_ver) / "php-cgi.exe")

    # php.bat, php.cmd, php.ps1
    (paths.SHIM_DIR / "php.bat").write_text(f'@echo off\r\n"{exe_path}" %*\r\n', encoding="utf-8")
    (paths.SHIM_DIR / "php.cmd").write_text(f'@echo off\r\n"{exe_path}" %*\r\n', encoding="utf-8")
    (paths.SHIM_DIR / "php.ps1").write_text(f'& "{exe_path}" @args\r\n', encoding="utf-8")

    # php-cgi.bat, php-cgi.cmd, php-cgi.ps1
    (paths.SHIM_DIR / "php-cgi.bat").write_text(f'@echo off\r\n"{cgi_path}" %*\r\n', encoding="utf-8")
    (paths.SHIM_DIR / "php-cgi.cmd").write_text(f'@echo off\r\n"{cgi_path}" %*\r\n', encoding="utf-8")
    (paths.SHIM_DIR / "php-cgi.ps1").write_text(f'& "{cgi_path}" @args\r\n', encoding="utf-8")

    # If composer.phar is present, create/update composer shims
    composer_phar = paths.SHIM_DIR / "composer.phar"
    if composer_phar.exists():
        clean_phar = str(composer_phar.resolve()).replace("\\", "/")
        (paths.SHIM_DIR / "composer.bat").write_text(
            f'@echo off\r\n"{exe_path}" "{clean_phar}" %*\r\n', encoding="utf-8"
        )
        (paths.SHIM_DIR / "composer.cmd").write_text(
            f'@echo off\r\n"{exe_path}" "{clean_phar}" %*\r\n', encoding="utf-8"
        )
        (paths.SHIM_DIR / "composer.ps1").write_text(
            f'& "{exe_path}" "{clean_phar}" @args\r\n', encoding="utf-8"
        )

    paths.set_current_version(resolved_ver)
    return resolved_ver
