import shutil
import os
from pathlib import Path
from ndev.chroot.manager import SandboxManager
from ndev.logger import logger
from ndev.utils import run_command

def install_host_packages(packages: list[str], show_logs: bool = False):
    """Downloads, extracts, and moves package files to usr/local inside chroot."""
    if not packages:
        return
        
    logger.info(f"Installing packages into sandbox: {', '.join(packages)}")
    sandbox = SandboxManager()
    sandbox.init_sandbox()
    
    local_dir = sandbox.chroot_dir / "usr" / "local"
    local_dir.mkdir(parents=True, exist_ok=True)
    for sub in ["bin", "lib", "include", "share"]:
        (local_dir / sub).mkdir(parents=True, exist_ok=True)
        
    tmp_dir = sandbox.chroot_dir / "tmp" / "pkg_downloads"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        cmd = ["apt-get", "download"] + packages
        run_command(cmd, cwd=tmp_dir, show_logs=show_logs)
        
        for deb in tmp_dir.glob("*.deb"):
            extract_dest = tmp_dir / deb.stem
            extract_dest.mkdir(parents=True, exist_ok=True)
            run_command(["dpkg", "-x", str(deb), str(extract_dest)], show_logs=show_logs)
            
            usr_src = extract_dest / "usr"
            if usr_src.exists():
                for root, dirs, files in os.walk(usr_src):
                    rel_root = Path(root).relative_to(usr_src)
                    dest_root = local_dir / rel_root
                    dest_root.mkdir(parents=True, exist_ok=True)
                    
                    # Move directory symlinks
                    for d in list(dirs):
                        src_dir = Path(root) / d
                        if src_dir.is_symlink():
                            dest_dir = dest_root / d
                            if dest_dir.exists() or dest_dir.is_symlink():
                                if dest_dir.is_dir() and not dest_dir.is_symlink():
                                    shutil.rmtree(dest_dir)
                                else:
                                    dest_dir.unlink()
                            shutil.move(src_dir, dest_dir)
                            dirs.remove(d)

                    for file in files:
                        src_file = Path(root) / file
                        dest_file = dest_root / file
                        if dest_file.exists():
                            dest_file.unlink()
                        shutil.move(src_file, dest_file)
                        
        # Fix broken relative symlinks in usr/local/lib pointing to multiarch runtime libraries
        lib_dir = local_dir / "lib"
        if lib_dir.exists():
            for root, dirs, files in os.walk(lib_dir):
                for file in files:
                    file_path = Path(root) / file
                    if file_path.is_symlink():
                        target = os.readlink(file_path)
                        # Check if it is a broken link
                        if not file_path.exists():
                            # Find it on the host system
                            host_paths = [
                                Path("/usr/lib/x86_64-linux-gnu"),
                                Path("/lib/x86_64-linux-gnu"),
                                Path("/usr/lib"),
                                Path("/lib")
                            ]
                            resolved = False
                            for hp in host_paths:
                                host_target = hp / target
                                if host_target.exists():
                                    logger.info(f"Fixing broken symlink {file_path.name} -> {host_target}")
                                    file_path.unlink()
                                    file_path.symlink_to(host_target)
                                    resolved = True
                                    break
                            if not resolved:
                                logger.warning(f"Could not resolve symlink target '{target}' for {file_path}")
                        
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
