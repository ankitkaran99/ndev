from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.table import Table

if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

from .core import (
    db as db_core,
    ext as ext_core,
    fcgi,
    grok as grok_core,
    logs as logs_core,
    mailpit as mailpit_core,
    mkcert as mkcert_core,
    paths,
    php,
    pma as pma_core,
    services,
    setup as setup_core,
    upgrade as upgrade_core,
    vhost as vhost_core,
)
from .core.elevate import is_admin

console = Console()


@click.group(invoke_without_command=True)
@click.pass_context
def main(ctx: click.Context):
    """ndev: Windows PHP/FastCGI/Nginx/MariaDB developer environment manager."""
    paths.ensure_dirs()
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


# ---- Core PHP Version Management -------------------------------------------

@main.command()
@click.option("--all", "--archives", "include_archives", is_flag=True, help="Include archived older PHP releases.")
def available(include_archives):
    """List PHP versions available to install from windows.php.net."""
    releases = php.list_available(include_archives=include_archives)
    if not releases:
        console.print("[yellow]Could not fetch PHP releases. Check internet connectivity.[/yellow]")
        return

    table = Table(title="Available PHP Versions (windows.php.net)")
    table.add_column("Version", style="bold cyan")
    table.add_column("Type", style="magenta")
    table.add_column("Arch", style="green")
    table.add_column("Toolset")
    table.add_column("Source")

    for r in releases:
        tag = "TS (Thread Safe)" if r.thread_safe else "NTS (Non-Thread-Safe)"
        src = "Archive" if r.is_archive else "Current"
        table.add_row(r.version, tag, r.arch, r.toolset, src)

    console.print(table)


@main.command()
@click.argument("version")
@click.option("--arch", default="x64", type=click.Choice(["x64", "x86"]))
@click.option("--thread-safe/--non-thread-safe", default=True, help="Install Thread-Safe (TS) or Non-Thread-Safe (NTS) build.")
def install(version, arch, thread_safe):
    """Download and install a PHP version (e.g. 8.4, 8.4.25, 7.4)."""
    with console.status(f"[bold green]Resolving PHP {version} ({arch}, {'TS' if thread_safe else 'NTS'})...[/bold green]"):
        release = php.resolve_release(version, arch=arch, thread_safe=thread_safe)
    
    if not release:
        raise click.ClickException(
            f"No matching release found for '{version}' ({arch}, {'TS' if thread_safe else 'NTS'}). "
            f"Run `ndev available --all` to check available versions."
        )

    console.print(f"Downloading [cyan]PHP {release.version}[/cyan] from {release.zip_url} ...")
    with console.status("[bold green]Downloading archive...[/bold green]"):
        zip_path = php.download_release(release)

    with console.status(f"[bold green]Extracting and configuring PHP {release.version}...[/bold green]"):
        target = php.install(release.version, zip_path)

    console.print(f"[bold green]Successfully installed PHP {release.version}[/bold green] -> {target}")
    if php.get_current_version() == release.version:
        console.print(f"[green]PHP {release.version} is now the active CLI version.[/green]")


@main.command()
@click.argument("version")
def uninstall(version):
    """Remove an installed PHP version."""
    try:
        target_ver = php.resolve_installed(version)
    except FileNotFoundError as e:
        raise click.ClickException(str(e))

    php.uninstall(target_ver)
    console.print(f"[bold green]Removed PHP {target_ver}[/bold green]")


@main.command(name="list")
def list_cmd():
    """List locally installed PHP versions and running status."""
    installed = php.list_installed()
    if not installed:
        console.print("[yellow]No PHP versions installed yet. Run `ndev install <version>` (e.g. `ndev install 8.4`).[/yellow]")
        return

    curr = php.get_current_version()
    table = Table(title="Installed PHP Versions")
    table.add_column("Version", style="bold cyan")
    table.add_column("Active", style="green")
    table.add_column("FastCGI Pool", style="magenta")
    table.add_column("Path")

    for v in installed:
        is_active = "[bold green]* (active)[/bold green]" if v == curr else ""
        workers = fcgi.status(v)
        pool_status = f"[green]Running ({len(workers)} workers)[/green]" if workers else "[red]Stopped[/red]"
        table.add_row(v, is_active, pool_status, str(paths.version_dir(v)))

    console.print(table)


@main.command()
def current():
    """Display the currently active PHP version."""
    v = php.get_current_version()
    if v:
        workers = fcgi.status(v)
        pool_info = f" (FastCGI pool: {len(workers)} worker(s))" if workers else " (FastCGI pool: stopped)"
        console.print(f"Active PHP version: [bold cyan]{v}[/bold cyan]{pool_info}")
    else:
        console.print("[yellow]No active PHP version set -- run `ndev use <version>`[/yellow]")


@main.command(name="use")
@click.argument("version")
def use_cmd(version):
    """Set a PHP version as the active CLI binary."""
    try:
        target_ver = php.use(version)
    except FileNotFoundError as e:
        raise click.ClickException(str(e))

    console.print(f"[bold green]Now using PHP {target_ver}.[/bold green]")
    shim_on_path = str(paths.SHIM_DIR).lower() in os.environ.get("PATH", "").lower()
    if not shim_on_path:
        console.print(f"[yellow]Ensure {paths.SHIM_DIR} is in your system PATH to run `php` directly.[/yellow]")


@main.command()
def update():
    """Check if installed PHP versions have newer releases available."""
    installed = php.list_installed()
    if not installed:
        console.print("[yellow]No PHP versions installed yet.[/yellow]")
        return

    available_rels = php.list_available(include_archives=False)
    table = Table(title="PHP Version Update Check")
    table.add_column("Installed", style="bold cyan")
    table.add_column("Latest Available", style="green")
    table.add_column("Status")

    for v in installed:
        parts = v.split(".")
        mm = f"{parts[0]}.{parts[1]}" if len(parts) >= 2 else v
        matching = [r for r in available_rels if r.major_minor == mm]
        if matching:
            latest = matching[0].version
            if latest != v:
                table.add_row(v, latest, f"[bold yellow]Update Available[/bold yellow] (`ndev install {latest}`)")
            else:
                table.add_row(v, latest, "[green]Up to date[/green]")
        else:
            table.add_row(v, "N/A (Archived/Custom)", "[dim]No active feed[/dim]")

    console.print(table)


@main.command()
@click.option("--downloads/--no-downloads", default=True, help="Clean downloaded archive cache.")
@click.option("--run-state/--no-run-state", default=True, help="Clean dead PID and state files.")
@click.option("--temp/--no-temp", default=True, help="Clean temporary session and cache files.")
@click.option("--logs/--no-logs", "clean_logs", default=False, help="Truncate or clear log files in nginx and php.")
def clean(downloads, run_state, temp, clean_logs):
    """Clean up cached downloads, temporary session files, logs, and stale runtime state files."""
    count = 0
    if downloads and paths.DOWNLOADS_DIR.exists():
        for item in paths.DOWNLOADS_DIR.iterdir():
            try:
                if item.is_file():
                    item.unlink()
                    count += 1
                elif item.is_dir():
                    shutil.rmtree(item)
                    count += 1
            except Exception:
                pass

    if temp:
        temp_dir = paths.TEMP_DIR
        if temp_dir.exists():
            for item in temp_dir.rglob("*"):
                if item.is_file():
                    try:
                        item.unlink()
                        count += 1
                    except Exception:
                        pass

    if clean_logs:
        if paths.NGINX_LOGS_DIR.exists():
            for p in paths.NGINX_LOGS_DIR.glob("*.log"):
                try:
                    p.write_text("", encoding="utf-8")
                    count += 1
                except Exception:
                    pass
        for v in php.list_installed():
            v_dir = paths.version_dir(v)
            for log_file in [v_dir / "php_error.log", v_dir / "error.log"]:
                if log_file.exists():
                    try:
                        log_file.write_text("", encoding="utf-8")
                        count += 1
                    except Exception:
                        pass

    if run_state and paths.RUN_DIR.exists():
        for item in paths.RUN_DIR.glob("*.json"):
            try:
                if item.name.startswith("php_"):
                    ver = item.stem.replace("php_", "")
                    if not fcgi.status(ver):
                        item.unlink(missing_ok=True)
                        count += 1
                elif item.name == "mariadb.json":
                    if not services.mariadb_is_running():
                        item.unlink(missing_ok=True)
                        count += 1
                elif item.name == "pma.json":
                    if not pma_core.status():
                        item.unlink(missing_ok=True)
                        count += 1
            except Exception:
                pass

    console.print(f"[bold green]Cleaned {count} cached/stale files.[/bold green]")


