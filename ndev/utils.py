import subprocess
import shlex
import sys
from rich.console import Console
from ndev.logger import logger

console = Console()

def run_command(cmd, cwd=None, env=None, check=True, capture_output=False):
    """Run a shell command, printing output in real-time or capturing it."""
    if isinstance(cmd, str):
        cmd_args = shlex.split(cmd)
    else:
        cmd_args = cmd
        
    logger.debug(f"Running command: {' '.join(shlex.quote(arg) for arg in cmd_args)} in cwd={cwd}")
    
    if capture_output:
        res = subprocess.run(cmd_args, cwd=cwd, env=env, capture_output=True, text=True)
        if check and res.returncode != 0:
            logger.error(f"Command failed with exit code {res.returncode}")
            logger.error(f"Stdout: {res.stdout}")
            logger.error(f"Stderr: {res.stderr}")
            raise subprocess.CalledProcessError(res.returncode, cmd_args, res.stdout, res.stderr)
        return res
        
    p = subprocess.Popen(
        cmd_args,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )
    
    output_lines = []
    if p.stdout:
        for line in p.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            output_lines.append(line)
            
    p.wait()
    if check and p.returncode != 0:
        raise subprocess.CalledProcessError(p.returncode, cmd_args, "".join(output_lines))
    return p.returncode
