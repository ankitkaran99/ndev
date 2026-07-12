import os
from ndev.chroot.manager import SandboxManager

def enter_sandbox_shell():
    """Launch interactive bash shell inside the bubblewrap sandbox."""
    sandbox = SandboxManager()
    cmd = ["bash"]
    bwrap_cmd = sandbox.get_bwrap_command(cmd)
    os.execvp(bwrap_cmd[0], bwrap_cmd)