@main.command()
@click.argument("target", required=False)
@click.option("--lines", "-n", default=50, help="Number of lines to display.")
def logs(target, lines):
    """View / tail service and vhost logs."""
    all_logs = logs_core.get_available_logs()
    matched_path = None

    if not target:
        if not all_logs:
            console.print("[yellow]No active log files found.[/yellow]")
            return
        console.print("\n[bold]Available Log Files[/bold]")
        console.print("-------------------")
        log_items = list(all_logs.items())
        for idx, (name, p) in enumerate(log_items, 1):
            console.print(f" {idx}) {name:<20} ({p})")
        console.print("")
        choice = click.prompt("Select log file index to view", default=1, type=int)
        if 1 <= choice <= len(log_items):
            matched_path = log_items[choice - 1][1]
        else:
            return
    else:
        # Match target
        if target in all_logs:
            matched_path = all_logs[target]
        else:
            for name, p in all_logs.items():
                if target.lower() in name.lower() or target.lower() in p.name.lower():
                    matched_path = p
                    break

        if not matched_path:
            # Check direct path in nginx logs
            direct = paths.NGINX_LOGS_DIR / f"{target}.error.log"
            if direct.exists():
                matched_path = direct
            else:
                direct_access = paths.NGINX_LOGS_DIR / f"{target}.access.log"
                if direct_access.exists():
                    matched_path = direct_access

    if not matched_path or not matched_path.exists():
        raise click.ClickException(f"Log file for '{target}' not found.")

    tail = logs_core.read_log_tail(matched_path, lines=lines)
    console.print(f"\n[bold cyan]--- Showing last {len(tail)} lines of {matched_path} ---[/bold cyan]")
    for line in tail:
        click.echo(line)


@main.command()
def doctor():
    """Diagnose the ndev environment and components."""
    table = Table(title="ndev Doctor Diagnostic Report")
    table.add_column("Component", style="bold cyan")
    table.add_column("Status")
    table.add_column("Details")

    table.add_row("ndev Home", "[green]OK[/green]", str(paths.NDEV_HOME))
    
    admin_st = "[green]YES[/green]" if is_admin() else "[yellow]NO (Standard User)[/yellow]"
    table.add_row("Running as Admin", admin_st, "UAC elevation is handled on-demand")

    installed_phps = php.list_installed()
    curr_php = php.get_current_version()
    php_detail = f"Installed: {', '.join(installed_phps) if installed_phps else 'none'} | Active: {curr_php or 'none'}"
    php_status = "[green]OK[/green]" if installed_phps else "[yellow]MISSING[/yellow]"
    table.add_row("PHP Runtimes", php_status, php_detail)

    # Nginx
    nginx_inst = services.nginx_is_installed()
    if nginx_inst:
        t_res = services.nginx_test_config()
        t_ok = "Config OK" if t_res.returncode == 0 else f"Config Error: {t_res.stderr.strip()}"
        run_st = "Running" if services.nginx_is_running() else "Stopped"
        table.add_row("Nginx Web Server", "[green]OK[/green]", f"{run_st} | {t_ok} ({paths.NGINX_DIR})")
    else:
        table.add_row("Nginx Web Server", "[red]MISSING[/red]", "Run `ndev setup` to install")

    # MariaDB
    mariadb_inst = services.mariadb_is_installed()
    if mariadb_inst:
        run_st = "Running" if services.mariadb_is_running() else "Stopped"
        table.add_row("MariaDB Server", "[green]OK[/green]", f"{run_st} ({paths.MARIADB_DIR})")
    else:
        table.add_row("MariaDB Server", "[red]MISSING[/red]", "Run `ndev setup` to install")

    # mkcert
    mkcert_exe = paths.SHIM_DIR / "mkcert.exe"
    if mkcert_exe.exists() or shutil.which("mkcert"):
        ca_ok = mkcert_core.is_ca_installed()
        detail = "Installed and root CA trusted" if ca_ok else "Installed (run `ndev setup` to trust root CA)"
        table.add_row("mkcert (Local SSL)", "[green]OK[/green]", detail)
    else:
        table.add_row("mkcert (Local SSL)", "[yellow]MISSING[/yellow]", "Run `ndev setup` to install")

    # ngrok
    ngrok_exe = paths.SHIM_DIR / "ngrok.exe"
    if ngrok_exe.exists() or shutil.which("ngrok"):
        table.add_row("ngrok Tunneling", "[green]OK[/green]", "Installed and available for public tunnels")
    else:
        table.add_row("ngrok Tunneling", "[yellow]MISSING[/yellow]", "Run `ndev setup` to install")

    # Composer
    composer_bat = paths.SHIM_DIR / "composer.bat"
    if composer_bat.exists() or shutil.which("composer"):
        table.add_row("Composer", "[green]OK[/green]", "Installed and available on CLI")
    else:
        table.add_row("Composer", "[yellow]MISSING[/yellow]", "Run `ndev setup` to install")

    # Root CA Bundle
    if paths.CACERT_PATH.exists():
        table.add_row("Root CA Bundle", "[green]OK[/green]", f"Available for cURL/OpenSSL ({paths.CACERT_PATH.name})")
    else:
        table.add_row("Root CA Bundle", "[yellow]MISSING[/yellow]", "Run `ndev setup` to download cacert.pem")

    # PATH Check
    shim_on_path = str(paths.SHIM_DIR).lower() in os.environ.get("PATH", "").lower()
    path_status = "[green]OK[/green]" if shim_on_path else "[yellow]WARNING[/yellow]"
    path_detail = f"Found on PATH ({paths.SHIM_DIR})" if shim_on_path else f"Add {paths.SHIM_DIR} to your system PATH"
    table.add_row("Shims on PATH", path_status, path_detail)

    console.print(table)


# ---- Top-Level Service Commands (start / stop / restart / reload / status) ---

def _resolve_target(target: str | None) -> str:
    if not target:
        curr = php.get_current_version()
        if curr:
            return curr
        installed = php.list_installed()
        if installed:
            return installed[-1]
        raise click.ClickException("No target or active PHP version specified.")
    try:
        return php.resolve_installed(target)
    except Exception:
        return target


@main.command()
@click.argument("target", required=False)
def start(target):
    """Start a service (e.g. `8.4`, `pma`, `nginx`, `mariadb`, or `all`)."""
    t = (target or "").lower()
    if t == "all":
        services.nginx_start()
        services.mariadb_start()
        try:
            pma_core.start()
        except Exception:
            pass
        for v in php.list_installed():
            cfg = paths.load_config()
            try:
                fcgi.start(v, php.php_cgi_exe(v), cfg["fcgi_workers_per_version"], cfg["fcgi_base_port"])
            except Exception:
                pass
        console.print("[bold green]Started all services.[/bold green]")
        return

    if t in ["pma", "phpmyadmin"]:
        if pma_core.status():
            st = pma_core.status()
            console.print(f"[yellow]phpMyAdmin is already running at {st.get('url', 'http://127.0.0.1:8080')} (PID {st.get('pid')})[/yellow]")
            return
        pid = pma_core.start()
        console.print(f"[bold green]phpMyAdmin started at http://127.0.0.1:8080 (PID {pid})[/bold green]")
        return

    if t in ["mailpit", "mail"]:
        st = mailpit_core.status()
        if st:
            console.print(f"[yellow]Mailpit is already running at {st.get('url', 'http://127.0.0.1:8025')} (PID {st.get('pid')})[/yellow]")
            return
        if not mailpit_core.is_installed():
            console.print("[yellow]Mailpit not installed - downloading now...[/yellow]")
            with console.status("[bold green]Downloading Mailpit...[/bold green]"):
                mailpit_core.install()
        pid = mailpit_core.start()
        console.print(f"[bold green]Mailpit started at http://127.0.0.1:8025 (PID {pid})[/bold green]")
        return

    if t == "nginx":
        if services.nginx_is_running():
            console.print("[yellow]Nginx is already running.[/yellow]")
            return
        services.nginx_start()
        console.print("[bold green]Nginx started.[/bold green]")
        return

    if t in ["mariadb", "mysql"]:
        if services.mariadb_is_running():
            st = services.mariadb_status()
            pid_str = f" (PID {st.get('pid')})" if st and st.get('pid') else ""
            console.print(f"[yellow]MariaDB is already running{pid_str}.[/yellow]")
            return
        pid = services.mariadb_start()
        console.print(f"[bold green]MariaDB started (PID {pid}).[/bold green]")
        return

    # Treat as PHP version
    v = _resolve_target(target)
    existing = fcgi.status(v)
    if existing:
        ports = ", ".join(str(w.port) for w in existing)
        console.print(f"[yellow]PHP {v} FastCGI pool is already running ({len(existing)} worker(s) on ports: {ports})[/yellow]")
        return
    cfg = paths.load_config()
    workers = fcgi.start(v, php.php_cgi_exe(v), cfg["fcgi_workers_per_version"], cfg["fcgi_base_port"])
    ports = ", ".join(str(w.port) for w in workers)
    console.print(f"[bold green]Started PHP {v} FastCGI pool ({len(workers)} workers on ports: {ports})[/bold green]")


