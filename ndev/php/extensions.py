import shutil
import tarfile
import subprocess
import httpx
from pathlib import Path
from ndev.constants import PHP_DIR, DOWNLOADS_DIR, BUILDS_DIR
from ndev.chroot.manager import SandboxManager
from ndev.logger import logger
from ndev.utils import run_command

def get_php_binaries(version: str) -> tuple[Path, Path, Path]:
    """Get the path to php, phpize, and php-config binaries for a version."""
    prefix = PHP_DIR / version
    php_bin = prefix / "bin" / "php"
    phpize_bin = prefix / "bin" / "phpize"
    php_config_bin = prefix / "bin" / "php-config"
    return php_bin, phpize_bin, php_config_bin

def list_extensions(version: str) -> list[str]:
    """List loaded PHP extensions by running php -m."""
    php_bin, _, _ = get_php_binaries(version)
    if not php_bin.exists():
        raise ValueError(f"PHP version {version} is not installed.")
        
    res = subprocess.run([str(php_bin), "-m"], capture_output=True, text=True)
    if res.returncode != 0:
        raise ValueError(f"Failed to list extensions: {res.stderr}")
        
    lines = res.stdout.splitlines()
    extensions = []
    for line in lines:
        line = line.strip()
        if line and not line.startswith("["):
            extensions.append(line)
    return sorted(extensions)

def enable_extension(version: str, ext_name: str):
    """Enable an extension by creating its ini file in etc/conf.d/."""
    prefix = PHP_DIR / version
    conf_d = prefix / "etc" / "conf.d"
    conf_d.mkdir(parents=True, exist_ok=True)
    
    ini_file = conf_d / f"{ext_name}.ini"
    
    # OPcache and Xdebug require zend_extension, others require extension
    if ext_name.lower() in ["opcache", "xdebug"]:
        ini_file.write_text(f"zend_extension={ext_name}\n")
    else:
        ini_file.write_text(f"extension={ext_name}\n")
        
    logger.info(f"Extension '{ext_name}' enabled for PHP {version} (ini file created at {ini_file}).")

def disable_extension(version: str, ext_name: str):
    """Disable an extension by removing its ini file in etc/conf.d/."""
    prefix = PHP_DIR / version
    ini_file = prefix / "etc" / "conf.d" / f"{ext_name}.ini"
    if ini_file.exists():
        ini_file.unlink()
        logger.info(f"Extension '{ext_name}' disabled for PHP {version} (ini file removed).")
    else:
        logger.warning(f"Extension '{ext_name}' was not enabled (ini file {ini_file} does not exist).")

def install_extension(version: str, ext_name: str, show_logs: bool = False):
    """Download, compile, and install a PECL extension inside the sandbox."""
    php_bin, phpize_bin, php_config_bin = get_php_binaries(version)
    if not php_bin.exists():
        raise ValueError(f"PHP version {version} is not installed.")
    if not phpize_bin.exists():
        raise ValueError(f"phpize binary not found for version {version}. Development headers may be missing.")

    # 1. Download extension archive on host
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    archive_path = DOWNLOADS_DIR / f"{ext_name}.tgz"
    url = f"https://pecl.php.net/get/{ext_name}"
    
    logger.info(f"Downloading extension '{ext_name}' from {url}...")
    with httpx.Client(follow_redirects=True) as client:
        res = client.get(url)
        if res.status_code != 200:
            raise ValueError(f"Failed to download extension '{ext_name}' from PECL (HTTP status {res.status_code}).")
        archive_path.write_bytes(res.content)

    # 2. Extract extension archive
    BUILDS_DIR.mkdir(parents=True, exist_ok=True)
    build_dir = BUILDS_DIR / f"ext-{ext_name}"
    if build_dir.exists():
        if build_dir.is_dir():
            shutil.rmtree(build_dir)
        else:
            build_dir.unlink()
        
    logger.info(f"Extracting extension archive to {build_dir}...")
    with tarfile.open(archive_path) as tar:
        root_dir_name = None
        for member in tar.getmembers():
            if member.name.endswith("config.m4"):
                parts = Path(member.name).parts
                if len(parts) > 1:
                    root_dir_name = parts[0]
                    break
        if not root_dir_name:
            for member in tar.getmembers():
                parts = Path(member.name).parts
                if len(parts) > 1 and parts[0] != ".":
                    root_dir_name = parts[0]
                    break
        if not root_dir_name:
            raise ValueError("Could not find a valid root directory in extension archive.")
        tar.extractall(path=BUILDS_DIR)
        
    extracted_path = BUILDS_DIR / root_dir_name
    if extracted_path.resolve() != build_dir.resolve():
        shutil.move(str(extracted_path), str(build_dir))

    # 3. Configure and compile inside sandbox
    if not show_logs:
        logger.info(f"[yellow]Compiling extension '{ext_name}'...[/yellow]")
    else:
        logger.info(f"Compiling extension '{ext_name}' inside the sandbox...")
    sandbox = SandboxManager()
    
    # Run phpize
    sandbox.run([str(phpize_bin)], cwd=build_dir, show_logs=show_logs)
    
    # Run configure
    sandbox.run(["./configure", f"--with-php-config={php_config_bin}"], cwd=build_dir, show_logs=show_logs)
    
    # Run make
    sandbox.run(["make", "-j4"], cwd=build_dir, show_logs=show_logs)
    
    if not show_logs:
        logger.info(f"[green]Compiled extension '{ext_name}'[/green]")
        logger.info(f"[yellow]Installing extension '{ext_name}'...[/yellow]")
    else:
        logger.info("Installing extension...")
    sandbox.run(["make", "install"], cwd=build_dir, show_logs=show_logs)
    
    if not show_logs:
        logger.info(f"[green]Installed extension '{ext_name}'[/green]")
    
    # 4. Enable extension (strip version suffix if present: e.g. xdebug-3.1.6 -> xdebug)
    base_ext_name = ext_name.split("-")[0]
    enable_extension(version, base_ext_name)
    
    # Clean up build dir
    shutil.rmtree(build_dir, ignore_errors=True)
