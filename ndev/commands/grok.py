import re
import tempfile
import subprocess
import shutil
import typer
from pathlib import Path
from rich.console import Console
from ndev.logger import logger

console = Console()

def get_vhosts() -> list[str]:
    nginx_dir = Path("/etc/nginx/sites-enabled")
    domains = []
    if not nginx_dir.exists():
        return domains
        
    for file in nginx_dir.glob("*.conf"):
        try:
            content = file.read_text()
            for line in content.splitlines():
                line = line.strip()
                if line.startswith("server_name"):
                    parts = line.split()
                    for p in parts[1:]:
                        p = p.rstrip(";").strip()
                        if p and p != "_":
                            domains.append(p)
                            break
        except Exception:
            pass
    return domains

def grok_cmd():
    """Proxy local Nginx vhosts over public internet using Ngrok."""
    if not shutil.which("ngrok"):
        logger.error("ngrok is not installed or not in PATH.")
        raise typer.Exit(code=1)
        
    domains = get_vhosts()
    if not domains:
        logger.error("No vhosts found in /etc/nginx/sites-enabled.")
        raise typer.Exit(code=1)
        
    console.print("\n[bold]Available VHosts[/bold]")
    console.print("----------------")
    for i, d in enumerate(domains):
        console.print(f" {i + 1}) {d}")
        
    console.print("")
    choice = typer.prompt("Select vhost index", type=int)
    if choice < 1 or choice > len(domains):
        logger.error("Invalid selection.")
        raise typer.Exit(code=1)
        
    domain = domains[choice - 1]
    
    policy_content = f"""on_http_request:
  - actions:
      - type: add-headers
        config:
          headers:
            Host: {domain}
"""
    
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as tmp:
        tmp.write(policy_content)
        policy_file = tmp.name
        
    logger.info(f"Selected domain: {domain}")
    logger.info("Starting ngrok...")
    try:
        subprocess.run(["ngrok", "http", "80", "--traffic-policy-file", policy_file])
    finally:
        Path(policy_file).unlink(missing_ok=True)