@main.command()
@click.argument("target", required=False)
def stop(target):
    """Stop a service (e.g. `8.4`, `pma`, `nginx`, `mariadb`, or `all`)."""
    t = (target or "").lower()
    if t == "all":
        services.nginx_stop()
        services.mariadb_stop()
        pma_core.stop()
        for v in php.list_installed():
            fcgi.stop(v)
        console.print("[bold green]Stopped all services.[/bold green]")
        return

    if t in ["pma", "phpmyadmin"]:
        if not pma_core.status():
            console.print("[yellow]phpMyAdmin is not running.[/yellow]")
            return
        pma_core.stop()
        console.print("[bold green]phpMyAdmin stopped.[/bold green]")
        return

    if t in ["mailpit", "mail"]:
        if not mailpit_core.status():
            console.print("[yellow]Mailpit is not running.[/yellow]")
            return
        mailpit_core.stop()
        console.print("[bold green]Mailpit stopped.[/bold green]")
        return

    if t == "nginx":
        if not services.nginx_is_running():
            console.print("[yellow]Nginx is not running.[/yellow]")
            return
        services.nginx_stop()
        console.print("[bold green]Nginx stopped.[/bold green]")
        return

    if t in ["mariadb", "mysql"]:
        if not services.mariadb_is_running():
            console.print("[yellow]MariaDB is not running.[/yellow]")
            return
        services.mariadb_stop()
        console.print("[bold green]MariaDB stopped.[/bold green]")
        return

    v = _resolve_target(target)
    if not fcgi.status(v):
        console.print(f"[yellow]PHP {v} FastCGI pool is not running.[/yellow]")
        return
    fcgi.stop(v)
    console.print(f"[bold green]Stopped PHP {v} FastCGI pool.[/bold green]")


@main.command()
@click.argument("target", required=False)
def restart(target):
    """Restart a service (e.g. `8.4`, `pma`, `mailpit`, `nginx`, `mariadb`, or `all`)."""
    t = (target or "").lower()
    if t == "all":
        services.nginx_stop()
        services.mariadb_stop()
        pma_core.stop()
        for v in php.list_installed():
            fcgi.stop(v)
        services.nginx_start()
        services.mariadb_start()
        try:
            pma_core.start()
        except Exception:
            pass
        for v in php.list_installed():
            cfg = paths.load_config()
            try:
                fcgi.start(v, php.php_cgi_exe(v), cfg["fcgi_workers_per_version"], cfg["fcgi_base_port"])
            except Exception:
                pass
        console.print("[bold green]Restarted all services.[/bold green]")
        return

    if t in ["pma", "phpmyadmin"]:
        pid = pma_core.restart()
        console.print(f"[bold green]phpMyAdmin restarted at http://127.0.0.1:8080 (PID {pid})[/bold green]")
        return

    if t in ["mailpit", "mail"]:
        if not mailpit_core.is_installed():
            raise click.ClickException("Mailpit is not installed. Run `ndev mailpit install` first.")
        pid = mailpit_core.restart()
        console.print(f"[bold green]Mailpit restarted at http://127.0.0.1:8025 (PID {pid})[/bold green]")
        return

    if t == "nginx":
        services.nginx_stop()
        services.nginx_start()
        console.print("[bold green]Nginx restarted.[/bold green]")
        return

    if t in ["mariadb", "mysql"]:
        services.mariadb_stop()
        pid = services.mariadb_start()
        console.print(f"[bold green]MariaDB restarted (PID {pid}).[/bold green]")
        return

    v = _resolve_target(target)
    workers = fcgi.restart(v)
    ports = ", ".join(str(w.port) for w in workers)
    console.print(f"[bold green]Restarted PHP {v} FastCGI pool ({len(workers)} workers on ports: {ports})[/bold green]")


@main.command()
@click.argument("target", required=False)
def reload(target):
    """Reload service configuration (e.g. Nginx or PHP)."""
    t = (target or "nginx").lower()
    if t == "nginx":
        services.nginx_reload()
        console.print("[bold green]Nginx configuration reloaded.[/bold green]")
        return

    # Default to restarting target
    restart.callback(target)


@main.command()
@click.argument("target", required=False)
def status(target):
    """Show status of all services or a specific target."""
    if target:
        t = target.lower()
        if t in ["pma", "phpmyadmin"]:
            st = pma_core.status()
            if st:
                console.print(f"phpMyAdmin: [bold green]Running[/bold green] at {st['url']} (PID {st['pid']})")
            else:
                console.print("phpMyAdmin: [bold red]Stopped[/bold red]")
            return

        if t in ["mailpit", "mail"]:
            st = mailpit_core.status()
            if st:
                console.print(f"Mailpit: [bold green]Running[/bold green] at {st['url']} | SMTP {st['smtp']} (PID {st['pid']})")
            else:
                console.print("Mailpit: [bold red]Stopped[/bold red]")
            return

        if t == "nginx":
            run = services.nginx_is_running()
            console.print(f"Nginx: {'[bold green]Running[/bold green]' if run else '[bold red]Stopped[/bold red]'}")
            return

        if t in ["mariadb", "mysql"]:
            st = services.mariadb_status()
            if st and st.get("running"):
                console.print(f"MariaDB: [bold green]Running[/bold green] (PID {st['pid']})")
            else:
                console.print("MariaDB: [bold red]Stopped[/bold red]")
            return

        # PHP target
        v = _resolve_target(target)
        workers = fcgi.status(v)
        if workers:
            ports = ", ".join(str(w.port) for w in workers)
            console.print(f"PHP {v}: [bold green]Running[/bold green] ({len(workers)} workers on ports: {ports})")
        else:
            console.print(f"PHP {v}: [bold red]Stopped[/bold red]")
        return

    # Overall status table
    table = Table(title="ndev Service Status Dashboard")
    table.add_column("Service", style="bold cyan")
    table.add_column("Type", style="magenta")
    table.add_column("Status")
    table.add_column("Details")

    # Nginx
    if services.nginx_is_installed():
        ng_run = services.nginx_is_running()
        table.add_row(
            "Nginx",
            "Web Server",
            "[bold green]RUNNING[/bold green]" if ng_run else "[bold red]STOPPED[/bold red]",
            f"Config dir: {paths.NGINX_CONF_D}"
        )
    else:
        table.add_row("Nginx", "Web Server", "[yellow]NOT INSTALLED[/yellow]", "Run `ndev setup`")

    # MariaDB
    if services.mariadb_is_installed():
        mb_st = services.mariadb_status()
        mb_run = mb_st and mb_st.get("running")
        mb_detail = f"PID {mb_st['pid']} (port 3306)" if mb_run else f"Data: {paths.MARIADB_DIR / 'data'}"
        table.add_row(
            "MariaDB",
            "Database",
            "[bold green]RUNNING[/bold green]" if mb_run else "[bold red]STOPPED[/bold red]",
            mb_detail
        )
    else:
        table.add_row("MariaDB", "Database", "[yellow]NOT INSTALLED[/yellow]", "Run `ndev setup`")

    # phpMyAdmin
    pma_st = pma_core.status()
    if pma_st:
        table.add_row("phpMyAdmin", "Admin Tool", "[bold green]RUNNING[/bold green]", f"{pma_st['url']} (PID {pma_st['pid']})")
    else:
        pma_installed = (paths.PMA_DIR / "index.php").exists()
        table.add_row("phpMyAdmin", "Admin Tool", "[bold red]STOPPED[/bold red]" if pma_installed else "[dim]NOT INSTALLED[/dim]", "http://127.0.0.1:8080")

    # Mailpit
    mp_st = mailpit_core.status()
    if mp_st:
        table.add_row("Mailpit", "Email Sandbox", "[bold green]RUNNING[/bold green]", f"{mp_st['url']} | SMTP {mp_st['smtp']} (PID {mp_st['pid']})")
    elif mailpit_core.is_installed():
        table.add_row("Mailpit", "Email Sandbox", "[bold red]STOPPED[/bold red]", f"http://127.0.0.1:{mailpit_core.DEFAULT_WEB_PORT} | SMTP 127.0.0.1:{mailpit_core.DEFAULT_SMTP_PORT}")

    # PHP versions
    curr = php.get_current_version()
    installed_phps = php.list_installed()
    if not installed_phps:
        table.add_row("PHP (CLI/Pool)", "FastCGI Pool", "[yellow]NOT INSTALLED[/yellow]", "Run `ndev install <version>`")
    else:
        for v in installed_phps:
            workers = fcgi.status(v)
            is_act = " [bold green](active CLI)[/bold green]" if v == curr else ""
            if workers:
                table.add_row(
                    f"PHP {v}{is_act}",
                    "FastCGI Pool",
                    "[bold green]RUNNING[/bold green]",
                    f"{len(workers)} worker(s) | Ports: {', '.join(str(w.port) for w in workers)}"
                )
            else:
                table.add_row(
                    f"PHP {v}{is_act}",
                    "FastCGI Pool",
                    "[bold red]STOPPED[/bold red]",
                    f"Binary: {php.php_exe(v)}"
                )

    console.print(table)


# ---- Interactive Terminal UI Dashboard (ui / tui / dashboard) --------------

