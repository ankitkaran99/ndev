"""
`ndev setup` -- download and configure native Windows binaries for Nginx,
MariaDB, mkcert, ngrok, and Composer.
"""
from __future__ import annotations

import shutil
import stat
import subprocess
import urllib.request
import zipfile
from pathlib import Path
from typing import Optional

from . import paths

# ---- Defaults ---------------------------------------------------------------

DEFAULT_NGINX_VERSION = "1.30.4"
DEFAULT_MARIADB_VERSION = "11.4.5"
DEFAULT_MKCERT_VERSION = "1.4.4"
NGROK_STABLE_URL = "https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-windows-amd64.zip"
COMPOSER_PHAR_URL = "https://getcomposer.org/composer-stable.phar"


def _download(url: str, dest: Path) -> Path:
    paths.ensure_dirs()
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "ndev/0.1.0"})
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
            raise RuntimeError(f"Download from {url} resulted in empty file.")
    except Exception:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise
    return dest


def _overlay_zip_flatten_single_root(
    zip_path: Path,
    target: Path,
    preserve_dirs: Optional[list[str]] = None,
    preserve_files: Optional[list[str]] = None,
) -> None:
    preserve_dirs = preserve_dirs or []
    preserve_files = preserve_files or []
    paths.ensure_dirs()
    target.mkdir(parents=True, exist_ok=True)

    extract_tmp = paths.DOWNLOADS_DIR / f"_extract_{target.name}"
    if extract_tmp.exists():
        shutil.rmtree(extract_tmp)

    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(extract_tmp)

    inner_dirs = [d for d in extract_tmp.iterdir() if d.is_dir()]
    inner_files = [f for f in extract_tmp.iterdir() if f.is_file()]
    root_src = inner_dirs[0] if (len(inner_dirs) == 1 and not inner_files) else extract_tmp

    for item in root_src.iterdir():
        dest = target / item.name
        if item.is_dir():
            # If directory is in preserve list and already contains user files, DO NOT wipe it!
            if item.name in preserve_dirs and dest.exists() and any(dest.iterdir()):
                continue
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(item, dest)
        elif item.is_file():
            # If file is in preserve list and already exists, DO NOT overwrite it!
            if item.name in preserve_files and dest.exists() and dest.stat().st_size > 0:
                continue
            shutil.copy2(item, dest)

    shutil.rmtree(extract_tmp, ignore_errors=True)


# ---- Nginx ------------------------------------------------------------------

def install_nginx(version: str = DEFAULT_NGINX_VERSION) -> Path:
    url = f"https://nginx.org/download/nginx-{version}.zip"
    zip_path = _download(url, paths.DOWNLOADS_DIR / f"nginx-{version}.zip")
    
    # Non-destructively overlay binaries while preserving conf/ (ndev-vhosts) and logs/
    _overlay_zip_flatten_single_root(
        zip_path,
        paths.NGINX_DIR,
        preserve_dirs=["conf", "logs", "temp"],
        preserve_files=["nginx.conf"],
    )
    
    paths.NGINX_CONF_D.mkdir(parents=True, exist_ok=True)
    paths.NGINX_LOGS_DIR.mkdir(parents=True, exist_ok=True)
    _include_vhosts_in_main_conf()
    return paths.NGINX_DIR


def _include_vhosts_in_main_conf() -> None:
    """Add `include ndev-vhosts/*.conf;` inside the http{} block in nginx.conf."""
    # Ensure default fallback vhost exists so Nginx never fails wildcard glob
    default_conf = paths.NGINX_CONF_D / "_default.conf"
    if not default_conf.exists():
        default_conf.write_text(
            'server {\n'
            '    listen 80 default_server;\n'
            '    server_name _;\n'
            '    return 404 "ndev: No virtual host configured for this domain.\\n";\n'
            '}\n',
            encoding="utf-8"
        )

    conf = paths.NGINX_DIR / "conf" / "nginx.conf"
    if not conf.exists():
        return
    text = conf.read_text(encoding="utf-8", errors="ignore")
    include_line = "    include ndev-vhosts/*.conf;\n"
    if "ndev-vhosts" in text:
        return

    http_start = text.find("http {")
    if http_start == -1:
        return
    brace_depth = 0
    i = text.find("{", http_start)
    for idx in range(i, len(text)):
        if text[idx] == "{":
            brace_depth += 1
        elif text[idx] == "}":
            brace_depth -= 1
            if brace_depth == 0:
                text = text[:idx] + include_line + text[idx:]
                break
    conf.write_text(text, encoding="utf-8")


# ---- MariaDB ------------------------------------------------------------------

