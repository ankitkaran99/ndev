import os
import shutil
import socket
import subprocess
import zipfile
import secrets
import webbrowser
import httpx
import typer
from pathlib import Path
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, DownloadColumn, TransferSpeedColumn, TimeRemainingColumn
from ndev.constants import NDEV_DIR, CURRENT_LINK
from ndev.logger import logger

console = Console()

def download_file(url: str, dest_path: Path):
    with dest_path.open("wb") as f:
        with httpx.stream("GET", url, follow_redirects=True) as r:
            if r.status_code != 200:
                raise RuntimeError(f"Failed to download phpMyAdmin. HTTP Status Code: {r.status_code}")
                
            total = int(r.headers.get("Content-Length", 0))
            
            with Progress(
                TextColumn("[bold blue]{task.description}"),
                BarColumn(),
                DownloadColumn(),
                TransferSpeedColumn(),
                TimeRemainingColumn(),
                console=console
            ) as progress:
                task = progress.add_task("Downloading phpMyAdmin...", total=total)
                for chunk in r.iter_bytes(chunk_size=16384):
                    f.write(chunk)
                    progress.update(task, advance=len(chunk))

def extract_zip(zip_path: Path, extract_dir: Path):
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        console=console
    ) as progress:
        task = progress.add_task("Extracting phpMyAdmin...", total=None)
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(extract_dir)

def find_free_port(start_port=8080) -> int:
    port = start_port
    while port < 65535:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except socket.error:
                port += 1
    raise RuntimeError("No free ports found.")

def pma_cmd(
    port: int = typer.Option(None, "--port", "-p", help="Port to run phpMyAdmin on")
):
    """Setup phpMyAdmin if not installed, and launch it using the active PHP version."""
    php_path = CURRENT_LINK / "bin" / "php"
    if not php_path.exists():
        logger.error("No active PHP version found in ndev. Please run `ndev use <version>` first.")
        raise typer.Exit(code=1)
        
    pma_dir = NDEV_DIR / "phpmyadmin"
    
    # 1. Setup if not setup
    if not pma_dir.exists() or not (pma_dir / "index.php").exists():
        console.print("[bold yellow]phpMyAdmin is not set up. Installing now...[/bold yellow]")
        temp_dir = NDEV_DIR / "pma_temp"
        zip_path = NDEV_DIR / "phpmyadmin.zip"
        
        try:
            download_file("https://www.phpmyadmin.net/downloads/phpMyAdmin-latest-all-languages.zip", zip_path)
            
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
            temp_dir.mkdir(parents=True, exist_ok=True)
            
            extract_zip(zip_path, temp_dir)
            
            subfolders = list(temp_dir.glob("phpMyAdmin-*"))
            if not subfolders:
                raise RuntimeError("Could not find extracted phpMyAdmin folder inside zip.")
            src_folder = subfolders[0]
            
            if pma_dir.exists():
                shutil.rmtree(pma_dir)
            pma_dir.mkdir(parents=True, exist_ok=True)
            
            # Move extracted files to pma_dir
            for item in src_folder.iterdir():
                shutil.move(str(item), str(pma_dir / item.name))
                
            # Create config.inc.php
            config_path = pma_dir / "config.inc.php"
            blowfish_secret = secrets.token_hex(16)
            config_content = f"""<?php
$cfg['blowfish_secret'] = '{blowfish_secret}';
$i = 0;
$i++;
$cfg['Servers'][$i]['auth_type'] = 'cookie';
$cfg['Servers'][$i]['host'] = '127.0.0.1';
$cfg['Servers'][$i]['compress'] = false;
$cfg['Servers'][$i]['AllowNoPassword'] = true;
"""
            config_path.write_text(config_content)
            console.print("[bold green]phpMyAdmin setup completed successfully![/bold green]\n")
            
        except Exception as e:
            logger.error(f"Failed to set up phpMyAdmin: {e}")
            # Cleanup on failure
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
            if zip_path.exists():
                zip_path.unlink()
            if pma_dir.exists():
                shutil.rmtree(pma_dir)
            raise typer.Exit(code=1)
        finally:
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
            if zip_path.exists():
                zip_path.unlink()
                
    # 2. Launch phpMyAdmin
    if not port:
        try:
            port = find_free_port(8080)
        except Exception as e:
            logger.error(str(e))
            raise typer.Exit(code=1)
            
    url = f"http://127.0.0.1:{port}"
    console.print(f"\n[bold green]Launching phpMyAdmin built-in server...[/bold green]")
    console.print(f"Address: [bold cyan]{url}[/bold cyan]")
    console.print("[yellow]Press Ctrl+C to stop the server.[/yellow]\n")
    
    # Auto-open browser in a slight delay/background thread or just before starting process
    try:
        webbrowser.open(url)
    except Exception:
        pass
        
    cmd = [
        str(php_path),
        "-S", f"127.0.0.1:{port}",
        "-t", str(pma_dir)
    ]
    
    try:
        # Run in foreground so logs are visible and Ctrl+C works naturally
        subprocess.run(cmd, cwd=pma_dir)
    except KeyboardInterrupt:
        console.print("\n[bold yellow]phpMyAdmin server stopped.[/bold yellow]")