@main.command(name="ui")
def ui_cmd():
    """Launch the interactive Textual TUI dashboard."""
    from .tui import run_dashboard
    run_dashboard()


@main.command(name="tui", hidden=True)
def tui_alias():
    """Alias for ui."""
    ui_cmd.callback()


@main.command(name="dashboard", hidden=True)
def dashboard_alias():
    """Alias for ui."""
    ui_cmd.callback()


# ---- Interactive Control Dashboard (ctl) -----------------------------------

@main.group(invoke_without_command=True)
@click.pass_context
def ctl(ctx: click.Context):
    """Interactive dashboard and process control for Nginx, MariaDB, and PHP."""
    if ctx.invoked_subcommand is not None:
        return

    console.print("\n[bold blue]==================================================================[/bold blue]")
    console.print("[bold blue]                   ndev Web Services Control                      [/bold blue]")
    console.print("[bold blue]==================================================================[/bold blue]\n")

    status.callback(None)
    console.print("")
    console.print("[bold]Select Action:[/bold]")
    console.print("  1) Restart (Default)")
    console.print("  2) Start")
    console.print("  3) Stop")
    console.print("  4) Reload Nginx")
    
    action_choice = click.prompt("Enter choice [1-4]", default=1, type=int)
    action_map = {1: "restart", 2: "start", 3: "stop", 4: "reload"}
    act = action_map.get(action_choice, "restart")

    if act == "reload":
        reload.callback("nginx")
        return

    console.print("\n[bold]Select Service:[/bold]")
    console.print("  1) Nginx")
    console.print("  2) MariaDB")
    console.print("  3) phpMyAdmin (pma)")
    console.print("  4) PHP FastCGI Pool")
    console.print("  5) All Services")
    svc_choice = click.prompt("Enter choice [1-5]", default=5, type=int)

    curr_php = php.get_current_version()
    php_versions = php.list_installed()

    if svc_choice == 1:
        if act == "start":
            start.callback("nginx")
        elif act == "stop":
            stop.callback("nginx")
        elif act == "restart":
            restart.callback("nginx")
        return

    elif svc_choice == 2:
        if act == "start":
            start.callback("mariadb")
        elif act == "stop":
            stop.callback("mariadb")
        elif act == "restart":
            restart.callback("mariadb")
        return

    elif svc_choice == 3:
        if act == "start":
            start.callback("pma")
        elif act == "stop":
            stop.callback("pma")
        elif act == "restart":
            restart.callback("pma")
        return

    elif svc_choice == 4:
        if not php_versions:
            console.print("[yellow]No PHP versions installed. Run `ndev install <version>` first.[/yellow]")
            return
        console.print("\n[bold]Select PHP FastCGI Pool:[/bold]")
        default_idx = 1
        for idx, pv in enumerate(php_versions, 1):
            is_act = " [bold green](active CLI)[/bold green]" if pv == curr_php else ""
            if pv == curr_php:
                default_idx = idx
            console.print(f"  {idx}) PHP {pv}{is_act}")
        all_idx = len(php_versions) + 1
        console.print(f"  {all_idx}) All Installed PHP Pools")

        php_choice = click.prompt("Enter choice", default=default_idx, type=int)
        if php_choice == all_idx:
            for pv in php_versions:
                if act == "start":
                    start.callback(pv)
                elif act == "stop":
                    stop.callback(pv)
                elif act == "restart":
                    restart.callback(pv)
        elif 1 <= php_choice <= len(php_versions):
            target_pv = php_versions[php_choice - 1]
            if act == "start":
                start.callback(target_pv)
            elif act == "stop":
                stop.callback(target_pv)
            elif act == "restart":
                restart.callback(target_pv)
        return

    elif svc_choice == 5:
        # All Services
        selected_php_pools = []
        if php_versions:
            console.print("\n[bold]Select PHP FastCGI Pool to include with All Services:[/bold]")
            default_idx = 1
            for idx, pv in enumerate(php_versions, 1):
                is_act = " [bold green](active CLI)[/bold green]" if pv == curr_php else ""
                if pv == curr_php:
                    default_idx = idx
                console.print(f"  {idx}) PHP {pv}{is_act}")
            all_idx = len(php_versions) + 1
            none_idx = len(php_versions) + 2
            console.print(f"  {all_idx}) All Installed PHP Pools")
            console.print(f"  {none_idx}) None (Web & Database Only)")

            php_choice = click.prompt("Enter choice", default=default_idx, type=int)
            if php_choice == all_idx:
                selected_php_pools = list(php_versions)
            elif 1 <= php_choice <= len(php_versions):
                selected_php_pools = [php_versions[php_choice - 1]]
            else:
                selected_php_pools = []

        console.print(f"\n[bold blue]Executing '{act}' on selected services...[/bold blue]")

        # Process Nginx
        try:
            if act == "start":
                services.nginx_start()
                console.print("[bold green]✓ Nginx started[/bold green]")
            elif act == "stop":
                services.nginx_stop()
                console.print("[bold green]✓ Nginx stopped[/bold green]")
            elif act == "restart":
                services.nginx_stop()
                services.nginx_start()
                console.print("[bold green]✓ Nginx restarted[/bold green]")
        except Exception as e:
            console.print(f"[bold red]✗ Nginx error: {e}[/bold red]")

        # Process MariaDB
        try:
            if act == "start":
                pid = services.mariadb_start()
                console.print(f"[bold green]✓ MariaDB started (PID {pid})[/bold green]")
            elif act == "stop":
                services.mariadb_stop()
                console.print("[bold green]✓ MariaDB stopped[/bold green]")
            elif act == "restart":
                services.mariadb_stop()
                pid = services.mariadb_start()
                console.print(f"[bold green]✓ MariaDB restarted (PID {pid})[/bold green]")
        except Exception as e:
            console.print(f"[bold red]✗ MariaDB error: {e}[/bold red]")

        # Process phpMyAdmin
        try:
            if (paths.PMA_DIR / "index.php").exists():
                if act == "start":
                    pid = pma_core.start()
                    console.print(f"[bold green]✓ phpMyAdmin started at http://127.0.0.1:8080 (PID {pid})[/bold green]")
                elif act == "stop":
                    pma_core.stop()
                    console.print("[bold green]✓ phpMyAdmin stopped[/bold green]")
                elif act == "restart":
                    pid = pma_core.restart()
                    console.print(f"[bold green]✓ phpMyAdmin restarted at http://127.0.0.1:8080 (PID {pid})[/bold green]")
        except Exception as e:
            console.print(f"[yellow]! phpMyAdmin note: {e}[/yellow]")

        # Process selected PHP FastCGI pools
        for pv in selected_php_pools:
            try:
                cfg = paths.load_config()
                if act == "start":
                    workers = fcgi.start(pv, php.php_cgi_exe(pv), cfg["fcgi_workers_per_version"], cfg["fcgi_base_port"])
                    ports = ", ".join(str(w.port) for w in workers)
                    console.print(f"[bold green]✓ PHP {pv} FastCGI pool started ({len(workers)} workers on ports: {ports})[/bold green]")
                elif act == "stop":
                    fcgi.stop(pv)
                    console.print(f"[bold green]✓ PHP {pv} FastCGI pool stopped[/bold green]")
                elif act == "restart":
                    workers = fcgi.restart(pv)
                    ports = ", ".join(str(w.port) for w in workers)
                    console.print(f"[bold green]✓ PHP {pv} FastCGI pool restarted ({len(workers)} workers on ports: {ports})[/bold green]")
            except Exception as e:
                console.print(f"[bold red]✗ PHP {pv} FastCGI pool error: {e}[/bold red]")

        console.print("\n[bold green]All requested service operations completed.[/bold green]")




@ctl.command(name="start-nginx")
def ctl_start_nginx():
    start.callback("nginx")


@ctl.command(name="stop-nginx")
def ctl_stop_nginx():
    stop.callback("nginx")


@ctl.command(name="reload-nginx")
def ctl_reload_nginx():
    reload.callback("nginx")


@ctl.command(name="start-mariadb")
def ctl_start_mariadb():
    start.callback("mariadb")


@ctl.command(name="stop-mariadb")
def ctl_stop_mariadb():
    stop.callback("mariadb")


@ctl.command(name="status")
def ctl_status():
    status.callback(None)


# ---- FastCGI Pool Subcommands (pool) ---------------------------------------

@main.group()
def pool():
    """Manage php-cgi worker pools."""


@pool.command(name="start")
@click.argument("version")
@click.option("--workers", default=None, type=int)
def pool_start(version, workers):
    target_ver = php.resolve_installed(version)
    cfg = paths.load_config()
    n = workers or cfg["fcgi_workers_per_version"]
    state = fcgi.start(target_ver, php.php_cgi_exe(target_ver), n, cfg["fcgi_base_port"])
    ports = ", ".join(str(w.port) for w in state)
    console.print(f"[bold green]Started {len(state)} workers for PHP {target_ver} on ports: {ports}[/bold green]")


