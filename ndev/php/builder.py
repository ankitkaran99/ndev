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

def apply_patches(version: str, build_dir: Path):
    """Apply patches for a specific PHP version from the patches directory."""
    major_minor = ".".join(version.split(".")[:2])
    
    project_root = Path(__file__).resolve().parents[2]
    patches_dirs = [
        project_root / "patches" / version,
        project_root / "patches" / major_minor,
    ]
    
    import subprocess
    
    applied_any = False
    for patch_dir in patches_dirs:
        if patch_dir.exists() and patch_dir.is_dir():
            patch_files = sorted(patch_dir.glob("*.patch")) + sorted(patch_dir.glob("*.diff"))
            seen = set()
            for patch_file in patch_files:
                if patch_file.name in seen:
                    continue
                seen.add(patch_file.name)
                
                logger.info(f"Applying patch {patch_file.name} for PHP {version}...")
                try:
                    subprocess.run(
                        ["patch", "-p1", "-N", "-t", "-i", str(patch_file)],
                        cwd=build_dir,
                        capture_output=True,
                        text=True,
                        check=True
                    )
                    applied_any = True
                except subprocess.CalledProcessError as e:
                    logger.error(f"Failed to apply patch {patch_file.name}: {e.stderr}")
                    raise e
                    
    if not applied_any:
        logger.debug(f"No patches found for PHP {version}.")

def load_compat_args(version: str) -> str:
    """Load compatibility compiler flags from the args directory for the given version."""
    major_minor = ".".join(version.split(".")[:2])
    
    project_root = Path(__file__).resolve().parents[2]
    args_files = [
        project_root / "args" / f"{version}.txt",
        project_root / "args" / f"{major_minor}.txt",
    ]
    
    for args_file in args_files:
        if args_file.exists() and args_file.is_file():
            try:
                content = args_file.read_text().strip()
                return " " + " ".join(content.split())
            except Exception as e:
                logger.warning(f"Failed to read args file {args_file}: {e}")
                
    return ""

def build_php(version: str, archive_path: Path, show_logs: bool = False) -> Path:
    """Extract, configure, compile and install PHP inside bubblewrap."""
    build_dir = BUILDS_DIR / f"php-{version}"
    if build_dir.exists():
        shutil.rmtree(build_dir)
        
    extracted_path = extract_archive(archive_path, BUILDS_DIR)
    if extracted_path.resolve() != build_dir.resolve():
        logger.info(f"Renaming build directory from {extracted_path.name} to {build_dir.name}")
        shutil.move(str(extracted_path), str(build_dir))
        
    # Apply version-specific patches
    apply_patches(version, build_dir)
        
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
    
    env = os.environ.copy()
    # Avoid pkg-config dependency checks for libraries inside the sandbox
    env["CURL_CFLAGS"] = "-I/usr/local/include"
    env["CURL_LIBS"] = "-L/usr/local/lib -L/usr/local/lib/x86_64-linux-gnu -lcurl"
    
    env["WEBP_CFLAGS"] = "-I/usr/local/include"
    env["WEBP_LIBS"] = "-L/usr/local/lib -L/usr/local/lib/x86_64-linux-gnu -lwebp"
    
    env["JPEG_CFLAGS"] = "-I/usr/local/include"
    env["JPEG_LIBS"] = "-L/usr/local/lib -L/usr/local/lib/x86_64-linux-gnu -ljpeg"
    
    env["PNG_CFLAGS"] = "-I/usr/local/include"
    env["PNG_LIBS"] = "-L/usr/local/lib -L/usr/local/lib/x86_64-linux-gnu -lpng"
    
    env["FREETYPE2_CFLAGS"] = "-I/usr/local/include/freetype2 -I/usr/local/include"
    env["FREETYPE2_LIBS"] = "-L/usr/local/lib -L/usr/local/lib/x86_64-linux-gnu -lfreetype"
    
    env["LIBSODIUM_CFLAGS"] = "-I/usr/local/include"
    env["LIBSODIUM_LIBS"] = "-L/usr/local/lib -L/usr/local/lib/x86_64-linux-gnu -lsodium"
    
    env["LIBZIP_CFLAGS"] = "-I/usr/local/include"
    env["LIBZIP_LIBS"] = "-L/usr/local/lib -L/usr/local/lib/x86_64-linux-gnu -lzip"
    
    env["ONIG_CFLAGS"] = "-I/usr/local/include"
    env["ONIG_LIBS"] = "-L/usr/local/lib -L/usr/local/lib/x86_64-linux-gnu -lonig"

    env["ICU_CFLAGS"] = "-I/usr/local/include"
    env["ICU_LIBS"] = "-L/usr/local/lib -L/usr/local/lib/x86_64-linux-gnu -licui18n -licuuc -licudata -licuio"

    compat_flags = load_compat_args(version)
    if compat_flags:
        logger.info(f"Applying compatibility flags from args file for PHP {version}...")
        env["CFLAGS"] = env.get("CFLAGS", "") + compat_flags
        env["CXXFLAGS"] = env.get("CXXFLAGS", "") + compat_flags

    if not show_logs:
        logger.info(f"[yellow]Compiling PHP {version}...[/yellow]")
    else:
        logger.info("Configuring PHP within sandbox...")
    sandbox = SandboxManager()
    sandbox.run(configure_args, cwd=build_dir, env=env, show_logs=show_logs)
    
    cores = os.cpu_count() or 2
    if show_logs:
        logger.info(f"Compiling PHP using {cores} parallel jobs...")
    try:
        sandbox.run(["make", f"-j{cores}"], cwd=build_dir, env=env, show_logs=show_logs)
    except Exception:
        logger.warning("Parallel compilation failed (likely due to a libtool race condition). Retrying sequentially...")
        sandbox.run(["make"], cwd=build_dir, env=env, show_logs=show_logs)
    
    if not show_logs:
        logger.info(f"[green]Compiled PHP {version}[/green]")
        logger.info(f"[yellow]Installing PHP {version}...[/yellow]")
    else:
        logger.info("Installing PHP...")
    sandbox.run(["make", "install"], cwd=build_dir, env=env, show_logs=show_logs)
    
    if not show_logs:
        logger.info(f"[green]Installed PHP {version}[/green]")
        
    add_installed_version(version, str(install_prefix), configure_args)
    
    logger.info(f"PHP {version} compiled and installed successfully at {install_prefix}!")
    return install_prefix
