import os
import sys
import re
import subprocess
import shutil
import typer
from pathlib import Path
from rich.console import Console
from rich.table import Table
from ndev.logger import logger

console = Console()

def get_user_ndev_dir() -> Path:
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user:
        try:
            import pwd
            return Path(pwd.getpwnam(sudo_user).pw_dir) / ".ndev"
        except Exception:
            pass
    return Path(os.path.expanduser("~/.ndev"))

def service_exists(service: str) -> bool:
    if service.startswith("ndev-"):
        version = service[5:]
        return (get_user_ndev_dir() / "php" / version).exists()
        
    if shutil.which("systemctl"):
        res = subprocess.run(["systemctl", "list-unit-files", f"{service}.service"], capture_output=True, text=True)
        return service in res.stdout
    else:
        return Path(f"/etc/init.d/{service}").exists()

def service_status(service: str) -> str:
    if not service_exists(service):
        return "NOT INSTALLED"
        
    if service.startswith("ndev-"):
        version = service[5:]
        script_path = sys.argv[0]
        res = subprocess.run([sys.executable, script_path, "status", version], capture_output=True, text=True)
        if "Running" in res.stdout:
            return "RUNNING"
        else:
            return "STOPPED"
            
    if shutil.which("systemctl"):
        res = subprocess.run(["systemctl", "is-active", "--quiet", service])
        return "RUNNING" if res.returncode == 0 else "STOPPED"
    return "UNKNOWN"

def get_php_versions() -> list[str]:
    versions = []
    ndev_dir = get_user_ndev_dir() / "php"
    if ndev_dir.exists():
        for d in ndev_dir.iterdir():
            if d.is_dir():
                versions.append(d.name)
    return sorted(versions)

def manage_service(service: str, action: str):
    console.print(f"\n[yellow]{action.upper()} -> {service}[/yellow]")
    if service.startswith("ndev-"):
        version = service[5:]
        script_path = sys.argv[0]
        subprocess.run([sys.executable, script_path, action, version])
    else:
        cmd = ["sudo"]
        if shutil.which("systemctl"):
            cmd.extend(["systemctl", action, service])
        else:
            cmd.extend(["service", service, action])
        subprocess.run(cmd)
    console.print("[green]Done[/green]")

def ctl_cmd():
    """Interactive dashboard to start, stop, or restart local web services."""
    console.print("[bold blue]==================================================================[/bold blue]")
    console.print("[bold blue]                 Web Service Management Tool                      [/bold blue]")
    console.print("[bold blue]==================================================================[/bold blue]\n")
    
    # 1. Detect base services status
    base_services = ["nginx", "mariadb"]
    php_versions = get_php_versions()
    
    table = Table(title="Detected Services")
    table.add_column("Service", style="cyan")
    table.add_column("Type", style="magenta")
    table.add_column("Status", style="bold")
    
    for svc in base_services:
        if service_exists(svc):
            status = service_status(svc)
            color = "green" if status == "RUNNING" else "red"
            table.add_row(svc, "Base Service", f"[{color}]{status}[/{color}]")
            
    for version in php_versions:
        svc = f"ndev-{version}"
        status = service_status(svc)
        color = "green" if status == "RUNNING" else "red"
        table.add_row(svc, "ndev FPM", f"[{color}]{status}[/{color}]")
            
    console.print(table)
    console.print("")
    
    # 2. Select Action
    console.print("[bold]Select Action:[/bold]")
    console.print("  1) Restart (Default)")
    console.print("  2) Start")
    console.print("  3) Stop")
    choice = typer.prompt("Enter choice [1-3]", default=1)
    
    action_map = {1: "restart", 2: "start", 3: "stop"}
    action = action_map.get(choice, "restart")
    
    # 3. Select Service
    console.print("\n[bold]Select Service:[/bold]")
    console.print("  1) Nginx")
    console.print("  2) MariaDB")
    console.print("  3) PHP-FPM")
    console.print("  4) All Services")
    svc_choice = typer.prompt("Enter choice [1-4]", default=4)
    
    php_ver = None
    if svc_choice in [3, 4]:
        if not php_versions:
            logger.error("No PHP-FPM versions detected.")
            raise typer.Exit(code=1)
            
        console.print("\n[bold]Available PHP Versions[/bold]")
        console.print("----------------------")
        for i, version in enumerate(php_versions):
            status = service_status(f"ndev-{version}")
            console.print(f"  {i + 1}) PHP {version:<12} {status} (ndev)")
                
        console.print("")
        php_idx = typer.prompt("Select PHP version index", type=int)
        if php_idx < 1 or php_idx > len(php_versions):
            logger.error("Invalid selection.")
            raise typer.Exit(code=1)
        php_ver = php_versions[php_idx - 1]
        
    services_to_manage = []
    if svc_choice == 1:
        services_to_manage = ["nginx"]
    elif svc_choice == 2:
        services_to_manage = ["mariadb"]
    elif svc_choice == 3:
        services_to_manage = [f"ndev-{php_ver}"]
    elif svc_choice == 4:
        services_to_manage = ["nginx", "mariadb"]
        if php_ver:
            services_to_manage.append(f"ndev-{php_ver}")
                
    console.print("\n[bold blue]Executing requested actions...[/bold blue]")
    for svc in services_to_manage:
        manage_service(svc, action)
        
    console.print("\n[bold green]Completed successfully.[/bold green]")
    console.print("[bold blue]==================================================================[/bold blue]")
