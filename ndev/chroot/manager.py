import os
import subprocess
from pathlib import Path
from ndev.constants import CHROOT_DIR, NDEV_DIR
from ndev.logger import logger
from ndev.utils import run_command

class SandboxManager:
    def __init__(self):
        self.chroot_dir = CHROOT_DIR
        self.ndev_dir = NDEV_DIR

    def init_sandbox(self):
        """Prepare local directories in ~/.ndev/chroot for mounting."""
        for sub_dir in ["bin", "sbin", "lib", "lib64", "usr", "etc", "proc", "dev", "sys", "tmp", "builds", "home"]:
            (self.chroot_dir / sub_dir).mkdir(parents=True, exist_ok=True)
        # Ensure usr/local exists
        (self.chroot_dir / "usr" / "local").mkdir(parents=True, exist_ok=True)

    def get_bwrap_command(self, cmd_args, cwd=None):
        """Build bubblewrap command that mounts the host system read-only."""
        self.init_sandbox()
        
        bwrap_cmd = [
            "bwrap",
            "--bind", str(self.chroot_dir), "/",
            "--ro-bind-try", "/usr", "/usr",
            "--bind", str(self.chroot_dir / "usr" / "local"), "/usr/local",
            "--ro-bind-try", "/lib", "/lib",
            "--ro-bind-try", "/lib64", "/lib64",
            "--ro-bind-try", "/bin", "/bin",
            "--ro-bind-try", "/sbin", "/sbin",
            "--ro-bind-try", "/etc", "/etc",
            "--proc", "/proc",
            "--dev", "/dev",
            "--tmpfs", "/tmp",
            "--bind", str(self.ndev_dir), str(self.ndev_dir),
        ]
        
        home_dir = os.path.expanduser("~")
        bwrap_cmd.extend(["--bind", home_dir, home_dir])
        
        if cwd:
            bwrap_cmd.extend(["--chdir", str(cwd)])
            
        bwrap_cmd.append("--")
        bwrap_cmd.extend(cmd_args)
        
        return bwrap_cmd

    def run(self, cmd_args, cwd=None, env=None, check=True):
        """Run command inside the bubblewrap sandbox."""
        if env is None:
            env = os.environ.copy()
            
        env["PKG_CONFIG_PATH"] = "/usr/local/lib/pkgconfig:/usr/local/lib/x86_64-linux-gnu/pkgconfig:" + env.get("PKG_CONFIG_PATH", "")
        env["LD_LIBRARY_PATH"] = "/usr/local/lib:/usr/local/lib/x86_64-linux-gnu:" + env.get("LD_LIBRARY_PATH", "")
        env["LIBRARY_PATH"] = "/usr/local/lib:/usr/local/lib/x86_64-linux-gnu:" + env.get("LIBRARY_PATH", "")
        env["CPATH"] = "/usr/local/include:" + env.get("CPATH", "")
        env["PATH"] = "/usr/local/bin:" + env.get("PATH", "")
        
        bwrap_cmd = self.get_bwrap_command(cmd_args, cwd=cwd)
        return run_command(bwrap_cmd, env=env, check=check)
