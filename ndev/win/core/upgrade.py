"""
Component version check and upgrade management for Windows.
Manages updates for Nginx, Mailpit, MariaDB, phpMyAdmin, mkcert, and Composer.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from typing import Optional

import httpx

from . import mailpit as mailpit_core, paths, pma as pma_core, redis_core, services, setup as setup_core


USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ndev/0.1.0"


@dataclass
class ComponentInfo:
    name: str
    display_name: str
    current_version: Optional[str]
    latest_version: Optional[str]
    update_available: bool
    installed: bool
    status: str
    error: Optional[str] = None


def _http_get_json(url: str, timeout: int = 15) -> dict:
    headers = {"User-Agent": USER_AGENT}
    with httpx.Client(follow_redirects=True, timeout=timeout) as client:
        resp = client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.json()


def _http_get_text(url: str, timeout: int = 15) -> str:
    headers = {"User-Agent": USER_AGENT}
    with httpx.Client(follow_redirects=True, timeout=timeout) as client:
        resp = client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.text



def _clean_ver(v: Optional[str]) -> str:
    if not v:
        return ""
    v = v.strip().lower()
    if v.startswith("v"):
        v = v[1:]
    # Remove git commit hashes or dates, e.g. "2.10.3 2026-..."
    return v.split()[0]


# ── COMPONENT DETECTORS & UPDATERS ──────────────────────────────────────────

# 1. NGINX
def get_nginx_info() -> ComponentInfo:
    installed = services.nginx_is_installed()
    curr_ver = None
    latest_ver = None
    err = None

    if installed:
        try:
            res = subprocess.run([str(services.nginx_exe()), "-v"], capture_output=True, text=True, timeout=5)
            out = res.stderr or res.stdout
            m = re.search(r"nginx/(\d+\.\d+\.\d+)", out)
            if m:
                curr_ver = m.group(1)
        except Exception as e:
            err = str(e)

    try:
        html = _http_get_text("https://nginx.org/en/download.html")
        matches = re.findall(r"nginx-(\d+\.\d+\.\d+)\.zip", html)
        if matches:
            latest_ver = matches[0]
        else:
            latest_ver = setup_core.DEFAULT_NGINX_VERSION
    except Exception as e:
        latest_ver = setup_core.DEFAULT_NGINX_VERSION
        if not err:
            err = f"Could not query remote version: {e}"

    update_avail = False
    if curr_ver and latest_ver and _clean_ver(curr_ver) != _clean_ver(latest_ver):
        update_avail = True

    status = "Up-to-date"
    if not installed:
        status = "Not Installed"
    elif update_avail:
        status = f"Update Available ({curr_ver} -> {latest_ver})"

    return ComponentInfo("nginx", "Nginx Web Server", curr_ver, latest_ver, update_avail, installed, status, err)


def upgrade_nginx() -> tuple[bool, str]:
    was_running = services.nginx_is_running()
    if was_running:
        services.nginx_stop()

    info = get_nginx_info()
    target_ver = info.latest_version or setup_core.DEFAULT_NGINX_VERSION

    # 1. Create a persistent safety backup of conf/
    conf_dir = paths.NGINX_DIR / "conf"
    if conf_dir.exists() and any(conf_dir.iterdir()):
        import datetime
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dest = paths.BACKUPS_DIR / f"nginx_conf_{ts}"
        try:
            shutil.copytree(conf_dir, backup_dest)
        except Exception:
            pass

    try:
        setup_core.install_nginx(version=target_ver)

        if was_running:
            services.nginx_start()

        return True, f"Nginx upgraded successfully to {target_ver} (configuration preserved)."
    except Exception as e:
        if was_running:
            try:
                services.nginx_start()
            except Exception:
                pass
        return False, f"Nginx upgrade failed: {e}"


# 2. MAILPIT
def get_mailpit_info() -> ComponentInfo:
    installed = mailpit_core.is_installed()
    curr_ver = None
    latest_ver = None
    err = None

    if installed:
        try:
            res = subprocess.run([str(mailpit_core.BINARY_PATH), "version"], capture_output=True, text=True, timeout=5)
            out = res.stdout.strip() or res.stderr.strip()
            m = re.search(r"v?(\d+\.\d+\.\d+)", out)
            if m:
                curr_ver = f"v{m.group(1)}"
            else:
                curr_ver = out
        except Exception as e:
            err = str(e)

    try:
        rel = mailpit_core._fetch_latest_release()
        latest_ver = rel.get("tag_name")
    except Exception as e:
        if not err:
            err = f"Could not query GitHub releases: {e}"

    update_avail = False
    if curr_ver and latest_ver and _clean_ver(curr_ver) != _clean_ver(latest_ver):
        update_avail = True

    status = "Up-to-date"
    if not installed:
        status = "Not Installed"
    elif update_avail:
        status = f"Update Available ({curr_ver} -> {latest_ver})"

    return ComponentInfo("mailpit", "Mailpit Email Sandbox", curr_ver, latest_ver, update_avail, installed, status, err)


def upgrade_mailpit() -> tuple[bool, str]:
    was_running = bool(mailpit_core.status())
    if was_running:
        mailpit_core.stop()

    try:
        paths.ensure_dirs()
        release = mailpit_core._fetch_latest_release()
        version = release.get("tag_name", "unknown")
        asset = mailpit_core._find_windows_asset(release)
        if not asset:
            raise RuntimeError("No Windows asset found in latest Mailpit release.")

        url = asset["browser_download_url"]
        dl_path = paths.DOWNLOADS_DIR / asset["name"]
        if dl_path.exists():
            dl_path.unlink()

        setup_core._download(url, dl_path)
        with zipfile.ZipFile(dl_path) as zf:
            for member in zf.namelist():
                if member.lower().endswith(".exe") and "mailpit" in member.lower():
                    with zf.open(member) as src, open(mailpit_core.BINARY_PATH, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    break

        if was_running:
            mailpit_core.start()

        return True, f"Mailpit upgraded successfully to {version}."
    except Exception as e:
        if was_running:
            try:
                mailpit_core.start()
            except Exception:
                pass
        return False, f"Mailpit upgrade failed: {e}"


# 3. MARIADB
def get_mariadb_info() -> ComponentInfo:
    installed = services.mariadb_is_installed()
    curr_ver = None
    latest_ver = None
    err = None

    if installed:
        try:
            mysqld = paths.MARIADB_DIR / "bin" / "mariadbd.exe"
            if not mysqld.exists():
                mysqld = paths.MARIADB_DIR / "bin" / "mysqld.exe"
            if mysqld.exists():
                res = subprocess.run([str(mysqld), "--version"], capture_output=True, text=True, timeout=5)
                m = re.search(r"(\d+\.\d+\.\d+)", res.stdout or res.stderr)
                if m:
                    curr_ver = m.group(1)
        except Exception as e:
            err = str(e)

    try:
        data = _http_get_json("https://downloads.mariadb.org/rest-api/mariadb/11.4/")
        releases = list(data.get("releases", {}).keys())
        if releases:
            latest_ver = releases[0]
        else:
            latest_ver = setup_core.DEFAULT_MARIADB_VERSION
    except Exception as e:
        latest_ver = setup_core.DEFAULT_MARIADB_VERSION
        if not err:
            err = f"Could not query MariaDB release API: {e}"

    update_avail = False
    if curr_ver and latest_ver and _clean_ver(curr_ver) != _clean_ver(latest_ver):
        update_avail = True

    status = "Up-to-date"
    if not installed:
        status = "Not Installed"
    elif update_avail:
        status = f"Update Available ({curr_ver} -> {latest_ver})"

    return ComponentInfo("mariadb", "MariaDB Server", curr_ver, latest_ver, update_avail, installed, status, err)


def upgrade_mariadb() -> tuple[bool, str]:
    mb_st = services.mariadb_status()
    was_running = mb_st and mb_st.get("running")
    if was_running:
        services.mariadb_stop()

    info = get_mariadb_info()
    target_ver = info.latest_version or setup_core.DEFAULT_MARIADB_VERSION

    # 1. Create a persistent safety snapshot backup of data/ and my.ini
    data_dir = paths.MARIADB_DIR / "data"
    my_ini = paths.MARIADB_DIR / "my.ini"
    if data_dir.exists() and any(data_dir.iterdir()):
        import datetime
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dest = paths.BACKUPS_DIR / f"mariadb_backup_{ts}"
        try:
            backup_dest.mkdir(parents=True, exist_ok=True)
            shutil.copytree(data_dir, backup_dest / "data")
            if my_ini.exists():
                shutil.copy2(my_ini, backup_dest / "my.ini")
        except Exception:
            pass

    try:
        setup_core.install_mariadb(version=target_ver)

        if was_running:
            services.mariadb_start()

        return True, f"MariaDB upgraded successfully to {target_ver} (database and configuration preserved)."
    except Exception as e:
        if was_running:
            try:
                services.mariadb_start()
            except Exception:
                pass
        return False, f"MariaDB upgrade failed: {e}"


# 4. PHPMYADMIN
def get_pma_info() -> ComponentInfo:
    installed = (paths.PMA_DIR / "index.php").exists()
    curr_ver = None
    latest_ver = None
    err = None

    if installed:
        for f in paths.PMA_DIR.glob("RELEASE-DATE-*"):
            curr_ver = f.name.replace("RELEASE-DATE-", "")
            break
        if not curr_ver:
            curr_ver = pma_core.DEFAULT_VERSION

    try:
        data = _http_get_json("https://www.phpmyadmin.net/home_page/version.json")
        latest_ver = data.get("version", pma_core.DEFAULT_VERSION)
    except Exception as e:
        latest_ver = pma_core.DEFAULT_VERSION
        if not err:
            err = f"Could not query PMA version API: {e}"

    update_avail = False
    if curr_ver and latest_ver and _clean_ver(curr_ver) != _clean_ver(latest_ver):
        update_avail = True

    status = "Up-to-date"
    if not installed:
        status = "Not Installed"
    elif update_avail:
        status = f"Update Available ({curr_ver} -> {latest_ver})"

    return ComponentInfo("pma", "PMA (phpMyAdmin)", curr_ver, latest_ver, update_avail, installed, status, err)


def upgrade_pma() -> tuple[bool, str]:
    was_running = bool(pma_core.status())
    if was_running:
        pma_core.stop()

    info = get_pma_info()
    target_ver = info.latest_version or pma_core.DEFAULT_VERSION

    # 1. Create safety backup of config.inc.php
    config_inc = paths.PMA_DIR / "config.inc.php"
    config_backup = None
    if config_inc.exists():
        import datetime
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        config_backup = paths.BACKUPS_DIR / f"pma_config_{ts}.inc.php"
        try:
            shutil.copy2(config_inc, config_backup)
        except Exception:
            pass

    try:
        pma_core.install(version=target_ver)
        if config_backup and config_backup.exists():
            shutil.copy2(config_backup, paths.PMA_DIR / "config.inc.php")

        if was_running:
            pma_core.start()

        return True, f"PMA upgraded successfully to {target_ver} (configuration preserved)."
    except Exception as e:
        if was_running:
            try:
                pma_core.start()
            except Exception:
                pass
        return False, f"PMA upgrade failed: {e}"


# 5. MKCERT
def get_mkcert_info() -> ComponentInfo:
    mkcert_exe = paths.SHIM_DIR / "mkcert.exe"
    installed = mkcert_exe.exists()
    curr_ver = None
    latest_ver = None
    err = None

    if installed:
        try:
            res = subprocess.run([str(mkcert_exe), "-version"], capture_output=True, text=True, timeout=5)
            curr_ver = res.stdout.strip() or res.stderr.strip()
        except Exception as e:
            err = str(e)

    try:
        rel = _http_get_json("https://api.github.com/repos/FiloSottile/mkcert/releases/latest")
        latest_ver = rel.get("tag_name")
    except Exception as e:
        latest_ver = f"v{setup_core.DEFAULT_MKCERT_VERSION}"
        if not err:
            err = f"Could not query GitHub releases: {e}"

    update_avail = False
    if curr_ver and latest_ver and _clean_ver(curr_ver) != _clean_ver(latest_ver):
        update_avail = True

    status = "Up-to-date"
    if not installed:
        status = "Not Installed"
    elif update_avail:
        status = f"Update Available ({curr_ver} -> {latest_ver})"

    return ComponentInfo("mkcert", "mkcert Local SSL", curr_ver, latest_ver, update_avail, installed, status, err)


def upgrade_mkcert() -> tuple[bool, str]:
    info = get_mkcert_info()
    target_ver = _clean_ver(info.latest_version) or setup_core.DEFAULT_MKCERT_VERSION
    try:
        setup_core.install_mkcert(version=target_ver)
        return True, f"mkcert upgraded successfully to v{target_ver}."
    except Exception as e:
        return False, f"mkcert upgrade failed: {e}"


# 6. COMPOSER
def get_composer_info() -> ComponentInfo:
    phar = paths.SHIM_DIR / "composer.phar"
    installed = phar.exists()
    curr_ver = None
    latest_ver = None
    err = None

    if installed:
        try:
            bat = paths.SHIM_DIR / "composer.bat"
            res = subprocess.run([str(bat), "--version", "--no-ansi"], capture_output=True, text=True, timeout=10)
            raw = (res.stdout or "") + "\n" + (res.stderr or "")
            # Strip ANSI escape sequences if any exist
            clean_text = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", raw)
            m = re.search(r"Composer\s+(?:version\s+)?(\d+\.\d+\.\d+)", clean_text, re.IGNORECASE)
            if m:
                curr_ver = m.group(1)
        except Exception as e:
            err = str(e)


    try:
        data = _http_get_json("https://getcomposer.org/versions")
        stables = data.get("stable", [])
        if stables:
            latest_ver = stables[0].get("version")
    except Exception as e:
        if not err:
            err = f"Could not query Composer versions API: {e}"

    update_avail = False
    if curr_ver and latest_ver and _clean_ver(curr_ver) != _clean_ver(latest_ver):
        update_avail = True

    status = "Up-to-date"
    if not installed:
        status = "Not Installed"
    elif update_avail:
        status = f"Update Available ({curr_ver} -> {latest_ver})"

    return ComponentInfo("composer", "Composer PHP Package Manager", curr_ver, latest_ver, update_avail, installed, status, err)


def upgrade_composer() -> tuple[bool, str]:
    try:
        bat = paths.SHIM_DIR / "composer.bat"
        if bat.exists():
            res = subprocess.run([str(bat), "self-update"], capture_output=True, text=True, timeout=60)
            if res.returncode == 0:
                info = get_composer_info()
                return True, f"Composer upgraded successfully ({info.current_version})."

        setup_core.install_composer()
        info = get_composer_info()
        return True, f"Composer upgraded successfully ({info.current_version or info.latest_version})."
    except Exception as e:
        return False, f"Composer upgrade failed: {e}"


# 7. REDIS
def get_redis_info() -> ComponentInfo:
    installed = redis_core.is_installed()
    curr_ver = None
    latest_ver = None
    err = None

    if installed:
        try:
            res = subprocess.run([str(redis_core.server_exe()), "--version"], capture_output=True, text=True, timeout=5)
            m = re.search(r"v=(\d+\.\d+\.\d+)", res.stdout or res.stderr)
            if m:
                curr_ver = m.group(1)
        except Exception as e:
            err = str(e)

    try:
        rel = _http_get_json("https://api.github.com/repos/redis-windows/redis-windows/releases/latest")
        latest_ver = rel.get("tag_name", redis_core.DEFAULT_VERSION)
    except Exception as e:
        latest_ver = redis_core.DEFAULT_VERSION
        if not err:
            err = f"Could not query Redis release API: {e}"

    update_avail = False
    if curr_ver and latest_ver and _clean_ver(curr_ver) != _clean_ver(latest_ver):
        update_avail = True

    status = "Up-to-date"
    if not installed:
        status = "Not Installed"
    elif update_avail:
        status = f"Update Available ({curr_ver} -> {latest_ver})"

    return ComponentInfo("redis", "Redis In-Memory Database", curr_ver, latest_ver, update_avail, installed, status, err)


def upgrade_redis() -> tuple[bool, str]:
    was_running = bool(redis_core.status())
    if was_running:
        redis_core.stop()

    info = get_redis_info()
    target_ver = info.latest_version or redis_core.DEFAULT_VERSION
    try:
        redis_core.install(version=target_ver)
        if was_running:
            redis_core.start()
        return True, f"Redis upgraded successfully to {target_ver}."
    except Exception as e:
        if was_running:
            try:
                redis_core.start()
            except Exception:
                pass
        return False, f"Redis upgrade failed: {e}"


# ── UNIFIED API ─────────────────────────────────────────────────────────────

COMPONENTS = ["nginx", "mailpit", "mariadb", "pma", "redis", "mkcert", "composer"]


def check_all() -> list[ComponentInfo]:
    """Inspect installed versions and query latest upstream releases for all stack components."""
    results = [
        get_nginx_info(),
        get_mailpit_info(),
        get_mariadb_info(),
        get_pma_info(),
        get_redis_info(),
        get_mkcert_info(),
        get_composer_info(),
    ]
    return results


def upgrade_component(name: str) -> tuple[bool, str]:
    name = name.lower()
    if name == "nginx":
        return upgrade_nginx()
    elif name in ["mailpit", "mail"]:
        return upgrade_mailpit()
    elif name in ["mariadb", "mysql"]:
        return upgrade_mariadb()
    elif name in ["pma", "phpmyadmin"]:
        return upgrade_pma()
    elif name == "redis":
        return upgrade_redis()
    elif name == "mkcert":
        return upgrade_mkcert()
    elif name == "composer":
        return upgrade_composer()
    else:
        return False, f"Unknown component '{name}'. Available: {', '.join(COMPONENTS)}"



def upgrade_all() -> dict[str, tuple[bool, str]]:
    results = {}
    for comp in COMPONENTS:
        results[comp] = upgrade_component(comp)
    return results
