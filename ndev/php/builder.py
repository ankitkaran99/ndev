import os
import tarfile
import shutil
from pathlib import Path
from ndev.constants import BUILDS_DIR, PHP_DIR
from ndev.logger import logger
from ndev.chroot.manager import SandboxManager
from ndev.config import load_config
from ndev.manifest import add_installed_version

def extract_archive(archive_path: Path, extract_dir: Path) -> Path:
    """Extract a tarball to a given directory and return the extracted folder path."""
    logger.info(f"Extracting {archive_path.name} to {extract_dir}...")
    extract_dir.mkdir(parents=True, exist_ok=True)
    
    with tarfile.open(archive_path) as tar:
        root_dir_name = None
        for member in tar.getmembers():
            parts = Path(member.name).parts
            if parts and parts[0] != ".":
                root_dir_name = parts[0]
                break
                
        if not root_dir_name:
            raise ValueError("Could not find a valid root directory in the tarball.")
            
        tar.extractall(path=extract_dir)
        
    return extract_dir / root_dir_name

def build_php(version: str, archive_path: Path) -> Path:
    """Extract, configure, compile and install PHP inside bubblewrap."""
    build_dir = BUILDS_DIR / f"php-{version}"
    if build_dir.exists():
        shutil.rmtree(build_dir)
        
    extracted_path = extract_archive(archive_path, BUILDS_DIR)
    if extracted_path.resolve() != build_dir.resolve():
        logger.info(f"Renaming build directory from {extracted_path.name} to {build_dir.name}")
        shutil.move(str(extracted_path), str(build_dir))
        
    # Patch upstream bug in ext/opcache/zend_shared_alloc.c
    alloc_c_path = build_dir / "ext" / "opcache" / "zend_shared_alloc.c"
    if alloc_c_path.exists():
        logger.info("Applying OPcache memfd_create patch to source code...")
        content = alloc_c_path.read_text()
        content = content.replace(
            "#if defined(__linux__) && defined(HAVE_MEMFD_CREATE)",
            "#if defined(__linux__)"
        )
        alloc_c_path.write_text(content)
        
    config = load_config()
    flags = config.get("build", {}).get("configure_flags", [])
    
    install_prefix = PHP_DIR / version
    if install_prefix.exists():
        logger.info(f"Removing existing installation at {install_prefix}")
        shutil.rmtree(install_prefix)
        
    configure_args = [
        "./configure",
        f"--prefix={install_prefix}",
        f"--with-config-file-path={install_prefix}/etc",
        f"--with-config-file-scan-dir={install_prefix}/etc/conf.d",
    ] + flags
    
    logger.info("Configuring PHP within sandbox...")
    sandbox = SandboxManager()
    sandbox.run(configure_args, cwd=build_dir)
    
    cores = os.cpu_count() or 2
    logger.info(f"Compiling PHP using {cores} parallel jobs...")
    sandbox.run(["make", f"-j{cores}"], cwd=build_dir)
    
    logger.info("Installing PHP...")
    sandbox.run(["make", "install"], cwd=build_dir)
    
    add_installed_version(version, str(install_prefix), configure_args)
    
    logger.info(f"PHP {version} compiled and installed successfully at {install_prefix}!")
    return install_prefix