@pool.command(name="stop")
@click.argument("version")
def pool_stop(version):
    target_ver = php.resolve_installed(version)
    fcgi.stop(target_ver)
    console.print(f"[bold green]Stopped FastCGI pool for PHP {target_ver}[/bold green]")


@pool.command(name="restart")
@click.argument("version")
@click.option("--workers", default=None, type=int)
def pool_restart(version, workers):
    target_ver = php.resolve_installed(version)
    state = fcgi.restart(target_ver, workers=workers)
    ports = ", ".join(str(w.port) for w in state)
    console.print(f"[bold green]Restarted {len(state)} workers for PHP {target_ver} on ports: {ports}[/bold green]")


@pool.command(name="status")
@click.argument("version")
def pool_status(version):
    target_ver = php.resolve_installed(version)
    workers = fcgi.status(target_ver)
    if workers:
        for w in workers:
            console.print(f"PID: {w.pid:<8} Port: {w.port}")
    else:
        console.print(f"PHP {target_ver} pool is stopped.")


# ---- Virtual Host Management (vhost) ---------------------------------------

@main.command(name="vhost")
@click.option("--domain", "-d", default=None, help="Domain name (e.g. project.local)")
@click.option("--root", "-r", default=None, help="Project root directory")
@click.option("--php", "php_version", default=None, help="PHP version (e.g. 8.4)")
@click.option("--ssl/--no-ssl", default=None, help="Enable SSL/HTTPS with local mkcert certificate")
@click.option("--start-pool/--no-start-pool", default=True, help="Auto-start PHP FastCGI pool if stopped")
@click.option("--force", "-f", is_flag=True, help="Overwrite/update existing virtual host without confirmation")
def vhost_cmd(domain, root, php_version, ssl, start_pool, force):
    """Create or update an Nginx virtual host with local SSL and hosts file mapping."""
    installed_phps = php.list_installed()
    if not installed_phps:
        raise click.ClickException("No PHP versions installed. Run `ndev install <version>` first.")

    # Interactive prompts if arguments omitted
    is_interactive = not domain
    if not domain:
        domain = click.prompt("Domain name (e.g. myproject.local)")
    
    # Strip any protocol prefixes and slashes
    domain = re.sub(r"^https?://", "", domain.strip().lower()).rstrip("/")

    # Check if virtual host already exists
    existing_vhost = None
    for v in vhost_core.list_vhosts():
        if v["domain"].lower() == domain.lower():
            existing_vhost = v
            break

    is_update = bool(existing_vhost)
    if existing_vhost and not force:
        if is_interactive:
            console.print(f"\n[yellow]Virtual host '{domain}' already exists:[/yellow]")
            console.print(f"  • Root: {existing_vhost['root']}")
            console.print(f"  • PHP : {existing_vhost['php']}")
            console.print(f"  • SSL : {'Enabled' if existing_vhost['ssl'] else 'Disabled'}")
            if not click.confirm(f"Do you want to update/reconfigure '{domain}'?", default=False):
                console.print("[yellow]Aborted. Existing virtual host was not modified.[/yellow]")
                return
        else:
            raise click.ClickException(f"Virtual host '{domain}' already exists. Use --force to overwrite/update.")

    default_root = existing_vhost["root"] if existing_vhost else str(Path.home() / "Sites" / domain)
    if not root:
        root = click.prompt("Project root directory", default=default_root)

    default_php = existing_vhost["php"] if (existing_vhost and existing_vhost["php"] in installed_phps) else (php.get_current_version() or installed_phps[-1])
    if not php_version:
        console.print(f"Available PHP versions: {', '.join(installed_phps)}")
        while True:
            php_version = click.prompt("Select PHP version", default=default_php)
            if php_version in installed_phps:
                break
            console.print(f"[bold red]PHP {php_version} is not installed.[/bold red] Available: {', '.join(installed_phps)}")
    elif php_version not in installed_phps:
        raise click.ClickException(
            f"PHP {php_version} is not installed. Available versions: {', '.join(installed_phps)}"
        )

    default_ssl = existing_vhost["ssl"] if existing_vhost else False
    if ssl is None:
        ssl = click.confirm("Enable SSL/HTTPS with local certificate?", default=default_ssl)

    conf_path = vhost_core.create_vhost(
        domain=domain,
        root=root,
        php_version=php_version,
        ssl=ssl,
        auto_start_pool=start_pool,
    )

    action_label = "Updated" if is_update else "Created"
    console.print(f"\n[bold green]Virtual Host {action_label} Successfully[/bold green]")
    console.print(f"Domain : [bold cyan]{domain}[/bold cyan]")
    console.print(f"Root   : {root}")
    console.print(f"PHP    : {php_version}")
    console.print(f"Config : {conf_path}")
    if ssl:
        console.print(f"URL    : [bold green]https://{domain}[/bold green]")
    else:
        console.print(f"URL    : [bold green]http://{domain}[/bold green]")


@main.command(name="vhost-remove")
@click.option("--domain", "-d", default=None, help="Domain name to remove")
def vhost_remove_cmd(domain):
    """Remove a virtual host configuration and hosts file mapping."""
    if not domain:
        vhosts = vhost_core.list_vhosts()
        if not vhosts:
            console.print("[yellow]No virtual hosts configured.[/yellow]")
            return
        console.print("\n[bold]Select Virtual Host to Remove:[/bold]")
        for idx, v in enumerate(vhosts, 1):
            console.print(f"  {idx}) {v['domain']} (Root: {v['root']})")
        choice = click.prompt("Enter choice", default=1, type=int)
        if 1 <= choice <= len(vhosts):
            domain = vhosts[choice - 1]["domain"]
        else:
            return

    domain = re.sub(r"^https?://", "", domain.strip().lower()).rstrip("/")
    removed = vhost_core.remove_vhost(domain)
    if removed:
        console.print(f"[bold green]Removed virtual host '{domain}'.[/bold green]")
    else:
        console.print(f"[yellow]Virtual host '{domain}' does not exist.[/yellow]")


@main.command(name="vhost-list")
def vhost_list_cmd():
    """List all configured virtual hosts."""
    vhosts = vhost_core.list_vhosts()
    if not vhosts:
        console.print("[yellow]No virtual hosts configured yet. Run `ndev vhost` to create one.[/yellow]")
        return

    table = Table(title="Configured Virtual Hosts")
    table.add_column("Domain", style="bold cyan")
    table.add_column("URL", style="bold green")
    table.add_column("Root Directory")
    table.add_column("PHP", style="magenta")
    table.add_column("SSL")

    for v in vhosts:
        url = f"https://{v['domain']}" if v["ssl"] else f"http://{v['domain']}"
        ssl_tag = "[green]Enabled[/green]" if v["ssl"] else "[dim]Disabled[/dim]"
        table.add_row(v["domain"], url, v["root"], v["php"], ssl_tag)

    console.print(table)


# ---- Database Management (db) ----------------------------------------------

@main.group(invoke_without_command=True)
@click.pass_context
def db(ctx: click.Context):
    """Manage MariaDB databases and users."""
    if ctx.invoked_subcommand is not None:
        return

    # Interactive Wizard matching Linux ndev db
    console.print("\n[bold blue]========================================[/bold blue]")
    console.print("[bold blue]        ndev Database Manager Wizard     [/bold blue]")
    console.print("[bold blue]========================================[/bold blue]\n")

    console.print("Operation:")
    console.print("  1) Create Database")
    console.print("  2) Drop Database")
    console.print("  3) Export/Dump Database")
    console.print("  4) Import Database (SQL file)")
    console.print("  5) Create User")
    console.print("  6) Drop User")
    console.print("  7) List Databases")
    console.print("  8) List Users")

    op_choice = click.prompt("Choice [1-8]", default=1, type=int)
    root_pass = click.prompt("Admin password", default=db_core.DEFAULT_ROOT_PASSWORD, hide_input=True)

    # Validate database connection before proceeding with operations
    ok, err = db_core.test_connection(root_password=root_pass)
    if not ok:
        console.print(f"\n[bold red]✗ Connection Error:[/bold red] {err}")
        retry = click.confirm("Would you like to re-enter the admin password?", default=True)
        if retry:
            root_pass = click.prompt("Admin password", hide_input=True)
            ok, err = db_core.test_connection(root_password=root_pass)
            if not ok:
                console.print(f"[bold red]✗ Connection failed: {err}[/bold red]")
                return
        else:
            return

    try:
        if op_choice == 1:
            name = click.prompt("Database name")
            owner = click.prompt("User to grant privileges to (optional)", default="")
            db_core.create_db(name, owner=owner, root_password=root_pass)
            console.print(f"[bold green]✓ Database '{name}' created successfully.[/bold green]")
        elif op_choice == 2:
            name = click.prompt("Database name to drop")
            confirm = click.prompt(f"Type '{name}' to confirm deletion")
            if confirm == name:
                db_core.drop_db(name, root_password=root_pass)
                console.print(f"[bold green]✓ Database '{name}' dropped.[/bold green]")
            else:
                console.print("[yellow]Aborted.[/yellow]")
        elif op_choice == 3:
            name = click.prompt("Database name to export")
            out_path = click.prompt("Output SQL file path", default=f"{name}.sql")
            saved = db_core.export_db(name, output_path=out_path, root_password=root_pass)
            console.print(f"[bold green]✓ Database exported to: {saved}[/bold green]")
        elif op_choice == 4:
            name = click.prompt("Database name to import into")
            sql_file = click.prompt("Path to .sql file to import")
            db_core.import_db(name, sql_file, root_password=root_pass)
            console.print(f"[bold green]✓ Database '{name}' imported from {sql_file}.[/bold green]")
        elif op_choice == 5:
            user = click.prompt("Username")
            password = click.prompt("Password", hide_input=True)
            grant = click.prompt("Database to grant privileges to (optional)", default="")
            db_core.create_user(user, password, grant_db=grant or None, root_password=root_pass)
            console.print(f"[bold green]✓ User '{user}' created successfully.[/bold green]")
        elif op_choice == 6:
            user = click.prompt("Username to drop")
            confirm = click.prompt(f"Type '{user}' to confirm deletion")
            if confirm == user:
                db_core.drop_user(user, root_password=root_pass)
                console.print(f"[bold green]✓ User '{user}' dropped.[/bold green]")
            else:
                console.print("[yellow]Aborted.[/yellow]")
        elif op_choice == 7:
            dbs = db_core.list_databases(root_password=root_pass)
            console.print("\n[bold]Databases:[/bold]")
            for d in dbs:
                console.print(f"  • {d}")
        elif op_choice == 8:
            users = db_core.list_users(root_password=root_pass)
            console.print("\n[bold]Users:[/bold]")
            for u in users:
                console.print(f"  • {u}")
    except Exception as e:
        console.print(f"\n[bold red]✗ Database Error:[/bold red] {e}")


