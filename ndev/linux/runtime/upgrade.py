"""
Component version check and upgrade management for Linux.
Manages updates for Nginx, Mailpit, MariaDB, phpMyAdmin, mkcert, and Composer on Linux.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ndev.common.constants import NDEV_DIR, LOGS_DIR
from ndev.linux.runtime import mailpit as mailpit_rt, pma as pma_rt

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


def _clean_ver(v: Optional[str]) -> str:
    if not v:
        return ""
    v = v.strip().lower()
    if v.startswith("v"):
        v = v[1:]
    return v.split()[0]


# 1. NGINX
def get_nginx_info() -> ComponentInfo:
    installed = bool(shutil.which("nginx"))
    curr_ver = None
    latest_ver = None
    err = None

    if installed:
        try:
            res = subprocess.run(["nginx", "-v"], capture_output=True, text=True, timeout=5)
            out = res.stderr or res.stdout
            m = re.search(r"nginx/(\d+\.\d+\.\d+)", out)
            if m:
                curr_ver = m.group(1)
        except Exception as e:
            err = str(e)

    # Check apt update availability if on Debian/Ubuntu
    update_avail = False
    if installed and shutil.which("apt"):
        try:
            res = subprocess.run(["apt", "list", "--upgradable", "nginx"], capture_output=True, text=True, timeout=10)
            if "nginx" in res.stdout and "upgradable from" in res.stdout:
                update_avail = True
                m = re.search(r"nginx/[\w\-]+\s+(\S+)", res.stdout)
                if m:
                    latest_ver = m.group(1)
        except Exception:
            pass

    if not latest_ver and curr_ver:
        latest_ver = curr_ver

    status = "Up-to-date"
    if not installed:
        status = "Not Installed"
    elif update_avail:
        status = f"Update Available ({curr_ver} -> {latest_ver})"

    return ComponentInfo("nginx", "Nginx Web Server", curr_ver, latest_ver, update_avail, installed, status, err)


def upgrade_nginx() -> tuple[bool, str]:
    if not shutil.which("apt"):
        return False, "Package manager 'apt' not found."
    try:
        subprocess.run(["sudo", "apt-get", "update"], check=True)
        subprocess.run(["sudo", "apt-get", "--only-upgrade", "install", "-y", "nginx"], check=True)
        info = get_nginx_info()
        return True, f"Nginx upgraded successfully ({info.current_version})."
    except Exception as e:
        return False, f"Nginx upgrade failed: {e}"


# 2. MAILPIT
def get_mailpit_info() -> ComponentInfo:
    installed = mailpit_rt.is_installed()
    curr_ver = None
    latest_ver = None
    err = None

    if installed:
        try:
            res = subprocess.run([str(mailpit_rt.BINARY_PATH), "version"], capture_output=True, text=True, timeout=5)
            out = res.stdout.strip() or res.stderr.strip()
            m = re.search(r"v?(\d+\.\d+\.\d+)", out)
            if m:
                curr_ver = f"v{m.group(1)}"
            else:
                curr_ver = out
        except Exception as e:
            err = str(e)

    try:
        data = _http_get_json("https://api.github.com/repos/axllent/mailpit/releases/latest")
        latest_ver = data.get("tag_name")
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
    was_running = mailpit_rt.get_mailpit_status().get("running", False)
    if was_running:
        mailpit_rt.stop_mailpit()
    try:
        mailpit_rt.install_mailpit()
        if was_running:
            mailpit_rt.start_mailpit()
        info = get_mailpit_info()
        return True, f"Mailpit upgraded successfully to {info.current_version}."
    except Exception as e:
        if was_running:
            try:
                mailpit_rt.start_mailpit()
            except Exception:
                pass
        return False, f"Mailpit upgrade failed: {e}"


# 3. MARIADB
def get_mariadb_info() -> ComponentInfo:
    installed = bool(shutil.which("mariadb") or shutil.which("mysql") or shutil.which("mysqld"))
    curr_ver = None
    latest_ver = None
    err = None

    if installed:
        try:
            exe = shutil.which("mariadbd") or shutil.which("mysqld") or shutil.which("mysql")
            if exe:
                res = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=5)
                m = re.search(r"(\d+\.\d+\.\d+)", res.stdout or res.stderr)
                if m:
                    curr_ver = m.group(1)
        except Exception as e:
            err = str(e)

    update_avail = False
    if installed and shutil.which("apt"):
        try:
            res = subprocess.run(["apt", "list", "--upgradable", "mariadb-server"], capture_output=True, text=True, timeout=10)
            if "mariadb-server" in res.stdout and "upgradable from" in res.stdout:
                update_avail = True
                m = re.search(r"mariadb-server/[\w\-]+\s+(\S+)", res.stdout)
                if m:
                    latest_ver = m.group(1)
        except Exception:
            pass

    if not latest_ver and curr_ver:
        latest_ver = curr_ver

    status = "Up-to-date"
    if not installed:
        status = "Not Installed"
    elif update_avail:
        status = f"Update Available ({curr_ver} -> {latest_ver})"

    return ComponentInfo("mariadb", "MariaDB Server", curr_ver, latest_ver, update_avail, installed, status, err)


def upgrade_mariadb() -> tuple[bool, str]:
    if not shutil.which("apt"):
        return False, "Package manager 'apt' not found."
    try:
        subprocess.run(["sudo", "apt-get", "update"], check=True)
        subprocess.run(["sudo", "apt-get", "--only-upgrade", "install", "-y", "mariadb-server"], check=True)
        info = get_mariadb_info()
        return True, f"MariaDB upgraded successfully ({info.current_version})."
    except Exception as e:
        return False, f"MariaDB upgrade failed: {e}"


# 4. PHPMYADMIN
def get_pma_info() -> ComponentInfo:
    pma_st = pma_rt.get_pma_status()
    installed = pma_st.get("installed", False)
    curr_ver = None
    pma_dir = pma_rt.PMA_DIR
    if installed and pma_dir.exists():
        for f in pma_dir.glob("RELEASE-DATE-*"):
            curr_ver = f.name.replace("RELEASE-DATE-", "")
            break
        if not curr_ver:
            curr_ver = pma_rt.DEFAULT_PMA_VERSION

    try:
        data = _http_get_json("https://www.phpmyadmin.net/home_page/version.json")
        latest_ver = data.get("version", pma_rt.DEFAULT_PMA_VERSION)
    except Exception as e:
        latest_ver = pma_rt.DEFAULT_PMA_VERSION
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
    was_running = pma_rt.get_pma_status().get("running", False)
    if was_running:
        pma_rt.stop_pma()

    info = get_pma_info()
    target_ver = info.latest_version or pma_rt.DEFAULT_PMA_VERSION

    # Preserve config.inc.php
    pma_dir = pma_rt.PMA_DIR
    config_inc = pma_dir / "config.inc.php"
    config_backup = None
    if config_inc.exists():
        config_backup = NDEV_DIR / "cache" / "_pma_config.inc.php.bak"
        config_backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(config_inc, config_backup)

    try:
        pma_rt.install_pma(version=target_ver)
        if config_backup and config_backup.exists():
            shutil.copy(config_backup, pma_dir / "config.inc.php")
            config_backup.unlink(missing_ok=True)

        if was_running:
            pma_rt.start_pma()

        return True, f"phpMyAdmin upgraded successfully to {target_ver}."
    except Exception as e:
        if was_running:
            try:
                pma_rt.start_pma()
            except Exception:
                pass
        return False, f"phpMyAdmin upgrade failed: {e}"


# 5. MKCERT
def get_mkcert_info() -> ComponentInfo:
    installed = bool(shutil.which("mkcert"))
    curr_ver = None
    latest_ver = None
    err = None

    if installed:
        try:
            res = subprocess.run(["mkcert", "-version"], capture_output=True, text=True, timeout=5)
            curr_ver = res.stdout.strip() or res.stderr.strip()
        except Exception as e:
            err = str(e)

    try:
        data = _http_get_json("https://api.github.com/repos/FiloSottile/mkcert/releases/latest")
        latest_ver = data.get("tag_name")
    except Exception as e:
        latest_ver = "v1.4.4"
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
    if not shutil.which("apt"):
        return False, "Package manager 'apt' not found."
    try:
        subprocess.run(["sudo", "apt-get", "update"], check=True)
        subprocess.run(["sudo", "apt-get", "--only-upgrade", "install", "-y", "mkcert"], check=True)
        subprocess.run(["mkcert", "-install"], check=True)
        info = get_mkcert_info()
        return True, f"mkcert upgraded successfully ({info.current_version})."
    except Exception as e:
        return False, f"mkcert upgrade failed: {e}"


# 6. COMPOSER
def get_composer_info() -> ComponentInfo:
    installed = bool(shutil.which("composer"))
    curr_ver = None
    latest_ver = None
    err = None

    if installed:
        try:
            res = subprocess.run(["composer", "--version"], capture_output=True, text=True, timeout=10)
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
        if shutil.which("composer"):
            res = subprocess.run(["composer", "self-update"], capture_output=True, text=True, timeout=60)
            if res.returncode == 0:
                info = get_composer_info()
                return True, f"Composer upgraded successfully ({info.current_version})."

        # Fallback to direct download
        dest = Path.home() / ".local" / "bin" / "composer"
        dest.parent.mkdir(parents=True, exist_ok=True)
        phar_url = "https://getcomposer.org/composer-stable.phar"
        req = urllib.request.Request(phar_url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as f:
            f.write(resp.read())
        dest.chmod(0o755)
        info = get_composer_info()
        return True, f"Composer upgraded successfully ({info.current_version})."
    except Exception as e:
        return False, f"Composer upgrade failed: {e}"


# ── UNIFIED API ─────────────────────────────────────────────────────────────

COMPONENTS = ["nginx", "mailpit", "mariadb", "pma", "mkcert", "composer"]


def check_all() -> list[ComponentInfo]:
    return [
        get_nginx_info(),
        get_mailpit_info(),
        get_mariadb_info(),
        get_pma_info(),
        get_mkcert_info(),
        get_composer_info(),
    ]


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
