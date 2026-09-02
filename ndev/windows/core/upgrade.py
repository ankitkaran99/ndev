"""
Component version check and upgrade management for Windows.
Manages updates for Nginx, Mailpit, MariaDB, phpMyAdmin, mkcert, and Composer.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import fcgi, logs, mailpit as mailpit_core, paths, pma as pma_core, services, setup as setup_core

USER_AGENT = "ndev/0.1.0"


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


def _http_get_json(url: str, timeout: int = 10) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_get_text(url: str, timeout: int = 10) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="ignore")


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

    # Backup existing configuration
    conf_backup = None
    conf_dir = paths.NGINX_DIR / "conf"
    if conf_dir.exists():
        conf_backup = paths.DOWNLOADS_DIR / "_nginx_conf_backup"
        if conf_backup.exists():
            shutil.rmtree(conf_backup)
        shutil.copytree(conf_dir, conf_backup)

    try:
        url = f"https://nginx.org/download/nginx-{target_ver}.zip"
        zip_path = setup_core._download(url, paths.DOWNLOADS_DIR / f"nginx-{target_ver}.zip")
        setup_core._extract_zip_flatten_single_root(zip_path, paths.NGINX_DIR)

        # Restore configuration and vhosts
        if conf_backup and conf_backup.exists():
            if (conf_backup / "nginx.conf").exists():
                shutil.copy(conf_backup / "nginx.conf", conf_dir / "nginx.conf")
            if (conf_backup / "ndev-vhosts").exists():
                if (conf_dir / "ndev-vhosts").exists():
                    shutil.rmtree(conf_dir / "ndev-vhosts")
                shutil.copytree(conf_backup / "ndev-vhosts", conf_dir / "ndev-vhosts")
            shutil.rmtree(conf_backup, ignore_errors=True)

        setup_core._include_vhosts_in_main_conf()

        if was_running:
            services.nginx_start()

        return True, f"Nginx upgraded successfully to {target_ver}."
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

    # Preserve data/ directory and my.ini
    data_dir = paths.MARIADB_DIR / "data"
    my_ini = paths.MARIADB_DIR / "my.ini"

    data_backup = None
    ini_backup = None

    if data_dir.exists() and any(data_dir.iterdir()):
        data_backup = paths.DOWNLOADS_DIR / "_mariadb_data_backup"
        if data_backup.exists():
            shutil.rmtree(data_backup)
        shutil.copytree(data_dir, data_backup)

    if my_ini.exists():
        ini_backup = paths.DOWNLOADS_DIR / "_mariadb_my_ini.bak"
        shutil.copy(my_ini, ini_backup)

    try:
        url = f"https://archive.mariadb.org/mariadb-{target_ver}/winx64-packages/mariadb-{target_ver}-winx64.zip"
        zip_path = setup_core._download(url, paths.DOWNLOADS_DIR / f"mariadb-{target_ver}-winx64.zip")
        setup_core._extract_zip_flatten_single_root(zip_path, paths.MARIADB_DIR)

        # Restore data directory and my.ini
        if data_backup and data_backup.exists():
            target_data = paths.MARIADB_DIR / "data"
            if target_data.exists():
                shutil.rmtree(target_data)
            shutil.copytree(data_backup, target_data)
            shutil.rmtree(data_backup, ignore_errors=True)

        if ini_backup and ini_backup.exists():
            shutil.copy(ini_backup, paths.MARIADB_DIR / "my.ini")
            ini_backup.unlink(missing_ok=True)
        else:
            setup_core._init_mariadb_data_dir()

        setup_core._create_mariadb_shims()

        if was_running:
            services.mariadb_start()

        return True, f"MariaDB upgraded successfully to {target_ver}."
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
            err = f"Could not query phpMyAdmin version API: {e}"

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

    # Preserve config.inc.php
    config_inc = paths.PMA_DIR / "config.inc.php"
    config_backup = None
    if config_inc.exists():
        config_backup = paths.DOWNLOADS_DIR / "_pma_config.inc.php.bak"
        shutil.copy(config_inc, config_backup)

    try:
        pma_core.install(version=target_ver)
        if config_backup and config_backup.exists():
            shutil.copy(config_backup, paths.PMA_DIR / "config.inc.php")
            config_backup.unlink(missing_ok=True)

        if was_running:
            pma_core.start()

        return True, f"phpMyAdmin upgraded successfully to {target_ver}."
    except Exception as e:
        if was_running:
            try:
                pma_core.start()
            except Exception:
                pass
        return False, f"phpMyAdmin upgrade failed: {e}"


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
        dest = setup_core.install_mkcert(version=target_ver)
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
            res = subprocess.run([str(bat), "--version"], capture_output=True, text=True, timeout=10)
            m = re.search(r"Composer (?:version )?(\d+\.\d+\.\d+)", res.stdout or res.stderr)
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


# ── UNIFIED API ─────────────────────────────────────────────────────────────

COMPONENTS = ["nginx", "mailpit", "mariadb", "pma", "mkcert", "composer"]


def check_all() -> list[ComponentInfo]:
    """Inspect installed versions and query latest upstream releases for all stack components."""
    results = [
        get_nginx_info(),
        get_mailpit_info(),
        get_mariadb_info(),
        get_pma_info(),
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