@db.command(name="create-db")
@click.argument("name")
@click.option("--owner", default="", help="User to grant privileges on this database")
@click.option("--root-password", default=db_core.DEFAULT_ROOT_PASSWORD)
def db_create_db(name, owner, root_password):
    """Create a new database."""
    try:
        db_core.create_db(name, owner=owner, root_password=root_password)
        console.print(f"[bold green]✓ Database `{name}` created.[/bold green]")
    except Exception as e:
        raise click.ClickException(str(e))


@db.command(name="create", hidden=True)
@click.argument("name")
@click.option("--owner", default="", help="User to grant privileges on this database")
@click.option("--root-password", default=db_core.DEFAULT_ROOT_PASSWORD)
def db_create_alias(name, owner, root_password):
    """Alias for create-db."""
    db_create_db.callback(name, owner, root_password)


@db.command(name="drop-db")
@click.argument("name")
@click.option("--force", "-f", is_flag=True, help="Skip confirmation prompt")
@click.option("--root-password", default=db_core.DEFAULT_ROOT_PASSWORD)
def db_drop_db(name, force, root_password):
    """Drop an existing database."""
    if not force:
        confirm = click.prompt(f"Type '{name}' to confirm dropping database")
        if confirm != name:
            console.print("[yellow]Aborted.[/yellow]")
            return
    try:
        db_core.drop_db(name, root_password)
        console.print(f"[bold green]✓ Database `{name}` dropped.[/bold green]")
    except Exception as e:
        raise click.ClickException(str(e))


@db.command(name="drop", hidden=True)
@click.argument("name")
@click.option("--force", "-f", is_flag=True)
@click.option("--root-password", default=db_core.DEFAULT_ROOT_PASSWORD)
def db_drop_alias(name, force, root_password):
    """Alias for drop-db."""
    db_drop_db.callback(name, force, root_password)


@db.command(name="export-db")
@click.argument("name")
@click.option("--output", "-o", default=None, help="Output SQL file path")
@click.option("--root-password", default=db_core.DEFAULT_ROOT_PASSWORD)
def db_export_db(name, output, root_password):
    """Export/dump a database to SQL file."""
    out = output or f"{name}.sql"
    try:
        saved = db_core.export_db(name, output_path=out, root_password=root_password)
        console.print(f"[bold green]✓ Database `{name}` exported to {saved}[/bold green]")
    except Exception as e:
        raise click.ClickException(str(e))


@db.command(name="export", hidden=True)
@click.argument("name")
@click.option("--output", "-o", default=None)
@click.option("--root-password", default=db_core.DEFAULT_ROOT_PASSWORD)
def db_export_alias(name, output, root_password):
    """Alias for export-db."""
    db_export_db.callback(name, output, root_password)


@db.command(name="dump", hidden=True)
@click.argument("name")
@click.option("--output", "-o", default=None)
@click.option("--root-password", default=db_core.DEFAULT_ROOT_PASSWORD)
def db_dump_alias(name, output, root_password):
    """Alias for export-db."""
    db_export_db.callback(name, output, root_password)


@db.command(name="import-db")
@click.argument("name")
@click.argument("sql_file", type=click.Path(exists=True))
@click.option("--root-password", default=db_core.DEFAULT_ROOT_PASSWORD)
def db_import_db(name, sql_file, root_password):
    """Import a .sql file into a database."""
    try:
        db_core.import_db(name, sql_file, root_password=root_password)
        console.print(f"[bold green]✓ Database `{name}` imported from {sql_file}[/bold green]")
    except Exception as e:
        raise click.ClickException(str(e))


@db.command(name="import", hidden=True)
@click.argument("name")
@click.argument("sql_file", type=click.Path(exists=True))
@click.option("--root-password", default=db_core.DEFAULT_ROOT_PASSWORD)
def db_import_alias(name, sql_file, root_password):
    """Alias for import-db."""
    db_import_db.callback(name, sql_file, root_password)


@db.command(name="list")
@click.option("--root-password", default=db_core.DEFAULT_ROOT_PASSWORD)
def db_list(root_password):
    """List databases."""
    try:
        for name in db_core.list_databases(root_password):
            console.print(f"  • {name}")
    except Exception as e:
        raise click.ClickException(str(e))


@db.command(name="create-user")
@click.argument("username")
@click.option("--new-password", prompt=True, hide_input=True)
@click.option("--grant-db", default=None)
@click.option("--root-password", default=db_core.DEFAULT_ROOT_PASSWORD)
def db_create_user(username, new_password, grant_db, root_password):
    """Create a database user."""
    try:
        db_core.create_user(username, new_password, grant_db, root_password=root_password)
        suffix = f" with privileges on `{grant_db}`" if grant_db else ""
        console.print(f"[bold green]✓ User '{username}' created{suffix}.[/bold green]")
    except Exception as e:
        raise click.ClickException(str(e))


@db.command(name="drop-user")
@click.argument("username")
@click.option("--force", "-f", is_flag=True)
@click.option("--root-password", default=db_core.DEFAULT_ROOT_PASSWORD)
def db_drop_user(username, force, root_password):
    """Drop a database user."""
    if not force:
        confirm = click.prompt(f"Type '{username}' to confirm dropping user")
        if confirm != username:
            console.print("[yellow]Aborted.[/yellow]")
            return
    try:
        db_core.drop_user(username, root_password=root_password)
        console.print(f"[bold green]✓ User '{username}' dropped.[/bold green]")
    except Exception as e:
        raise click.ClickException(str(e))


@db.command(name="list-users")
@click.option("--root-password", default=db_core.DEFAULT_ROOT_PASSWORD)
def db_list_users(root_password):
    """List database users."""
    try:
        for name in db_core.list_users(root_password):
            console.print(f"  • {name}")
    except Exception as e:
        raise click.ClickException(str(e))


# ---- Extension Manager (ext) -----------------------------------------------

@main.group()
def ext():
    """Manage PECL extensions (precompiled DLLs for Windows)."""


@ext.command(name="install")
@click.argument("name")
@click.argument("ext_version", required=False)
@click.argument("php_version", required=False)
@click.option("--arch", default="x64", type=click.Choice(["x64", "x86"]))
def ext_install(name, ext_version, php_version, arch):
    """Install and enable a PECL extension."""
    target_php = php_version
    target_ext_ver = ext_version

    # If only 2 args passed (e.g. `ndev ext install redis 8.4`)
    if ext_version and not php_version:
        installed = php.list_installed()
        if ext_version in installed or any(v.startswith(ext_version) for v in installed):
            target_php = ext_version
            target_ext_ver = None

    if not target_php:
        target_php = php.get_current_version()
        if not target_php:
            installed = php.list_installed()
            if installed:
                target_php = installed[-1]
            else:
                raise click.ClickException("No PHP version active. Specify PHP version as argument.")

    with console.status(f"[bold green]Finding and installing extension '{name}' for PHP {target_php}...[/bold green]"):
        ext_dir = ext_core.install(name, target_ext_ver, target_php, arch=arch)

    console.print(f"[bold green]Installed and enabled {name} for PHP {target_php}[/bold green] -> {ext_dir}")


