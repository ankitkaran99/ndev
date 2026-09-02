"""
Textual TUI dashboard for ndev (Linux PHP-FPM/Nginx/MariaDB stack manager).
"""
from __future__ import annotations

import asyncio
import datetime
import os
import re
import shutil
import subprocess
import webbrowser
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Label,
    RichLog,
    Select,
    Static,
    TabbedContent,
    TabPane,
)

from ndev.constants import NDEV_DIR, PHP_DIR, CURRENT_LINK, RUN_DIR, LOGS_DIR
from ndev.runtime.fpm import get_fpm_status, start_fpm, stop_fpm, restart_fpm
from ndev.runtime.pma import get_pma_status, start_pma, stop_pma, restart_pma
from ndev.runtime.mailpit import get_mailpit_status, start_mailpit, stop_mailpit, restart_mailpit, is_installed as is_mailpit_installed


# ── CSS STYLESHEET ────────────────────────────────────────────────────────────

TUI_CSS = """
Screen {
    background: $surface;
    color: $text;
}

#app-grid {
    layout: horizontal;
    height: 1fr;
    width: 1fr;
}

#sidebar {
    width: 36;
    min-width: 32;
    max-width: 42;
    background: $panel;
    border-right: vkey $primary-background;
    padding: 1;
}

.sidebar-section {
    margin-bottom: 1;
    background: $surface;
    border: round $primary-background;
    padding: 1;
}

.section-title {
    text-style: bold;
    color: $accent;
    margin-bottom: 1;
    text-align: center;
}

.sidebar-btn {
    width: 1fr;
    margin-bottom: 1;
}

.sidebar-btn-row {
    layout: horizontal;
    height: auto;
    margin-bottom: 1;
}

.sidebar-btn-row Button {
    width: 1fr;
    margin-right: 1;
}

.sidebar-btn-row Button:last-of-type {
    margin-right: 0;
}

#main-content {
    width: 1fr;
    height: 1fr;
    padding: 1;
}

TabbedContent {
    height: 1fr;
}

TabPane {
    padding: 1;
    height: 1fr;
}

DataTable {
    height: 1fr;
    border: round $primary;
}

.tab-action-bar {
    layout: horizontal;
    height: auto;
    margin-top: 1;
    align: right middle;
}

.tab-action-bar Button {
    margin-left: 1;
}

#console-log {
    height: 1fr;
    border: round $accent;
    background: $background;
    color: $text;
    padding: 1;
}

#status-summary-box {
    color: $text-muted;
    margin-top: 1;
    padding: 1;
    border: dashed $primary-background;
}
"""


# ── MAIN APPLICATION ──────────────────────────────────────────────────────────