def install_mariadb(version: str = DEFAULT_MARIADB_VERSION) -> Path:
    url = f"https://archive.mariadb.org/mariadb-{version}/winx64-packages/mariadb-{version}-winx64.zip"
    zip_path = _download(url, paths.DOWNLOADS_DIR / f"mariadb-{version}-winx64.zip")
    
    # Non-destructively overlay binaries while preserving data/ and my.ini
    _overlay_zip_flatten_single_root(
        zip_path,
        paths.MARIADB_DIR,
        preserve_dirs=["data"],
        preserve_files=["my.ini"],
    )
    _init_mariadb_data_dir()
    _create_mariadb_shims()
    return paths.MARIADB_DIR


def _create_mariadb_shims() -> None:
    paths.ensure_dirs()
    mysql_exe = paths.MARIADB_DIR / "bin" / "mysql.exe"
    mysqldump_exe = paths.MARIADB_DIR / "bin" / "mysqldump.exe"
    if mysql_exe.exists():
        (paths.SHIM_DIR / "mysql.bat").write_text(f'@echo off\r\n"{mysql_exe}" %*\r\n', encoding="utf-8")
        (paths.SHIM_DIR / "mysql.cmd").write_text(f'@echo off\r\n"{mysql_exe}" %*\r\n', encoding="utf-8")
        (paths.SHIM_DIR / "mysql.ps1").write_text(f'& "{mysql_exe}" @args\r\n', encoding="utf-8")
    if mysqldump_exe.exists():
        (paths.SHIM_DIR / "mysqldump.bat").write_text(f'@echo off\r\n"{mysqldump_exe}" %*\r\n', encoding="utf-8")
        (paths.SHIM_DIR / "mysqldump.cmd").write_text(f'@echo off\r\n"{mysqldump_exe}" %*\r\n', encoding="utf-8")
        (paths.SHIM_DIR / "mysqldump.ps1").write_text(f'& "{mysqldump_exe}" @args\r\n', encoding="utf-8")


def _init_mariadb_data_dir() -> None:
    """Initialize MariaDB data directory with mariadb-install-db.exe and generate isolated my.ini."""
    data_dir = paths.MARIADB_DIR / "data"
    clean_data_dir = str(data_dir.resolve()).replace("\\", "/")
    clean_base_dir = str(paths.MARIADB_DIR.resolve()).replace("\\", "/")

    # Generate custom my.ini for isolated local execution
    my_ini = paths.MARIADB_DIR / "my.ini"
    if not my_ini.exists():
        my_ini_content = f"""[mysqld]
basedir = "{clean_base_dir}"
datadir = "{clean_data_dir}"
port = 3306
bind-address = 127.0.0.1
character-set-server = utf8mb4
collation-server = utf8mb4_unicode_ci
max_allowed_packet = 64M
default-storage-engine = INNODB
innodb_buffer_pool_size = 128M

[client]
port = 3306
default-character-set = utf8mb4

[mysql]
default-character-set = utf8mb4
"""
        my_ini.write_text(my_ini_content, encoding="utf-8")

    if data_dir.exists() and any(data_dir.iterdir()):
        return

    installer = paths.MARIADB_DIR / "bin" / "mariadb-install-db.exe"
    if not installer.exists():
        installer = paths.MARIADB_DIR / "bin" / "mysql_install_db.exe"
    if not installer.exists():
        return

    for cmd in [
        [str(installer), f"--datadir={clean_data_dir}", "--service=", "--password=root"],
        [str(installer), f"--datadir={clean_data_dir}", "--password=root"],
        [str(installer), f"--datadir={clean_data_dir}"],
    ]:
        try:
            res = subprocess.run(cmd, cwd=str(paths.MARIADB_DIR), capture_output=True, timeout=60)
            if res.returncode == 0:
                break
        except Exception:
            pass


# ---- mkcert -------------------------------------------------------------------

def install_mkcert(version: str = DEFAULT_MKCERT_VERSION) -> Path:
    url = f"https://github.com/FiloSottile/mkcert/releases/download/v{version}/mkcert-v{version}-windows-amd64.exe"
    dest = paths.SHIM_DIR / "mkcert.exe"
    _download(url, dest)
    
    cfg = paths.load_config()
    cfg["mkcert_path"] = str(dest)
    paths.save_config(cfg)

    # Automatically install root CA
    try:
        from . import mkcert
        mkcert.ensure_ca_installed()
    except Exception:
        pass

    return dest


# ---- ngrok --------------------------------------------------------------------

