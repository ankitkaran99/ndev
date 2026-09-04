import subprocess
import shlex
import sys
from rich.console import Console
from ndev.common.logger import logger

console = Console()

def run_command(cmd, cwd=None, env=None, check=True, capture_output=False, show_logs=True):
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
            if show_logs:
                sys.stdout.write(line)
                sys.stdout.flush()
            output_lines.append(line)
            
    p.wait()
    if check and p.returncode != 0:
        output_str = "".join(output_lines)
        if not show_logs:
            logger.error(f"Command failed with exit code {p.returncode}")
            logger.error("Command output:\n" + output_str)
        raise subprocess.CalledProcessError(p.returncode, cmd_args, output_str)
    return p.returncode

def get_version_or_prompt(version: str = None, prompt_message: str = "PHP version") -> str:
    """Return the provided version, the active version if set, or prompt the user."""
    import typer
    from ndev.common.constants import CURRENT_LINK, PHP_DIR
    
    if version:
        return version
        
    if CURRENT_LINK.exists() and CURRENT_LINK.is_symlink():
        return CURRENT_LINK.resolve().name
        
    installed_versions = []
    if PHP_DIR.exists():
        for path in PHP_DIR.iterdir():
            if path.is_dir():
                installed_versions.append(path.name)
                
    if installed_versions:
        from packaging.version import parse as parse_version
        try:
            installed_versions = sorted(installed_versions, key=parse_version)
        except Exception:
            installed_versions = sorted(installed_versions)
            
        console.print("\n[bold]Installed PHP Versions[/bold]")
        console.print("----------------------")
        for i, v in enumerate(installed_versions):
            console.print(f" {i + 1}) {v}")
        console.print("")
        
        try:
            choice = typer.prompt("Select PHP version index or enter version directly", default="1")
            try:
                idx = int(choice)
                if 1 <= idx <= len(installed_versions):
                    return installed_versions[idx - 1]
            except ValueError:
                return choice.strip()
        except Exception:
            pass
            
    return typer.prompt(prompt_message).strip()