class NdevDashboard(App):
    """Modern asynchronous TUI dashboard for Linux ndev."""

    TITLE = "ndev"
    SUB_TITLE = "Linux Web Stack Dashboard"
    CSS = TUI_CSS

    BINDINGS = [
        Binding("q", "quit", "Quit", priority=True),
        Binding("r", "refresh_all", "Refresh", priority=True),
        Binding("s", "start_all", "Start All"),
        Binding("x", "stop_all", "Stop All"),
        Binding("t", "restart_all", "Restart All"),
        Binding("l", "reload_nginx", "Reload Nginx"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._is_refreshing = False
        self._updating_selects = False
        self._available_logs: Dict[str, Path] = {}
        self._selected_service_key: Optional[str] = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        with Horizontal(id="app-grid"):
            # ── SIDEBAR ──
            with VerticalScroll(id="sidebar"):
                with Vertical(classes="sidebar-section"):
                    yield Label("⚡ Quick Actions", classes="section-title")
                    with Horizontal(classes="sidebar-btn-row"):
                        yield Button("Start All", id="btn-start-all", variant="success")
                        yield Button("Stop All", id="btn-stop-all", variant="error")
                    with Horizontal(classes="sidebar-btn-row"):
                        yield Button("Restart All", id="btn-restart-all", variant="warning")
                        yield Button("Reload Nginx", id="btn-reload-nginx", variant="primary")

                with Vertical(classes="sidebar-section"):
                    yield Label("🐘 Active PHP CLI", classes="section-title")
                    yield Select([], id="select-php-version", prompt="Select PHP Version")

                with Vertical(classes="sidebar-section"):
                    yield Label("📜 Service Logs", classes="section-title")
                    yield Select([], id="select-log-file", prompt="Select Log File")
                    yield Button("Tail Selected Log", id="btn-tail-log", variant="default", classes="sidebar-btn")

                with Vertical(id="status-summary-box"):
                    yield Label("[bold]🌐 Ports Reference[/bold]")
                    yield Label("• Nginx: 80 / 443 (SSL)")
                    yield Label("• MariaDB: 3306")
                    yield Label("• phpMyAdmin: 8080")
                    yield Label("• Mailpit Web: 8025")
                    yield Label("• Mailpit SMTP: 1025")

            # ── MAIN CONTENT (TABS) ──
            with Container(id="main-content"):
                with TabbedContent(initial="tab-services"):
                    with TabPane("⚡ Services & Pools", id="tab-services"):
                        yield DataTable(id="table-services", cursor_type="row", zebra_stripes=True)
                        with Horizontal(classes="tab-action-bar"):
                            yield Button("Start Selected", id="btn-svc-start", variant="success")
                            yield Button("Stop Selected", id="btn-svc-stop", variant="error")
                            yield Button("Restart Selected", id="btn-svc-restart", variant="warning")
                            yield Button("Open Web UI", id="btn-svc-open", variant="primary")

                    with TabPane("🌐 Virtual Hosts", id="tab-vhosts"):
                        yield DataTable(id="table-vhosts", cursor_type="row", zebra_stripes=True)
                        with Horizontal(classes="tab-action-bar"):
                            yield Button("Open in Browser", id="btn-vhost-open", variant="primary")

                    with TabPane("🐘 PHP Runtimes", id="tab-php"):
                        yield DataTable(id="table-php", cursor_type="row", zebra_stripes=True)
                        with Horizontal(classes="tab-action-bar"):
                            yield Button("Set as Active CLI", id="btn-php-set-active", variant="primary")

                    with TabPane("📋 Live Console / Logs", id="tab-logs"):
                        yield RichLog(id="console-log", highlight=True, markup=True)
                        with Horizontal(classes="tab-action-bar"):
                            yield Button("Clear Console", id="btn-clear-console", variant="default")

        yield Footer()

    # ── LIFECYCLE HOOKS ───────────────────────────────────────────────────────

    async def on_mount(self) -> None:
        """Initialize data tables, populate dropdowns, and start background polling."""
        self._init_tables()
        self.log_message("[bold green]ndev Linux TUI dashboard loaded.[/bold green]")

        # Initial data load
        self._refresh_all_data(full_rebuild=True)

        # Polling timer every 3.5 seconds
        self.set_interval(3.5, self._on_poll_timer)

    def _init_tables(self) -> None:
        """Configure columns for all DataTables."""
        svc_table = self.query_one("#table-services", DataTable)
        svc_table.add_columns("Status", "Service", "Type", "PID", "Socket / Port / Details")

        vhost_table = self.query_one("#table-vhosts", DataTable)
        vhost_table.add_columns("Domain", "URL", "PHP Target", "SSL", "Document Root")

        php_table = self.query_one("#table-php", DataTable)
        php_table.add_columns("Version", "CLI Active", "FPM Status", "Socket Path", "Installation Directory")

    def _on_poll_timer(self) -> None:
        """Periodic background status update."""
        if not self._is_refreshing:
            self._refresh_all_data(full_rebuild=False)

    def log_message(self, message: str) -> None:
        """Append formatted timestamped text to the RichLog console widget."""
        now = datetime.datetime.now().strftime("%H:%M:%S")
        try:
            log_widget = self.query_one("#console-log", RichLog)
            log_widget.write(f"[dim]{now}[/dim] {message}")
        except Exception:
            pass

    # ── ASYNC DATA FETCHERS ───────────────────────────────────────────────────

    async def _fetch_services_data(self) -> List[Dict[str, Any]]:
        """Collect states for system services and ndev runtimes."""
        def _get() -> List[Dict[str, Any]]:
            results = []

            # 1. Nginx
            ng_installed = bool(shutil.which("nginx"))
            ng_running = False
            if ng_installed:
                if shutil.which("systemctl"):
                    res = subprocess.run(["systemctl", "is-active", "--quiet", "nginx"])
                    ng_running = (res.returncode == 0)
                else:
                    ng_running = Path("/var/run/nginx.pid").exists()

            results.append({
                "key": "nginx",
                "name": "Nginx",
                "type": "Web Server",
                "installed": ng_installed,
                "running": ng_running,
                "pid": "Active" if ng_running else "-",
                "details": "Ports: 80, 443 | Config: /etc/nginx/",
                "url": "http://127.0.0.1",
            })

            # 2. MariaDB / MySQL
            db_installed = bool(shutil.which("mariadb") or shutil.which("mysql"))
            db_running = False
            if db_installed:
                if shutil.which("systemctl"):
                    res = subprocess.run(["systemctl", "is-active", "--quiet", "mariadb"])
                    if res.returncode != 0:
                        res = subprocess.run(["systemctl", "is-active", "--quiet", "mysql"])
                    db_running = (res.returncode == 0)

            results.append({
                "key": "mariadb",
                "name": "MariaDB / MySQL",
                "type": "Database",
                "installed": db_installed,
                "running": db_running,
                "pid": "Active" if db_running else "-",
                "details": "Port: 3306 (user: root)",
                "url": None,
            })

            # 3. phpMyAdmin
            pma_st = get_pma_status()
            pma_url = pma_st.get("url") or f"http://127.0.0.1:{pma_st.get('port', 8080)}"
            results.append({
                "key": "pma",
                "name": "phpMyAdmin",
                "type": "Admin Tool",
                "installed": pma_st.get("installed", False),
                "running": pma_st.get("running", False),
                "pid": str(pma_st.get("pid") or "-"),
                "details": f"{pma_url}" if pma_st.get("running") else "Port: 8080",
                "url": pma_url if pma_st.get("running") else None,
            })

            # 4. Mailpit
            mp_st = get_mailpit_status()
            mp_url = mp_st.get("url") or f"http://127.0.0.1:{mp_st.get('web_port', 8025)}"
            results.append({
                "key": "mailpit",
                "name": "Mailpit",
                "type": "Email Sandbox",
                "installed": mp_st.get("installed", False),
                "running": mp_st.get("running", False),
                "pid": str(mp_st.get("pid") or "-"),
                "details": f"Web: {mp_url} | SMTP: 127.0.0.1:{mp_st.get('smtp_port', 1025)}" if mp_st.get("running") else "Web: 8025 | SMTP: 1025",
                "url": mp_url if mp_st.get("running") else None,
            })

            # 5. PHP-FPM Pools
            installed_phps = []
            if PHP_DIR.exists():
                for d in PHP_DIR.iterdir():
                    if d.is_dir():
                        installed_phps.append(d.name)
            installed_phps.sort()

            curr_php = CURRENT_LINK.resolve().name if (CURRENT_LINK.exists() or CURRENT_LINK.is_symlink()) else None

            for v in installed_phps:
                fpm_st = get_fpm_status(v)
                is_running = fpm_st.get("running", False)
                is_active = (v == curr_php)
                cli_tag = " [active CLI]" if is_active else ""
                sock_str = str(fpm_st.get("socket", "-"))
                results.append({
                    "key": f"php:{v}",
                    "name": f"PHP-FPM {v}{cli_tag}",
                    "type": "PHP Daemon",
                    "installed": True,
                    "running": is_running,
                    "pid": str(fpm_st.get("pid") or "-"),
                    "details": f"Socket: {sock_str}",
                    "url": None,
                })

            return results

        return await asyncio.to_thread(_get)

    async def _fetch_vhosts_data(self) -> List[Dict[str, Any]]:
        """Parse Nginx virtual hosts configurations."""
        def _get() -> List[Dict[str, Any]]:
            vhosts = []
            search_dirs = [
                Path("/etc/nginx/sites-available"),
                NDEV_DIR / "vhosts",
            ]
            for sdir in search_dirs:
                if not sdir.exists():
                    continue
                for conf in sdir.glob("*.conf"):
                    try:
                        content = conf.read_text(errors="ignore")
                        # server_name
                        sn_match = re.search(r"server_name\s+([^;]+);", content)
                        domain = sn_match.group(1).split()[0] if sn_match else conf.stem

                        # root
                        root_match = re.search(r"root\s+([^;]+);", content)
                        docroot = root_match.group(1) if root_match else "-"

                        # fastcgi_pass
                        fcgi_match = re.search(r"fastcgi_pass\s+([^;]+);", content)
                        php_target = fcgi_match.group(1) if fcgi_match else "Default"

                        # ssl
                        has_ssl = "ssl_certificate" in content or "listen 443" in content or "listen [::]:443" in content

                        vhosts.append({
                            "domain": domain,
                            "root": docroot,
                            "php": php_target,
                            "ssl": has_ssl,
                            "conf": str(conf),
                        })
                    except Exception:
                        pass
            return vhosts

        return await asyncio.to_thread(_get)

    async def _fetch_php_data(self) -> Tuple[List[str], Optional[str]]:
        def _get() -> Tuple[List[str], Optional[str]]:
            installed = []
            if PHP_DIR.exists():
                for d in PHP_DIR.iterdir():
                    if d.is_dir():
                        installed.append(d.name)
            installed.sort()
            curr = CURRENT_LINK.resolve().name if (CURRENT_LINK.exists() or CURRENT_LINK.is_symlink()) else None
            return installed, curr
        return await asyncio.to_thread(_get)

    async def _fetch_logs_dict(self) -> Dict[str, Path]:
        def _get() -> Dict[str, Path]:
            logs_map = {}
            # Nginx logs
            for p in Path("/var/log/nginx").glob("*.log"):
                logs_map[f"nginx:{p.stem}"] = p
            # ndev logs
            if LOGS_DIR.exists():
                for p in LOGS_DIR.glob("*.log"):
                    logs_map[f"ndev:{p.stem}"] = p
            # PHP logs
            if PHP_DIR.exists():
                for v in PHP_DIR.iterdir():
                    if v.is_dir():
                        for cand in [v / "var" / "log" / "php-fpm.log", v / "php_error.log", v / "error.log"]:
                            if cand.exists():
                                logs_map[f"php:{v.name}"] = cand
            return logs_map
        return await asyncio.to_thread(_get)

    # ── DATA TABLE & DROPDOWN POPULATION ──────────────────────────────────────

    @work
    async def _refresh_all_data(self, full_rebuild: bool = False) -> None:
        """Main non-blocking data synchronization routine with selection preservation."""
        if self._is_refreshing:
            return
        self._is_refreshing = True
        try:
            services_data, vhosts_data, (installed_phps, curr_php), logs_dict = await asyncio.gather(
                self._fetch_services_data(),
                self._fetch_vhosts_data(),
                self._fetch_php_data(),
                self._fetch_logs_dict(),
            )

            # 1. Update Services Table (Preserving Cursor)
            svc_table = self.query_one("#table-services", DataTable)
            saved_svc_row = svc_table.cursor_row
            svc_table.clear()
            for svc in services_data:
                if not svc["installed"]:
                    status_text = Text("NOT INSTALLED", style="bold yellow")
                elif svc["running"]:
                    status_text = Text("RUNNING", style="bold green")
                else:
                    status_text = Text("STOPPED", style="bold red")

                svc_table.add_row(
                    status_text,
                    svc["name"],
                    svc["type"],
                    str(svc["pid"]),
                    svc["details"],
                    key=svc["key"],
                )
            if saved_svc_row is not None and saved_svc_row < svc_table.row_count:
                svc_table.move_cursor(row=saved_svc_row)

            # 2. Update Virtual Hosts Table (Preserving Cursor)
            vhost_table = self.query_one("#table-vhosts", DataTable)
            saved_vh_row = vhost_table.cursor_row
            vhost_table.clear()
            for vh in vhosts_data:
                proto = "https" if vh.get("ssl") else "http"
                url = f"{proto}://{vh['domain']}"
                ssl_badge = Text("SSL Enabled", style="bold green") if vh.get("ssl") else Text("Plain HTTP", style="dim")
                vhost_table.add_row(
                    vh["domain"],
                    url,
                    str(vh.get("php", "-")),
                    ssl_badge,
                    str(vh.get("root", "-")),
                    key=vh["domain"],
                )
            if saved_vh_row is not None and saved_vh_row < vhost_table.row_count:
                vhost_table.move_cursor(row=saved_vh_row)

            # 3. Update PHP Table (Preserving Cursor)
            php_table = self.query_one("#table-php", DataTable)
            saved_php_row = php_table.cursor_row
            php_table.clear()
            for v in installed_phps:
                is_active = (v == curr_php)
                cli_badge = Text("ACTIVE", style="bold green") if is_active else Text("Inactive", style="dim")
                fpm_st = get_fpm_status(v)
                fpm_badge = Text("RUNNING", style="bold green") if fpm_st.get("running") else Text("STOPPED", style="bold red")
                php_table.add_row(
                    v,
                    cli_badge,
                    fpm_badge,
                    str(fpm_st.get("socket", "-")),
                    str(PHP_DIR / v),
                    key=v,
                )
            if saved_php_row is not None and saved_php_row < php_table.row_count:
                php_table.move_cursor(row=saved_php_row)

            # 4. Update Dropdowns if full rebuild requested
            if full_rebuild:
                self._updating_selects = True
                try:
                    # PHP Version Selector
                    php_select = self.query_one("#select-php-version", Select)
                    php_options = [(f"PHP {v}" + (" (Active)" if v == curr_php else ""), v) for v in installed_phps]
                    php_select.set_options(php_options)
                    if curr_php and curr_php in installed_phps:
                        php_select.value = curr_php

                    # Log Selector
                    self._available_logs = logs_dict
                    log_select = self.query_one("#select-log-file", Select)
                    log_options = [(name, name) for name in sorted(logs_dict.keys())]
                    log_select.set_options(log_options)
                finally:
                    self._updating_selects = False

        except Exception as e:
            self.log_message(f"[bold red]Error updating dashboard: {e}[/bold red]")
        finally:
            self._is_refreshing = False

    # ── ACTION WORKERS ────────────────────────────────────────────────────────

    @work(exclusive=True)
    async def action_start_all(self) -> None:
        """Start all services and FastCGI pools."""
        self.log_message("[bold blue]Starting all services...[/bold blue]")
        self.notify("Starting all web services...", severity="information")

        def _do() -> None:
            # 1. Nginx
            if shutil.which("systemctl"):
                subprocess.run(["sudo", "systemctl", "start", "nginx"])
            # 2. MariaDB
            if shutil.which("systemctl"):
                subprocess.run(["sudo", "systemctl", "start", "mariadb"])
            # 3. phpMyAdmin
            try:
                start_pma()
            except Exception as e:
                self.log_message(f"[yellow]phpMyAdmin notice: {e}[/yellow]")
            # 4. Mailpit
            try:
                if is_mailpit_installed() and not get_mailpit_status()["running"]:
                    start_mailpit()
            except Exception as e:
                self.log_message(f"[yellow]Mailpit notice: {e}[/yellow]")
            # 5. PHP-FPM pools
            if PHP_DIR.exists():
                for d in PHP_DIR.iterdir():
                    if d.is_dir():
                        try:
                            start_fpm(d.name)
                        except Exception as e:
                            self.log_message(f"[yellow]PHP {d.name} pool notice: {e}[/yellow]")

        await asyncio.to_thread(_do)
        self.log_message("[bold green]✓ All services started.[/bold green]")
        self.notify("All services started.", severity="information")
        self._refresh_all_data(full_rebuild=False)

    @work(exclusive=True)
    async def action_stop_all(self) -> None:
        """Stop all running services and FastCGI pools."""
        self.log_message("[bold blue]Stopping all services...[/bold blue]")
        self.notify("Stopping all web services...", severity="information")

        def _do() -> None:
            if shutil.which("systemctl"):
                subprocess.run(["sudo", "systemctl", "stop", "nginx"])
                subprocess.run(["sudo", "systemctl", "stop", "mariadb"])
            stop_pma()
            stop_mailpit()
            if PHP_DIR.exists():
                for d in PHP_DIR.iterdir():
                    if d.is_dir():
                        stop_fpm(d.name)

        await asyncio.to_thread(_do)
        self.log_message("[bold green]✓ All services stopped.[/bold green]")
        self.notify("All services stopped.", severity="information")
        self._refresh_all_data(full_rebuild=False)

    @work(exclusive=True)
    async def action_restart_all(self) -> None:
        """Restart all services."""
        self.log_message("[bold blue]Restarting all services...[/bold blue]")
        self.notify("Restarting all web services...", severity="information")

        def _do() -> None:
            if shutil.which("systemctl"):
                subprocess.run(["sudo", "systemctl", "restart", "nginx"])
                subprocess.run(["sudo", "systemctl", "restart", "mariadb"])
            restart_pma()
            if is_mailpit_installed():
                restart_mailpit()
            if PHP_DIR.exists():
                for d in PHP_DIR.iterdir():
                    if d.is_dir():
                        restart_fpm(d.name)

        await asyncio.to_thread(_do)
        self.log_message("[bold green]✓ All services restarted.[/bold green]")
        self.notify("All services restarted.", severity="information")
        self._refresh_all_data(full_rebuild=False)

    @work(exclusive=True)
    async def action_reload_nginx(self) -> None:
        """Reload Nginx configuration."""
        self.log_message("[bold blue]Reloading Nginx configuration...[/bold blue]")
        try:
            def _reload():
                if shutil.which("systemctl"):
                    subprocess.run(["sudo", "systemctl", "reload", "nginx"], check=True)
                else:
                    subprocess.run(["sudo", "service", "nginx", "reload"], check=True)
            await asyncio.to_thread(_reload)
            self.log_message("[bold green]✓ Nginx configuration reloaded successfully.[/bold green]")
            self.notify("Nginx reloaded.", severity="information")
        except Exception as e:
            self.log_message(f"[bold red]✗ Failed to reload Nginx: {e}[/bold red]")
            self.notify(f"Nginx reload failed: {e}", severity="error")

    def action_refresh_all(self) -> None:
        """User-triggered full refresh."""
        self.log_message("[dim]Refreshing dashboard data...[/dim]")
        self._refresh_all_data(full_rebuild=True)

    # ── BUTTON AND EVENT HANDLERS ─────────────────────────────────────────────

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "btn-start-all":
            self.action_start_all()
        elif btn_id == "btn-stop-all":
            self.action_stop_all()
        elif btn_id == "btn-restart-all":
            self.action_restart_all()
        elif btn_id == "btn-reload-nginx":
            self.action_reload_nginx()
        elif btn_id == "btn-tail-log":
            self._handle_tail_log()
        elif btn_id == "btn-clear-console":
            self.query_one("#console-log", RichLog).clear()
        elif btn_id == "btn-svc-start":
            self._handle_selected_service_action("start")
        elif btn_id == "btn-svc-stop":
            self._handle_selected_service_action("stop")
        elif btn_id == "btn-svc-restart":
            self._handle_selected_service_action("restart")
        elif btn_id == "btn-svc-open":
            self._handle_selected_service_open()
        elif btn_id == "btn-vhost-open":
            self._handle_selected_vhost_open()
        elif btn_id == "btn-php-set-active":
            self._handle_php_set_active()

    @work(exclusive=True)
    async def on_select_changed(self, event: Select.Changed) -> None:
        """Handle PHP version switcher or log selector dropdown changes."""
        if self._updating_selects:
            return

        if event.select.id == "select-php-version" and event.value != Select.BLANK:
            target_version = str(event.value)
            curr = CURRENT_LINK.resolve().name if (CURRENT_LINK.exists() or CURRENT_LINK.is_symlink()) else None
            if target_version != curr:
                await self._switch_php_version(target_version)

        elif event.select.id == "select-log-file" and event.value != Select.BLANK:
            self._handle_tail_log()

    def _handle_tail_log(self) -> None:
        """Read and display the tail of the selected log file."""
        log_select = self.query_one("#select-log-file", Select)
        log_name = log_select.value
        if not log_name or log_name == Select.BLANK:
            self.notify("Please select a log file first.", severity="warning")
            return

        log_path = self._available_logs.get(str(log_name))
        if not log_path or not log_path.exists():
            self.log_message(f"[yellow]Log file '{log_name}' not found at {log_path}[/yellow]")
            return

        self.log_message(f"[bold cyan]─── Tail: {log_name} ({log_path}) ───[/bold cyan]")
        try:
            lines = log_path.read_text(errors="ignore").splitlines()[-60:]
            if not lines:
                self.log_message("[dim](Log file is empty)[/dim]")
            else:
                for line in lines:
                    self.log_message(f"[dim]{line}[/dim]")
        except Exception as e:
            self.log_message(f"[bold red]Error reading log: {e}[/bold red]")

        # Switch to Logs tab to view tail
        self.query_one(TabbedContent).active = "tab-logs"

    # ── ROW SELECTION & PER-SERVICE ACTIONS ───────────────────────────────────

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        """Record the active row under cursor during keyboard navigation."""
        if event.data_table.id == "table-services" and event.row_key.value:
            self._selected_service_key = str(event.row_key.value)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle Enter key or double click on table rows."""
        table_id = event.data_table.id
        row_key = str(event.row_key.value) if event.row_key.value else ""

        if table_id == "table-services":
            self._selected_service_key = row_key
            if row_key in ["pma", "mailpit"]:
                self._handle_selected_service_open()
            else:
                self._handle_selected_service_action("restart")

        elif table_id == "table-vhosts":
            self._handle_selected_vhost_open()

        elif table_id == "table-php":
            if row_key:
                self._switch_php_version(row_key)

    @work(exclusive=True)
    async def _handle_selected_service_action(self, action: str) -> None:
        """Contextually start, stop, or restart the service highlighted in the table."""
        svc_table = self.query_one("#table-services", DataTable)
        if svc_table.cursor_row is not None and svc_table.row_count > 0:
            row_key = svc_table.coordinate_to_cell_key((svc_table.cursor_row, 0)).row_key
            self._selected_service_key = str(row_key.value)

        key = self._selected_service_key
        if not key:
            self.notify("Please select a service row from the table.", severity="warning")
            return

        self.log_message(f"[bold blue]Executing '{action}' on {key}...[/bold blue]")

        def _do() -> None:
            if key == "nginx":
                if shutil.which("systemctl"):
                    subprocess.run(["sudo", "systemctl", action, "nginx"], check=True)
                else:
                    subprocess.run(["sudo", "service", "nginx", action], check=True)

            elif key == "mariadb":
                if shutil.which("systemctl"):
                    subprocess.run(["sudo", "systemctl", action, "mariadb"], check=True)
                else:
                    subprocess.run(["sudo", "service", "mariadb", action], check=True)

            elif key == "pma":
                if action == "start":
                    start_pma()
                elif action == "stop":
                    stop_pma()
                elif action == "restart":
                    restart_pma()

            elif key == "mailpit":
                if action == "start":
                    start_mailpit()
                elif action == "stop":
                    stop_mailpit()
                elif action == "restart":
                    restart_mailpit()

            elif key.startswith("php:"):
                ver = key.split(":", 1)[1]
                if action == "start":
                    start_fpm(ver)
                elif action == "stop":
                    stop_fpm(ver)
                elif action == "restart":
                    restart_fpm(ver)

        try:
            await asyncio.to_thread(_do)
            self.log_message(f"[bold green]✓ '{action}' completed for {key}.[/bold green]")
            self.notify(f"{key} {action} completed.", severity="information")
        except Exception as e:
            self.log_message(f"[bold red]✗ Action '{action}' on {key} failed: {e}[/bold red]")
            self.notify(f"Action failed: {e}", severity="error")
        finally:
            self._refresh_all_data(full_rebuild=False)

    def _handle_selected_service_open(self) -> None:
        """Open web UI for phpMyAdmin or Mailpit if selected."""
        svc_table = self.query_one("#table-services", DataTable)
        if svc_table.cursor_row is not None and svc_table.row_count > 0:
            row_key = svc_table.coordinate_to_cell_key((svc_table.cursor_row, 0)).row_key
            self._selected_service_key = str(row_key.value)

        key = self._selected_service_key
        if key == "pma":
            st = get_pma_status()
            url = st.get("url") or "http://127.0.0.1:8080"
            webbrowser.open(url)
            self.log_message(f"Opening phpMyAdmin at {url}")
        elif key == "mailpit":
            st = get_mailpit_status()
            url = st.get("url") or "http://127.0.0.1:8025"
            webbrowser.open(url)
            self.log_message(f"Opening Mailpit at {url}")
        elif key == "nginx":
            webbrowser.open("http://127.0.0.1")
            self.log_message("Opening Nginx at http://127.0.0.1")
        else:
            self.notify("Selected service does not provide a web interface.", severity="information")

    def _handle_selected_vhost_open(self) -> None:
        """Open highlighted virtual host in default web browser."""
        vhost_table = self.query_one("#table-vhosts", DataTable)
        if vhost_table.cursor_row is not None and vhost_table.row_count > 0:
            row_key = vhost_table.coordinate_to_cell_key((vhost_table.cursor_row, 0)).row_key
            domain = str(row_key.value)
            webbrowser.open(f"http://{domain}")
            self.log_message(f"Opening virtual host: http://{domain}")

    def _handle_php_set_active(self) -> None:
        """Set the highlighted PHP version as the active CLI version."""
        php_table = self.query_one("#table-php", DataTable)
        if php_table.cursor_row is not None and php_table.row_count > 0:
            row_key = php_table.coordinate_to_cell_key((php_table.cursor_row, 0)).row_key
            ver = str(row_key.value)
            self._switch_php_version(ver)

    @work(exclusive=True)
    async def _switch_php_version(self, target_version: str) -> None:
        def _use() -> None:
            target = PHP_DIR / target_version
            if not target.exists():
                raise RuntimeError(f"PHP {target_version} is not installed.")
            if CURRENT_LINK.exists() or CURRENT_LINK.is_symlink():
                CURRENT_LINK.unlink()
            CURRENT_LINK.symlink_to(target)

            local_bin = Path(os.path.expanduser("~/.local/bin"))
            local_bin.mkdir(parents=True, exist_ok=True)
            for bin_name in ["php", "php-config", "phpize", "php-fpm", "composer"]:
                src = target / "bin" / bin_name
                if not src.exists() and bin_name == "php-fpm":
                    src = target / "sbin" / bin_name
                dst = local_bin / bin_name
                if src.exists():
                    if dst.exists() or dst.is_symlink():
                        dst.unlink()
                    dst.symlink_to(src)

        self.log_message(f"[bold blue]Switching active CLI PHP to {target_version}...[/bold blue]")
        try:
            await asyncio.to_thread(_use)
            self.log_message(f"[bold green]✓ Active PHP is now {target_version}[/bold green]")
            self.notify(f"Active PHP set to {target_version}", severity="information")
            self._refresh_all_data(full_rebuild=True)
        except Exception as e:
            self.log_message(f"[bold red]✗ Failed to switch PHP: {e}[/bold red]")
            self.notify(f"PHP switch failed: {e}", severity="error")


def run_dashboard() -> None:
    """Entrypoint to launch the Textual TUI app."""
    app = NdevDashboard()
    app.run()