def install_ngrok() -> Path:
    try:
        zip_path = _download(NGROK_STABLE_URL, paths.DOWNLOADS_DIR / "ngrok-stable-windows-amd64.zip")
        with zipfile.ZipFile(zip_path) as zf:
            zf.extract("ngrok.exe", paths.SHIM_DIR)
        dest = paths.SHIM_DIR / "ngrok.exe"
        cfg = paths.load_config()
        cfg["ngrok_path"] = str(dest)
        paths.save_config(cfg)
        return dest
    except Exception as e:
        error_msg = str(e)
        if "virus" in error_msg.lower() or "unwanted" in error_msg.lower() or "225" in error_msg:
            raise RuntimeError(
                "Windows Defender / Antivirus blocked ngrok.exe (Heuristic False Positive). "
                "Reverse-tunnel tools are frequently flagged by antivirus heuristic engines. "
                "You can run `ndev setup --no-ngrok` to skip ngrok installation, or whitelist ~/.ndev/shims/ngrok.exe in Windows Security."
            ) from e
        raise


# ---- Composer -----------------------------------------------------------------

def install_composer() -> Path:
    """Download composer.phar and generate composer.bat, composer.cmd, and composer.ps1 shims."""
    phar_dest = paths.SHIM_DIR / "composer.phar"
    _download(COMPOSER_PHAR_URL, phar_dest)
    
    clean_phar = str(phar_dest.resolve()).replace("\\", "/")
    (paths.SHIM_DIR / "composer.bat").write_text(f'@echo off\r\nphp "{clean_phar}" %*\r\n', encoding="utf-8")
    (paths.SHIM_DIR / "composer.cmd").write_text(f'@echo off\r\nphp "{clean_phar}" %*\r\n', encoding="utf-8")
    (paths.SHIM_DIR / "composer.ps1").write_text(f'& php "{clean_phar}" @args\r\n', encoding="utf-8")
    return phar_dest


# ---- CA Certificates ---------------------------------------------------------

def install_cacert() -> Path:
    """Download Mozilla root CA bundle for PHP cURL and OpenSSL."""
    paths.ensure_dirs()
    if not paths.CACERT_PATH.exists():
        _download("https://curl.se/ca/cacert.pem", paths.CACERT_PATH)
    # Re-apply php.ini updates across all installed PHP runtimes
    from . import php
    for v in php.list_installed():
        php._configure_php_ini(paths.version_dir(v))
    return paths.CACERT_PATH


def create_ndev_shims() -> Path:
    """Create ndev.bat, ndev.cmd, and ndev.ps1 in ~/.ndev/shims/ pointing to active python/ndev."""
    import sys
    paths.ensure_dirs()
    scripts_dir = Path(sys.executable).parent
    ndev_exe = scripts_dir / "ndev.exe"
    if ndev_exe.exists():
        bat_target = f'"{ndev_exe}" %*'
        ps_target = f'& "{ndev_exe}" @args'
    else:
        bat_target = f'"{sys.executable}" -m ndev_win.cli %*'
        ps_target = f'& "{sys.executable}" -m ndev_win.cli @args'

    bat_path = paths.SHIM_DIR / "ndev.bat"
    cmd_path = paths.SHIM_DIR / "ndev.cmd"
    ps_path = paths.SHIM_DIR / "ndev.ps1"
    bat_path.write_text(f'@echo off\r\n{bat_target}\r\n', encoding="utf-8")
    cmd_path.write_text(f'@echo off\r\n{bat_target}\r\n', encoding="utf-8")
    ps_path.write_text(f'{ps_target}\r\n', encoding="utf-8")
    return bat_path


# ---- Orchestration ----------------------------------------------------------

def run_setup(
    nginx: bool = True,
    mariadb: bool = True,
    mkcert: bool = True,
    ngrok: bool = True,
    composer: bool = True,
    cacert: bool = True,
    versions: Optional[dict] = None,
) -> dict:
    versions = versions or {}
    results = {}
    if nginx:
        results["nginx"] = install_nginx(versions.get("nginx", DEFAULT_NGINX_VERSION))
    if mariadb:
        results["mariadb"] = install_mariadb(versions.get("mariadb", DEFAULT_MARIADB_VERSION))
    if mkcert:
        results["mkcert"] = install_mkcert(versions.get("mkcert", DEFAULT_MKCERT_VERSION))
    if ngrok:
        try:
            results["ngrok"] = install_ngrok()
        except Exception as e:
            results["ngrok"] = f"Skipped: {e}"
    if composer:
        results["composer"] = install_composer()
    if cacert:
        results["cacert"] = install_cacert()

    # Always ensure CLI shims
    results["shims"] = create_ndev_shims()
    return results