@ext.command(name="enable")
@click.argument("name")
@click.argument("php_version", required=False)
def ext_enable(name, php_version):
    """Enable an extension in php.ini."""
    v = php_version or php.get_current_version()
    if not v:
        raise click.ClickException("No active PHP version. Pass PHP version explicitly.")
    target_v = php.resolve_installed(v)
    ext_core.enable(name, target_v)
    console.print(f"[bold green]Enabled {name} for PHP {target_v}[/bold green]")


@ext.command(name="disable")
@click.argument("name")
@click.argument("php_version", required=False)
def ext_disable(name, php_version):
    """Disable an extension in php.ini."""
    v = php_version or php.get_current_version()
    if not v:
        raise click.ClickException("No active PHP version. Pass PHP version explicitly.")
    target_v = php.resolve_installed(v)
    ext_core.disable(name, target_v)
    console.print(f"[bold green]Disabled {name} for PHP {target_v}[/bold green]")


@ext.command(name="uninstall")
@click.argument("name")
@click.argument("php_version", required=False)
def ext_uninstall(name, php_version):
    """Disable and remove an extension DLL."""
    v = php_version or php.get_current_version()
    if not v:
        raise click.ClickException("No active PHP version. Pass PHP version explicitly.")
    target_v = php.resolve_installed(v)
    ext_core.uninstall(name, target_v)
    console.print(f"[bold green]Uninstalled {name} for PHP {target_v}[/bold green]")


@ext.command(name="list")
@click.argument("php_version", required=False)
def ext_list(php_version):
    """List loaded and configured extensions for a PHP version."""
    v = php_version or php.get_current_version()
    if not v:
        raise click.ClickException("No active PHP version. Pass PHP version explicitly.")
    target_v = php.resolve_installed(v)

    table = Table(title=f"PHP {target_v} Extensions")
    table.add_column("Extension", style="bold cyan")
    table.add_column("Status")

    for name, enabled in ext_core.list_status(target_v).items():
        st = "[bold green]enabled[/bold green]" if enabled else "[dim]disabled[/dim]"
        table.add_row(name, st)

    console.print(table)


@ext.command(name="available")
@click.argument("name")
def ext_available(name):
    """List available versions for an extension on PECL."""
    versions = ext_core.list_ext_versions(name)
    console.print(f"[bold]Available versions for {name} on PECL ({len(versions)} total):[/bold]")
    for v in versions[-20:]:
        console.print(f"  {v}")


# ---- phpMyAdmin Service (pma) ----------------------------------------------

@main.group()
def pma():
    """Manage phpMyAdmin background service."""


@pma.command(name="install")
@click.option("--version", default=pma_core.DEFAULT_VERSION)
def pma_install(version):
    with console.status(f"[bold green]Installing phpMyAdmin {version}...[/bold green]"):
        path = pma_core.install(version)
    console.print(f"[bold green]Installed phpMyAdmin {version}[/bold green] -> {path}")


@pma.command(name="start")
@click.option("--php", "php_version", default=None)
@click.option("--port", default=pma_core.DEFAULT_PORT)
def pma_start(php_version, port):
    pid = pma_core.start(php_version, port)
    console.print(f"[bold green]phpMyAdmin running at http://127.0.0.1:{port} (PID {pid})[/bold green]")


@pma.command(name="stop")
def pma_stop():
    pma_core.stop()
    console.print("[bold green]phpMyAdmin stopped.[/bold green]")


@pma.command(name="restart")
@click.option("--php", "php_version", default=None)
@click.option("--port", default=pma_core.DEFAULT_PORT)
def pma_restart(php_version, port):
    pid = pma_core.restart(php_version, port)
    console.print(f"[bold green]phpMyAdmin restarted at http://127.0.0.1:{port} (PID {pid})[/bold green]")


@pma.command(name="status")
def pma_status():
    st = pma_core.status()
    if st:
        console.print(f"[bold green]Running:[/bold green] {st['url']} (PID {st['pid']})")
    else:
        console.print("[bold red]Stopped.[/bold red]")


# ---- Mailpit - local email sandbox (mailpit) --------------------------------

@main.group()
def mailpit():
    """Manage Mailpit - local email sandbox & SMTP catcher.

    \b
    Mailpit catches every e-mail your app sends locally so you can
    inspect it without ever hitting a real inbox.

    \b
    After starting:
      SMTP server  ->  127.0.0.1:1025  (point your app here)
      Web UI       ->  http://127.0.0.1:8025  (browse caught mail)
    """


@mailpit.command(name="install")
def mailpit_install():
    """Download the prebuilt Mailpit binary from GitHub releases."""
    with console.status("[bold green]Fetching latest Mailpit release...[/bold green]"):
        try:
            path = mailpit_core.install()
        except Exception as e:
            raise click.ClickException(str(e))
    console.print(f"[bold green]Mailpit installed[/bold green] -> {path}")


@mailpit.command(name="start")
@click.option("--smtp-port", default=mailpit_core.DEFAULT_SMTP_PORT, show_default=True,
              help="SMTP listening port")
@click.option("--web-port", default=mailpit_core.DEFAULT_WEB_PORT, show_default=True,
              help="Web UI listening port")
def mailpit_start(smtp_port, web_port):
    """Start Mailpit email sandbox in the background."""
    if not mailpit_core.is_installed():
        console.print("[yellow]Mailpit not installed - downloading now...[/yellow]")
        with console.status("[bold green]Downloading Mailpit...[/bold green]"):
            try:
                mailpit_core.install()
            except Exception as e:
                raise click.ClickException(str(e))

    st = mailpit_core.status()
    if st:
        console.print(
            f"[yellow]Mailpit is already running at {st['url']} "
            f"(SMTP {st['smtp']}, PID {st['pid']})[/yellow]"
        )
        return
    try:
        pid = mailpit_core.start(smtp_port=smtp_port, web_port=web_port)
    except Exception as e:
        raise click.ClickException(str(e))

    console.print(f"[bold green]Mailpit started (PID {pid})[/bold green]")
    console.print(f"  Web UI  -> [bold cyan]http://127.0.0.1:{web_port}[/bold cyan]")
    console.print(f"  SMTP    -> [bold cyan]127.0.0.1:{smtp_port}[/bold cyan]")


@mailpit.command(name="stop")
def mailpit_stop():
    """Stop the running Mailpit process."""
    st = mailpit_core.status()
    if not st:
        console.print("[yellow]Mailpit is not running.[/yellow]")
        return
    try:
        mailpit_core.stop()
    except Exception as e:
        raise click.ClickException(str(e))
    console.print("[bold green]Mailpit stopped.[/bold green]")


@mailpit.command(name="restart")
@click.option("--smtp-port", default=mailpit_core.DEFAULT_SMTP_PORT, show_default=True)
@click.option("--web-port", default=mailpit_core.DEFAULT_WEB_PORT, show_default=True)
def mailpit_restart(smtp_port, web_port):
    """Restart Mailpit."""
    if not mailpit_core.is_installed():
        raise click.ClickException("Mailpit is not installed. Run `ndev mailpit install` first.")
    try:
        pid = mailpit_core.restart(smtp_port=smtp_port, web_port=web_port)
    except Exception as e:
        raise click.ClickException(str(e))
    console.print(f"[bold green]Mailpit restarted (PID {pid})[/bold green]")
    console.print(f"  Web UI  -> [bold cyan]http://127.0.0.1:{web_port}[/bold cyan]")
    console.print(f"  SMTP    -> [bold cyan]127.0.0.1:{smtp_port}[/bold cyan]")


@mailpit.command(name="status")
def mailpit_status():
    """Show Mailpit status."""
    st = mailpit_core.status()
    if st:
        console.print(f"[bold green]Running[/bold green]  Web UI -> {st['url']}  |  SMTP -> {st['smtp']}  |  PID {st['pid']}")
    else:
        console.print("[bold red]Stopped.[/bold red]")
        if not mailpit_core.is_installed():
            console.print("[yellow]  (not installed - run `ndev mailpit install`)[/yellow]")


@mailpit.command(name="launch")
@click.option("--smtp-port", default=mailpit_core.DEFAULT_SMTP_PORT, show_default=True,
              help="SMTP listening port")
@click.option("--web-port", default=mailpit_core.DEFAULT_WEB_PORT, show_default=True,
              help="Web UI listening port")
def mailpit_launch(smtp_port, web_port):
    """Open Mailpit web UI in your default browser (starts service if stopped)."""
    import webbrowser
    st = mailpit_core.status()
    if not st:
        if not mailpit_core.is_installed():
            console.print("[yellow]Mailpit not installed - downloading now...[/yellow]")
            with console.status("[bold green]Downloading Mailpit...[/bold green]"):
                try:
                    mailpit_core.install()
                except Exception as e:
                    raise click.ClickException(str(e))
        try:
            pid = mailpit_core.start(smtp_port=smtp_port, web_port=web_port)
            console.print(f"[bold green]✓ Mailpit started (PID {pid})[/bold green]")
        except Exception as e:
            raise click.ClickException(str(e))
        st = mailpit_core.status()

    url = st["url"] if st else f"http://127.0.0.1:{web_port}"
    console.print(f"Opening [bold cyan]{url}[/bold cyan] in browser...")
    webbrowser.open(url)


