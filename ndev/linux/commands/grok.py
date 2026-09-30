import tempfile
import subprocess
import shutil
import typer
from pathlib import Path
from rich.console import Console
from ndev.common.logger import logger

console = Console()

def get_vhost_info() -> list[dict]:
    nginx_dir = Path("/etc/nginx/sites-enabled")
    vhosts = []
    if not nginx_dir.exists():
        return vhosts
        
    for file in nginx_dir.glob("*.conf"):
        try:
            content = file.read_text()
            domain = None
            for line in content.splitlines():
                line = line.strip()
                if line.startswith("server_name"):
                    parts = line.split()
                    for p in parts[1:]:
                        p = p.rstrip(";").strip()
                        if p and p != "_":
                            domain = p
                            break
                    if domain:
                        break
            if domain:
                has_ssl = "listen 443 ssl" in content or "listen [::]:443 ssl" in content
                vhosts.append({"domain": domain, "ssl": has_ssl})
        except Exception:
            pass
    return vhosts

def grok_cmd():
    """Proxy local Nginx vhosts over public internet using Ngrok."""
    if not shutil.which("ngrok"):
        logger.error("ngrok is not installed or not in PATH.")
        raise typer.Exit(code=1)
        
    vhosts = get_vhost_info()
    if not vhosts:
        logger.error("No vhosts found in /etc/nginx/sites-enabled.")
        raise typer.Exit(code=1)
        
    console.print("\n[bold]Available VHosts[/bold]")
    console.print("----------------")
    for i, v in enumerate(vhosts):
        ssl_tag = " (HTTPS)" if v["ssl"] else ""
        console.print(f" {i + 1}) {v['domain']}{ssl_tag}")
        
    console.print("")
    choice = typer.prompt("Select vhost index", type=int)
    if choice < 1 or choice > len(vhosts):
        logger.error("Invalid selection.")
        raise typer.Exit(code=1)
        
    selected = vhosts[choice - 1]
    domain = selected["domain"]
    is_ssl = selected["ssl"]
    
    policy_content = f'''on_http_request:
  - actions:
      - type: add-headers
        config:
          headers:
            Host: "{domain}"

on_http_response:
  - expressions:
      - 'res.status_code >= 300 && res.status_code < 400 && "location" in res.headers'
      - 'res.headers["location"][0].contains("://{domain}")'
    actions:
      - type: add-headers
        config:
          headers:
            Location: '${{res.headers["location"][0].replace("https://{domain}", conn.server_name.size() > 0 ? "https://" + conn.server_name : "").replace("http://{domain}", conn.server_name.size() > 0 ? "https://" + conn.server_name : "")}}'
'''
    
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as tmp:
        tmp.write(policy_content)
        policy_file = tmp.name
        
    logger.info(f"Selected domain: {domain}{' (HTTPS)' if is_ssl else ''}")
    logger.info("Starting ngrok...")
    target = "https://localhost:443" if is_ssl else "80"
    cmd = ["ngrok", "http", target, "--traffic-policy-file", policy_file]
    if is_ssl:
        cmd.append("--upstream-tls-verify=false")
    try:
        subprocess.run(cmd)
    finally:
        Path(policy_file).unlink(missing_ok=True)