@mailpit.command(name="open", hidden=True)
@click.option("--smtp-port", default=mailpit_core.DEFAULT_SMTP_PORT)
@click.option("--web-port", default=mailpit_core.DEFAULT_WEB_PORT)
def mailpit_open_alias(smtp_port, web_port):
    """Alias for launch."""
    mailpit_launch.callback(smtp_port, web_port)


# ---- ngrok Tunneling (grok / tunnel / share) --------------------------------

@main.command(name="grok")
@click.option("--domain", default=None, help="Vhost domain to tunnel. Omit to select interactively.")
@click.option("--ssl", is_flag=True, help="Tunnel HTTPS port 443")
def grok(domain, ssl):
    """Tunnel a local virtual host to the public web via ngrok."""
    if not domain:
        vhosts = grok_core.list_vhosts()
        if not vhosts:
            console.print("[yellow]No virtual hosts configured yet -- run `ndev vhost` first.[/yellow]")
            return
        console.print("\n[bold]Available Virtual Hosts[/bold]")
        console.print("----------------------")
        for i, v in enumerate(vhosts, 1):
            console.print(f" {i}) {v}")
        console.print("")
        choice = click.prompt("Select vhost index", default=1, type=int)
        if 1 <= choice <= len(vhosts):
            domain = vhosts[choice - 1]
        else:
            raise click.ClickException("Invalid selection.")

    domain = re.sub(r"^https?://", "", domain.strip().lower()).rstrip("/")
    console.print(f"Starting ngrok tunnel for [bold cyan]{domain}[/bold cyan]{' (HTTPS)' if ssl else ''} -- Ctrl+C to stop.")
    proc = grok_core.start_tunnel(domain, ssl=ssl)
    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()


@main.command(name="tunnel", hidden=True)
@click.option("--domain", default=None)
@click.option("--ssl", is_flag=True)
def tunnel_alias(domain, ssl):
    """Alias for grok."""
    grok.callback(domain, ssl)


@main.command(name="share", hidden=True)
@click.option("--domain", default=None)
@click.option("--ssl", is_flag=True)
def share_alias(domain, ssl):
    """Alias for grok."""
    grok.callback(domain, ssl)


# ---- Interactive Shell (shell) ---------------------------------------------

@main.command()
def shell():
    """Open an interactive shell configured with active PHP, Composer, and ndev tools on PATH."""
    import subprocess
    paths.ensure_dirs()
    env = os.environ.copy()
    env["NDEV_HOME"] = str(paths.NDEV_HOME)

    # Prepend shims and active PHP/MariaDB to PATH
    shim_path = str(paths.SHIM_DIR)
    curr_v = php.get_current_version()
    extra_paths = [shim_path]
    if curr_v:
        extra_paths.append(str(paths.version_dir(curr_v)))
    if (paths.MARIADB_DIR / "bin").exists():
        extra_paths.append(str(paths.MARIADB_DIR / "bin"))
    if paths.NGINX_DIR.exists():
        extra_paths.append(str(paths.NGINX_DIR))

    curr_path = env.get("PATH", "")
    env["PATH"] = ";".join(extra_paths) + ";" + curr_path

    console.print(f"\n[bold blue]Entering ndev interactive shell (Active PHP: {curr_v or 'none'})...[/bold blue]")
    console.print("[dim]Type 'exit' to return to normal shell.[/dim]\n")

    ps_prompt_script = f"function prompt {{ '`n(ndev: PHP {curr_v or 'none'}) ' + (Get-Location) + '> ' }}; Write-Host 'ndev developer environment active.' -ForegroundColor Green"
    try:
        subprocess.run(["powershell.exe", "-NoLogo", "-NoExit", "-Command", ps_prompt_script], env=env)
    except Exception:
        subprocess.run(["cmd.exe"], env=env)


# ---- System Setup (setup) --------------------------------------------------

@main.command()
@click.option("--nginx/--no-nginx", default=True, help="Install Nginx")
@click.option("--mariadb/--no-mariadb", default=True, help="Install MariaDB")
@click.option("--mkcert/--no-mkcert", default=True, help="Install mkcert for local SSL")
@click.option("--ngrok/--no-ngrok", default=True, help="Install ngrok")
@click.option("--composer/--no-composer", default=True, help="Install Composer")
@click.option("--cacert/--no-cacert", default=True, help="Download Mozilla root CA bundle")
@click.option("--nginx-version", default=None)
@click.option("--mariadb-version", default=None)
@click.option("--mkcert-version", default=None)
def setup(nginx, mariadb, mkcert, ngrok, composer, cacert, nginx_version, mariadb_version, mkcert_version):
    """Download and setup Nginx, MariaDB, mkcert, ngrok, Composer, and CA certificates."""
    versions = {}
    if nginx_version:
        versions["nginx"] = nginx_version
    if mariadb_version:
        versions["mariadb"] = mariadb_version
    if mkcert_version:
        versions["mkcert"] = mkcert_version

    console.print("\n[bold blue]==================================================================[/bold blue]")
    console.print("[bold blue]                ndev System Environment Setup                     [/bold blue]")
    console.print("[bold blue]==================================================================[/bold blue]\n")

    with console.status("[bold green]Downloading and configuring components...[/bold green]"):
        results = setup_core.run_setup(
            nginx=nginx,
            mariadb=mariadb,
            mkcert=mkcert,
            ngrok=ngrok,
            composer=composer,
            cacert=cacert,
            versions=versions,
        )

    for name, path in results.items():
        console.print(f"[bold green]✓[/bold green] Installed {name:<10} -> {path}")

    shim_on_path = str(paths.SHIM_DIR).lower() in os.environ.get("PATH", "").lower()
    if not shim_on_path:
        console.print(f"\n[bold yellow]Important:[/bold yellow] Add [bold cyan]{paths.SHIM_DIR}[/bold cyan] to your system PATH.")


# ---- Component Upgrade (upgrade) --------------------------------------------

@main.command()
@click.argument("component", required=False, default=None)
@click.option("--check", is_flag=True, default=False, help="Only check for updates without applying upgrades.")
def upgrade(component: Optional[str], check: bool):
    """Check for and upgrade stack components (Nginx, Mailpit, MariaDB, PMA, mkcert, Composer)."""
    console.print("\n[bold blue]ndev Stack Component Updates & Upgrades[/bold blue]")

    with console.status("[bold green]Checking component versions...[/bold green]"):
        all_components = upgrade_core.check_all()
        if component and component.lower() != "all":
            # Filter matching component
            infos = [info for info in all_components if info.name == component.lower() or component.lower() in info.name]
            if not infos:
                raise click.ClickException(f"Unknown component '{component}'. Available: {', '.join(upgrade_core.COMPONENTS)}")
        else:
            infos = all_components

    table = Table(title="Stack Components Version Status", show_header=True, header_style="bold cyan")
    table.add_column("Component", style="bold", min_width=20)
    table.add_column("Installed Version", min_width=18)
    table.add_column("Latest Version", min_width=18)
    table.add_column("Status", min_width=22)

    upgradable = []
    for info in infos:
        curr_str = info.current_version or "[dim]Not installed[/dim]"
        latest_str = info.latest_version or "[dim]Unknown[/dim]"
        if not info.installed:
            st_str = "[yellow]Not Installed[/yellow]"
        elif info.update_available:
            st_str = "[bold green]Update Available[/bold green]"
            upgradable.append(info)
        else:
            st_str = "[green]Up-to-date[/green]"

        table.add_row(info.display_name, curr_str, latest_str, st_str)

    console.print(table)

    if check:
        if upgradable:
            console.print(f"\n[bold green]{len(upgradable)} component(s) can be upgraded.[/bold green] Run `ndev upgrade` to apply.")
        else:
            console.print("\n[bold green]All installed components are up-to-date![/bold green]")
        return

    if not upgradable and not component:
        console.print("\n[bold green]All installed components are up-to-date![/bold green]")
        return

    targets = [c.name for c in upgradable] if not component or component.lower() == "all" else [component.lower()]
    console.print(f"\n[bold blue]Upgrading {len(targets)} component(s): {', '.join(targets)}...[/bold blue]\n")

    for target in targets:
        with console.status(f"[bold green]Upgrading {target}...[/bold green]"):
            ok, msg = upgrade_core.upgrade_component(target)
        if ok:
            console.print(f"[bold green]✓ {msg}[/bold green]")
        else:
            console.print(f"[bold red]✗ {msg}[/bold red]")

    console.print("\n[bold green]Upgrade process complete![/bold green]")


if __name__ == "__main__":
    sys.exit(main())
