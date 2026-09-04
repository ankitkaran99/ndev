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
import threading
import webbrowser
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Checkbox,
    DataTable,
    DirectoryTree,
    Footer,
    Header,
    Input,
    Label,
    RichLog,
    Select,
    TabbedContent,
    TabPane,
)

from ndev.common.constants import NDEV_DIR, PHP_DIR, CURRENT_LINK, LOGS_DIR
from ndev.linux.runtime.fpm import get_fpm_status, start_fpm, stop_fpm, restart_fpm
from ndev.linux.runtime.pma import get_pma_status, start_pma, stop_pma, restart_pma, setup_pma
from ndev.linux.runtime.mailpit import get_mailpit_status, start_mailpit, stop_mailpit, restart_mailpit, is_installed as is_mailpit_installed, setup_mailpit
from ndev.linux.runtime import upgrade as upgrade_core


# ── CSS STYLESHEET ────────────────────────────────────────────────────────────

TUI_CSS = """
Screen {
    background: $surface;
    color: $text;
}

ModalScreen {
    align: center middle;
    background: rgba(0, 0, 0, 0.75);
}

#modal-dialog {
    width: 65;
    height: auto;
    max-height: 90%;
    background: $surface;
    border: thick $primary;
    padding: 1 2;
}

.picker-dialog {
    width: 80;
    height: 30;
    max-height: 90%;
}

#tree-dir-picker {
    height: 1fr;
    border: round $primary;
    margin: 1 0;
    background: $background;
}

#lbl-picker-current {
    color: $accent;
    text-style: bold;
    margin-bottom: 0;
}

.modal-input-row {
    height: auto;
    margin-bottom: 1;
}

.modal-input-row Input {
    width: 1fr;
}

.modal-input-row Button {
    width: auto;
    min-width: 14;
    margin-left: 1;
}

#modal-title {
    text-style: bold;
    color: $accent;
    margin-bottom: 1;
    text-align: center;
}

.modal-label {
    text-style: bold;
    margin-top: 1;
    margin-bottom: 0;
}

.modal-input {
    margin-bottom: 1;
}

#modal-buttons {
    layout: horizontal;
    height: auto;
    margin-top: 1;
    align: right middle;
}

#modal-buttons Button {
    margin-left: 1;
}

#app-grid {
    layout: horizontal;
    height: 1fr;
    width: 1fr;
}

#sidebar {
    width: 36;
    min-width: 32;
    max-width: 40;
    height: 1fr;
    background: $panel;
    border-right: vkey $primary-background;
    padding: 1;
}

.sidebar-section {
    height: auto;
    margin-bottom: 1;
    background: $surface;
    border: round $primary-background;
    padding: 0 1 1 1;
}

.section-title {
    text-style: bold;
    color: $accent;
    margin: 1 0;
    text-align: center;
}

.sidebar-btn {
    width: 100%;
    height: 3;
    margin-bottom: 1;
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


class DirectoryPickerModal(ModalScreen[Optional[str]]):
    """Interactive directory picker modal with Textual DirectoryTree on Linux."""

    def __init__(self, initial_path: Optional[str] = None) -> None:
        super().__init__()
        start_path = Path(initial_path).resolve() if initial_path and Path(initial_path).exists() else Path.cwd()
        while not start_path.exists() and start_path.parent != start_path:
            start_path = start_path.parent
        self.start_path = start_path

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog", classes="picker-dialog"):
            yield Label("📁 Select Document Root Directory", id="modal-title")
            yield Label(f"Current Path: {self.start_path}", id="lbl-picker-current", classes="modal-label")
            yield DirectoryTree(self.start_path, id="tree-dir-picker")
            with Horizontal(id="modal-buttons"):
                yield Button("Select Current Directory", variant="success", id="btn-picker-select")
                yield Button("Browse OS Dialog (GUI)...", variant="primary", id="btn-picker-tk")
                yield Button("Cancel", variant="default", id="btn-picker-cancel")

    def on_directory_tree_directory_selected(self, event: DirectoryTree.DirectorySelected) -> None:
        selected_path = str(event.path.resolve())
        self.query_one("#lbl-picker-current", Label).update(f"Current Path: {selected_path}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-picker-select":
            tree = self.query_one("#tree-dir-picker", DirectoryTree)
            if tree.cursor_node and tree.cursor_node.data:
                chosen = str(Path(tree.cursor_node.data.path).resolve())
            else:
                chosen = str(self.start_path)
            self.dismiss(chosen)
        elif event.button.id == "btn-picker-tk":
            def _open_tk() -> Optional[str]:
                try:
                    import tkinter as tk
                    from tkinter import filedialog
                    root = tk.Tk()
                    root.withdraw()
                    root.attributes("-topmost", True)
                    selected = filedialog.askdirectory(
                        title="Select Document Root Directory",
                        initialdir=str(self.start_path)
                    )
                    root.destroy()
                    return str(Path(selected).resolve()) if selected else None
                except Exception:
                    return None

            selected = _open_tk()
            if selected:
                self.dismiss(selected)
            else:
                self.notify("No folder selected from OS dialog.", severity="information")
        else:
            self.dismiss(None)


class CreateVhostModal(ModalScreen[Optional[dict]]):
    """Modal dialog to create a new virtual host with local SSL on Linux."""

    def __init__(self, installed_phps: list[str], default_php: Optional[str] = None) -> None:
        super().__init__()
        self.installed_phps = installed_phps
        self.default_php = default_php or (installed_phps[0] if installed_phps else "8.4")

    def compose(self) -> ComposeResult:
        php_options = [(v, v) for v in self.installed_phps] if self.installed_phps else [(self.default_php, self.default_php)]
        initial_php = self.default_php if self.default_php in [o[1] for o in php_options] else (php_options[0][1] if php_options else "8.4")

        with Vertical(id="modal-dialog"):
            yield Label("🌐 Create New Virtual Host", id="modal-title")
            yield Label("Domain Name (e.g. app.test):", classes="modal-label")
            yield Input(placeholder="app.test", id="input-vhost-domain", classes="modal-input")
            yield Label("Document Root Directory:", classes="modal-label")
            with Horizontal(classes="modal-input-row"):
                yield Input(placeholder="/var/www/app (or public folder)", id="input-vhost-root")
                yield Button("📁 Browse...", id="btn-vhost-browse", variant="primary")
            yield Label("PHP Version:", classes="modal-label")
            yield Select(php_options, value=initial_php, id="select-vhost-php", classes="modal-input")
            yield Checkbox("Enable Local SSL (HTTPS with mkcert)", value=True, id="chk-vhost-ssl")
            with Horizontal(id="modal-buttons"):
                yield Button("Create VHost", variant="success", id="btn-modal-create")
                yield Button("Cancel", variant="default", id="btn-modal-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-vhost-browse":
            current_val = self.query_one("#input-vhost-root", Input).value.strip()

            def _on_dir_chosen(chosen: Optional[str]) -> None:
                if chosen:
                    self.query_one("#input-vhost-root", Input).value = chosen

            self.app.push_screen(DirectoryPickerModal(current_val), _on_dir_chosen)
        elif event.button.id == "btn-modal-create":
            domain = self.query_one("#input-vhost-domain", Input).value.strip()
            root = self.query_one("#input-vhost-root", Input).value.strip()
            php_val = self.query_one("#select-vhost-php", Select).value
            php_ver = str(php_val) if (php_val is not None and php_val != Select.BLANK) else self.default_php
            ssl = self.query_one("#chk-vhost-ssl", Checkbox).value

            if not domain:
                self.notify("Domain name is required.", severity="error")
                return
            if not root:
                self.notify("Document root directory is required.", severity="error")
                return

            self.dismiss({
                "domain": domain,
                "root": root,
                "php": php_ver,
                "ssl": bool(ssl),
            })
        else:
            self.dismiss(None)


class ConfirmActionModal(ModalScreen[bool]):
    """Generic confirmation dialog for deletions and uninstalls on Linux."""

    def __init__(self, title: str, message: str, confirm_label: str = "Confirm", variant: str = "error") -> None:
        super().__init__()
        self.title_text = title
        self.message_text = message
        self.confirm_label = confirm_label
        self.btn_variant = variant

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog"):
            yield Label(self.title_text, id="modal-title")
            yield Label(self.message_text, classes="modal-label")
            with Horizontal(id="modal-buttons"):
                yield Button(self.confirm_label, variant=self.btn_variant, id="btn-modal-confirm")
                yield Button("Cancel", variant="default", id="btn-modal-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-modal-confirm":
            self.dismiss(True)
        else:
            self.dismiss(False)


DEFAULT_LINUX_PHP = [
    # PHP 8.4 series
    "8.4.25", "8.4.24", "8.4.20", "8.4.15", "8.4.10", "8.4.5", "8.4.0",
    # PHP 8.3 series
    "8.3.33", "8.3.17", "8.3.10", "8.3.5", "8.3.0",
    # PHP 8.2 series
    "8.2.33", "8.2.27", "8.2.20", "8.2.10", "8.2.0",
    # PHP 8.1 series
    "8.1.34", "8.1.31", "8.1.20", "8.1.10", "8.1.0",
    # PHP 8.0 series
    "8.0.30", "8.0.25", "8.0.15", "8.0.0",
    # PHP 7.4 series
    "7.4.33", "7.4.30", "7.4.20", "7.4.10", "7.4.0",
    # PHP 7.3 series
    "7.3.33", "7.3.25", "7.3.0",
    # PHP 7.2 series
    "7.2.34", "7.2.20", "7.2.0",
    # PHP 7.1 series
    "7.1.33", "7.1.20", "7.1.0",
    # PHP 7.0 series
    "7.0.33", "7.0.20", "7.0.0",
    # PHP 5.6 series
    "5.6.40",
]


class InstallPhpModal(ModalScreen[Optional[dict]]):
    """Modal dialog to select and install a PHP runtime on Linux."""

    def __init__(self, popular_versions: Optional[list[str]] = None) -> None:
        super().__init__()
        self.popular_versions = popular_versions or DEFAULT_LINUX_PHP

    def compose(self) -> ComposeResult:
        opts = [(f"PHP {v}", v) for v in self.popular_versions]
        default_v = opts[0][1] if opts else "8.4.25"


        with Vertical(id="modal-dialog"):
            yield Label("🐘 Install PHP Runtime", id="modal-title")
            yield Label("Select PHP Release:", classes="modal-label")
            yield Select(opts, value=default_v, id="select-php-ver", classes="modal-input")
            yield Label("Or specify Custom Version (e.g. 8.4.25):", classes="modal-label")
            yield Input(placeholder="Leave blank to use selected release above", id="input-custom-ver", classes="modal-input")
            with Horizontal(id="modal-buttons"):
                yield Button("Install PHP", variant="success", id="btn-modal-install")
                yield Button("Cancel", variant="default", id="btn-modal-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-modal-install":
            custom = self.query_one("#input-custom-ver", Input).value.strip()
            sel_val = self.query_one("#select-php-ver", Select).value
            selected = str(sel_val) if (sel_val is not None and sel_val != Select.BLANK) else "8.4.25"
            version = custom if custom else selected

            self.dismiss({
                "version": version,
            })
        else:
            self.dismiss(None)


# ── MAIN APPLICATION ──────────────────────────────────────────────────────────

class NdevDashboard(App):
    """Modern asynchronous TUI dashboard for ndev Linux."""

    TITLE = "ndev"
    SUB_TITLE = "Local Web Stack Dashboard (Linux)"
    CSS = TUI_CSS

    BINDINGS = [
        Binding("q", "quit", "Quit", priority=True),
        Binding("r", "refresh_all", "Refresh", priority=True),
        Binding("s", "start_all", "Start All"),
        Binding("x", "stop_all", "Stop All"),
        Binding("t", "restart_all", "Restart All"),
        Binding("l", "reload_nginx", "Reload Nginx"),
        Binding("u", "check_upgrades", "Check Upgrades"),
        Binding("U", "upgrade_stack", "Upgrade Stack"),
        Binding("v", "create_vhost", "Create VHost"),
        Binding("i", "install_php", "Install PHP"),
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
                    yield Button("▶ Start All", id="btn-start-all", variant="success", classes="sidebar-btn")
                    yield Button("⏹ Stop All", id="btn-stop-all", variant="error", classes="sidebar-btn")
                    yield Button("🔄 Restart All", id="btn-restart-all", variant="warning", classes="sidebar-btn")
                    yield Button("⚡ Reload Nginx", id="btn-reload-nginx", variant="primary", classes="sidebar-btn")
                    yield Button("🌐 New Virtual Host", id="btn-sidebar-create-vhost", variant="success", classes="sidebar-btn")
                    yield Button("🐘 Install PHP", id="btn-sidebar-install-php", variant="success", classes="sidebar-btn")
                    yield Button("🔍 Check Upgrades", id="btn-check-upgrades", variant="default", classes="sidebar-btn")
                    yield Button("🚀 Upgrade Stack", id="btn-upgrade-stack", variant="primary", classes="sidebar-btn")

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
                    yield Label("• Redis: 6379")
                    yield Label("• PMA (phpMyAdmin): 8080")
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
                            yield Button("Install Selected", id="btn-svc-install", variant="success")
                            yield Button("Open Web UI", id="btn-svc-open", variant="primary")
                            yield Button("Check Upgrades", id="btn-svc-check-upgrades", variant="default")

                    with TabPane("🌐 Virtual Hosts", id="tab-vhosts"):
                        yield DataTable(id="table-vhosts", cursor_type="row", zebra_stripes=True)
                        with Horizontal(classes="tab-action-bar"):
                            yield Button("＋ Create VHost", id="btn-vhost-create", variant="success")
                            yield Button("✖ Delete Selected", id="btn-vhost-delete", variant="error")
                            yield Button("🌐 Open in Browser", id="btn-vhost-open", variant="primary")

                    with TabPane("🐘 PHP Runtimes", id="tab-php"):
                        yield DataTable(id="table-php", cursor_type="row", zebra_stripes=True)
                        with Horizontal(classes="tab-action-bar"):
                            yield Button("＋ Install PHP", id="btn-php-install", variant="success")
                            yield Button("✖ Uninstall Selected", id="btn-php-uninstall", variant="error")
                            yield Button("⭐ Set as Active CLI", id="btn-php-set-active", variant="primary")

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
        def _write() -> None:
            now = datetime.datetime.now().strftime("%H:%M:%S")
            try:
                log_widget = self.query_one("#console-log", RichLog)
                log_widget.write(f"[dim]{now}[/dim] {message}")
            except Exception:
                pass

        if not self.is_mounted:
            return
        if hasattr(self, "_thread_id") and threading.get_ident() == self._thread_id:
            _write()
        else:
            try:
                self.call_from_thread(_write)
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

            # 3. Redis
            redis_installed = bool(shutil.which("redis-server"))
            redis_running = False
            if redis_installed and shutil.which("systemctl"):
                res = subprocess.run(["systemctl", "is-active", "--quiet", "redis-server"])
                if res.returncode != 0:
                    res = subprocess.run(["systemctl", "is-active", "--quiet", "redis"])
                redis_running = (res.returncode == 0)

            results.append({
                "key": "redis",
                "name": "Redis",
                "type": "In-Memory Store",
                "installed": redis_installed,
                "running": redis_running,
                "pid": "Active" if redis_running else "-",
                "details": "Port: 6379 (CLI: redis-cli)",
                "url": None,
            })

            # 4. phpMyAdmin
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

            # 5. Mailpit
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

            # 6. PHP-FPM Pools

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
            self._available_logs = logs_dict

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
            # 3. Redis
            if shutil.which("systemctl"):
                subprocess.run(["sudo", "systemctl", "start", "redis-server"])
            # 4. phpMyAdmin
            try:
                start_pma()
            except Exception as e:
                self.log_message(f"[yellow]phpMyAdmin notice: {e}[/yellow]")
            # 5. Mailpit
            try:
                if is_mailpit_installed() and not get_mailpit_status()["running"]:
                    start_mailpit()
            except Exception as e:
                self.log_message(f"[yellow]Mailpit notice: {e}[/yellow]")
            # 6. PHP-FPM pools
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
                subprocess.run(["sudo", "systemctl", "stop", "redis-server"])
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

    @work(exclusive=True)
    async def action_check_upgrades(self) -> None:
        """Query upstream releases and display version check results in the console."""
        self.query_one(TabbedContent).active = "tab-logs"
        self.log_message("[bold cyan]═══════════════════════════════════════════════════[/bold cyan]")
        self.log_message("[bold cyan]🔍 Checking for Stack Component Updates...[/bold cyan]")
        self.log_message("[bold cyan]═══════════════════════════════════════════════════[/bold cyan]")
        self.notify("Checking component versions...", severity="information")

        try:
            infos = await asyncio.to_thread(upgrade_core.check_all)
            upgradable = []
            for info in infos:
                curr_str = info.current_version or "[dim]Not installed[/dim]"
                latest_str = info.latest_version or "[dim]Unknown[/dim]"
                if not info.installed:
                    self.log_message(f"• [yellow]{info.display_name:<28}[/yellow] [dim]Not Installed[/dim] (Latest: {latest_str})")
                elif info.update_available:
                    self.log_message(f"• [bold green]{info.display_name:<28}[/bold green] [yellow]{curr_str}[/yellow] -> [bold green]{latest_str}[/bold green] [bold yellow](UPDATE AVAILABLE)[/bold yellow]")
                    upgradable.append(info)
                else:
                    self.log_message(f"• [bold green]{info.display_name:<28}[/bold green] [dim]{curr_str}[/dim] [green]✓ Up-to-date[/green]")

            if upgradable:
                names = ", ".join([c.display_name for c in upgradable])
                self.log_message(f"\n[bold yellow]⚡ {len(upgradable)} component(s) can be upgraded: {names}[/bold yellow]")
                self.log_message("[dim]Click 'Upgrade Stack' in the sidebar or press Shift+U to install updates.[/dim]")
                self.notify(f"{len(upgradable)} updates available: {names}", severity="warning")
            else:
                self.log_message("\n[bold green]✓ All installed stack components are up-to-date![/bold green]")
                self.notify("All stack components are up-to-date.", severity="information")
        except Exception as e:
            self.log_message(f"[bold red]✗ Failed to check upgrades: {e}[/bold red]")
            self.notify(f"Check failed: {e}", severity="error")

    @work(exclusive=True)
    async def action_upgrade_stack(self) -> None:
        """Check for and upgrade all stack components needing updates."""
        self.query_one(TabbedContent).active = "tab-logs"
        self.log_message("[bold blue]═══════════════════════════════════════════════════[/bold blue]")
        self.log_message("[bold blue]🚀 Starting Stack Component Upgrade Process...[/bold blue]")
        self.log_message("[bold blue]═══════════════════════════════════════════════════[/bold blue]")
        self.notify("Scanning stack components for upgrades...", severity="information")

        try:
            infos = await asyncio.to_thread(upgrade_core.check_all)
            upgradable = [c for c in infos if c.update_available]
            if not upgradable:
                self.log_message("[bold green]✓ All installed stack components are already up-to-date![/bold green]")
                self.notify("All components are up-to-date.", severity="information")
                return

            self.log_message(f"[bold cyan]Upgrading {len(upgradable)} component(s)...[/bold cyan]")
            for c in upgradable:
                self.log_message(f"[bold blue]• Upgrading {c.display_name} ({c.current_version} -> {c.latest_version})...[/bold blue]")
                ok, msg = await asyncio.to_thread(upgrade_core.upgrade_component, c.name)
                if ok:
                    self.log_message(f"[bold green]  ✓ {msg}[/bold green]")
                    self.notify(f"{c.display_name} upgraded!", severity="information")
                else:
                    self.log_message(f"[bold red]  ✗ {msg}[/bold red]")
                    self.notify(f"{c.display_name} upgrade failed", severity="error")

            self.log_message("[bold green]═══════════════════════════════════════════════════[/bold green]")
            self.log_message("[bold green]✓ Upgrade process completed![/bold green]")
            self.log_message("[bold green]═══════════════════════════════════════════════════[/bold green]")
            self._refresh_all_data(full_rebuild=True)
        except Exception as e:
            self.log_message(f"[bold red]✗ Upgrade process failed: {e}[/bold red]")
            self.notify(f"Upgrade failed: {e}", severity="error")

    # ── BUTTON AND EVENT HANDLERS ─────────────────────────────────────────────
 
    @on(Button.Pressed)
    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "btn-start-all":
            self.action_start_all()
        elif btn_id == "btn-stop-all":
            self.action_stop_all()
        elif btn_id == "btn-restart-all":
            self.action_restart_all()
        elif btn_id == "btn-reload-nginx":
            self.action_reload_nginx()
        elif btn_id in ["btn-check-upgrades", "btn-svc-check-upgrades"]:
            self.action_check_upgrades()
        elif btn_id == "btn-upgrade-stack":
            self.action_upgrade_stack()
        elif btn_id in ["btn-sidebar-create-vhost", "btn-vhost-create"]:
            self.action_create_vhost()
        elif btn_id == "btn-vhost-delete":
            self.action_delete_vhost()
        elif btn_id in ["btn-sidebar-install-php", "btn-php-install"]:
            self.action_install_php()
        elif btn_id == "btn-php-uninstall":
            self.action_uninstall_php()
        elif btn_id == "btn-svc-install":
            self._handle_selected_service_install()
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

    # ── VHOST, PHP & SERVICE INSTALL ACTIONS ──────────────────────────────────

    def action_create_vhost(self) -> None:
        """Open modal dialog to create a new virtual host."""
        installed = []
        if PHP_DIR.exists():
            installed = sorted([d.name for d in PHP_DIR.iterdir() if d.is_dir()])
        curr = CURRENT_LINK.resolve().name if (CURRENT_LINK.exists() or CURRENT_LINK.is_symlink()) else None

        def _on_modal_result(res: Optional[dict]) -> None:
            if res:
                self._create_vhost_worker(res["domain"], res["root"], res["php"], res["ssl"])

        self.push_screen(CreateVhostModal(installed, curr), _on_modal_result)

    @work(exclusive=True)
    async def _create_vhost_worker(self, domain: str, root: str, php_ver: str, ssl: bool) -> None:
        self.query_one(TabbedContent).active = "tab-logs"
        self.log_message(f"[bold blue]Creating virtual host '{domain}' (PHP {php_ver}, SSL={ssl})...[/bold blue]")
        self.notify(f"Creating vhost {domain}...", severity="information")

        def _do() -> str:
            from ndev.linux.commands.vhost import generate_local_cert
            nginx_available = Path("/etc/nginx/sites-available")
            nginx_enabled = Path("/etc/nginx/sites-enabled")
            if not nginx_available.exists():
                nginx_available = NDEV_DIR / "nginx" / "conf" / "ndev-vhosts"
                nginx_enabled = nginx_available
                nginx_available.mkdir(parents=True, exist_ok=True)

            conf_file = nginx_available / f"{domain}.conf"
            cert_dir = NDEV_DIR / "certs"
            cert_path, key_path = None, None
            if ssl:
                cert_path, key_path = generate_local_cert(domain, cert_dir)

            mm = php_ver.replace(".", "")[:2] if "." in php_ver else php_ver
            selected_sock = NDEV_DIR / "run" / f"php{mm}.sock"

            if ssl:
                tpl = f"""server {{
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name {domain};
    ssl_certificate {cert_path};
    ssl_certificate_key {key_path};
    root {root};
    index index.php index.html index.htm;
    access_log /var/log/nginx/{domain}.access.log;
    error_log  /var/log/nginx/{domain}.error.log;
    location / {{
        try_files $uri $uri/ /index.php?$query_string;
    }}
    location ~ \\.php$ {{
        include snippets/fastcgi-php.conf;
        fastcgi_pass unix:{selected_sock};
    }}
    location ~ /\\.ht {{
        deny all;
    }}
}}
"""
            else:
                tpl = f"""server {{
    listen 80;
    listen [::]:80;
    server_name {domain};
    root {root};
    index index.php index.html index.htm;
    access_log /var/log/nginx/{domain}.access.log;
    error_log  /var/log/nginx/{domain}.error.log;
    location / {{
        try_files $uri $uri/ /index.php?$query_string;
    }}
    location ~ \\.php$ {{
        include snippets/fastcgi-php.conf;
        fastcgi_pass unix:{selected_sock};
    }}
    location ~ /\\.ht {{
        deny all;
    }}
}}
"""
            conf_file.write_text(tpl)
            if nginx_enabled != nginx_available:
                link = nginx_enabled / f"{domain}.conf"
                link.unlink(missing_ok=True)
                link.symlink_to(conf_file)

            # Add /etc/hosts entry if writable
            try:
                hosts = Path("/etc/hosts")
                if hosts.exists():
                    txt = hosts.read_text()
                    if domain not in txt:
                        with hosts.open("a") as hf:
                            hf.write(f"\n127.0.0.1 {domain}\n")
            except Exception:
                pass

            # Reload Nginx
            try:
                subprocess.run(["systemctl", "reload", "nginx"], capture_output=True, timeout=5)
            except Exception:
                pass
            return str(conf_file)

        try:
            conf_path = await asyncio.to_thread(_do)
            self.log_message(f"[bold green]✓ Virtual host created successfully: {conf_path}[/bold green]")
            proto = "https" if ssl else "http"
            self.log_message(f"  • URL: [link={proto}://{domain}]{proto}://{domain}[/link]")
            self.log_message(f"  • Root: {root}")
            self.notify(f"Virtual host {domain} created!", severity="information")
            self.query_one(TabbedContent).active = "tab-vhosts"
            self._refresh_all_data(full_rebuild=True)
        except Exception as e:
            self.log_message(f"[bold red]✗ Failed to create virtual host {domain}: {e}[/bold red]")
            self.notify(f"VHost creation failed: {e}", severity="error")

    def action_delete_vhost(self) -> None:
        """Prompt to delete the currently selected virtual host."""
        vhost_table = self.query_one("#table-vhosts", DataTable)
        if vhost_table.cursor_row is None or vhost_table.row_count == 0:
            self.notify("Please select a virtual host row to delete.", severity="warning")
            return

        row_key = vhost_table.coordinate_to_cell_key((vhost_table.cursor_row, 0)).row_key
        domain = str(row_key.value)

        def _on_confirm(confirmed: bool) -> None:
            if confirmed:
                self._delete_vhost_worker(domain)

        msg = f"Are you sure you want to delete virtual host '{domain}'?\n\nThis will remove its Nginx configuration, SSL certificates, and hosts entry."
        self.push_screen(ConfirmActionModal("Delete Virtual Host", msg, confirm_label="Delete VHost", variant="error"), _on_confirm)

    @work(exclusive=True)
    async def _delete_vhost_worker(self, domain: str) -> None:
        self.log_message(f"[bold yellow]Deleting virtual host '{domain}'...[/bold yellow]")
        self.notify(f"Deleting vhost {domain}...", severity="information")

        def _do() -> None:
            for d in [Path("/etc/nginx/sites-enabled"), Path("/etc/nginx/sites-available"), NDEV_DIR / "nginx" / "conf" / "ndev-vhosts"]:
                f = d / f"{domain}.conf"
                if f.exists() or f.is_symlink():
                    f.unlink()
            try:
                subprocess.run(["systemctl", "reload", "nginx"], capture_output=True, timeout=5)
            except Exception:
                pass

        try:
            await asyncio.to_thread(_do)
            self.log_message(f"[bold green]✓ Virtual host '{domain}' deleted successfully.[/bold green]")
            self.notify(f"Virtual host {domain} deleted.", severity="information")
            self._refresh_all_data(full_rebuild=True)
        except Exception as e:
            self.log_message(f"[bold red]✗ Failed to delete virtual host {domain}: {e}[/bold red]")
            self.notify(f"Delete failed: {e}", severity="error")

    def action_install_php(self) -> None:
        """Open modal dialog to install a new PHP runtime."""
        def _on_modal_result(res: Optional[dict]) -> None:
            if res:
                self._install_php_worker(res["version"])

        self.push_screen(InstallPhpModal(), _on_modal_result)

    @work(exclusive=True)
    async def _install_php_worker(self, version: str) -> None:
        self.query_one(TabbedContent).active = "tab-logs"
        self.log_message("[bold blue]═══════════════════════════════════════════════════[/bold blue]")
        self.log_message(f"[bold blue]🐘 Installing PHP {version}...[/bold blue]")
        self.notify(f"Installing PHP {version}...", severity="information")

        try:
            from ndev.linux.php.installer import install_version
            resolved = await asyncio.to_thread(install_version, version)
            self.log_message(f"[bold green]✓ PHP {resolved} installed successfully![/bold green]")
            self.notify(f"PHP {resolved} installed!", severity="information")
            self.query_one(TabbedContent).active = "tab-php"
            self._refresh_all_data(full_rebuild=True)
        except Exception as e:
            self.log_message(f"[bold red]✗ PHP installation failed: {e}[/bold red]")
            self.notify(f"Install failed: {e}", severity="error")

    def action_uninstall_php(self) -> None:
        """Prompt to uninstall the currently selected PHP runtime."""
        php_table = self.query_one("#table-php", DataTable)
        if php_table.cursor_row is None or php_table.row_count == 0:
            self.notify("Please select a PHP version row to uninstall.", severity="warning")
            return

        row_key = php_table.coordinate_to_cell_key((php_table.cursor_row, 0)).row_key
        ver = str(row_key.value)

        def _on_confirm(confirmed: bool) -> None:
            if confirmed:
                self._uninstall_php_worker(ver)

        msg = f"Are you sure you want to uninstall PHP {ver}?\n\nThis will stop its PHP-FPM pool and remove the installation directory."
        self.push_screen(ConfirmActionModal("Uninstall PHP Runtime", msg, confirm_label="Uninstall PHP", variant="error"), _on_confirm)

    @work(exclusive=True)
    async def _uninstall_php_worker(self, version: str) -> None:
        self.log_message(f"[bold yellow]Uninstalling PHP {version}...[/bold yellow]")
        self.notify(f"Uninstalling PHP {version}...", severity="information")

        def _do() -> None:
            stop_fpm(version)
            prefix = PHP_DIR / version
            if prefix.exists():
                shutil.rmtree(prefix)
            if CURRENT_LINK.exists() and CURRENT_LINK.is_symlink():
                if CURRENT_LINK.resolve() == prefix.resolve():
                    CURRENT_LINK.unlink()

        try:
            await asyncio.to_thread(_do)
            self.log_message(f"[bold green]✓ PHP {version} uninstalled successfully.[/bold green]")
            self.notify(f"PHP {version} uninstalled.", severity="information")
            self._refresh_all_data(full_rebuild=True)
        except Exception as e:
            self.log_message(f"[bold red]✗ Failed to uninstall PHP {version}: {e}[/bold red]")
            self.notify(f"Uninstall failed: {e}", severity="error")

    def _handle_selected_service_install(self) -> None:
        """Install or setup the selected service (PMA, Mailpit, Nginx, MariaDB)."""
        svc_table = self.query_one("#table-services", DataTable)
        if svc_table.cursor_row is not None and svc_table.row_count > 0:
            row_key = svc_table.coordinate_to_cell_key((svc_table.cursor_row, 0)).row_key
            self._selected_service_key = str(row_key.value)

        key = self._selected_service_key
        if not key:
            self.notify("Please select a service row from the table.", severity="warning")
            return

        self._install_service_worker(key)

    @work(exclusive=True)
    async def _install_service_worker(self, key: str) -> None:
        self.query_one(TabbedContent).active = "tab-logs"
        self.log_message(f"[bold blue]Installing/setting up component '{key}'...[/bold blue]")
        self.notify(f"Installing {key}...", severity="information")

        def _do() -> None:
            if key == "pma":
                setup_pma()
            elif key == "mailpit":
                setup_mailpit()
            elif key == "redis":
                if shutil.which("apt"):
                    subprocess.run(["sudo", "apt-get", "install", "-y", "redis-server"], check=True)
            elif key == "nginx":
                if shutil.which("apt"):
                    subprocess.run(["sudo", "apt-get", "install", "-y", "nginx"], check=True)
            elif key == "mariadb":
                if shutil.which("apt"):
                    subprocess.run(["sudo", "apt-get", "install", "-y", "mariadb-server"], check=True)


        try:
            await asyncio.to_thread(_do)
            self.log_message(f"[bold green]✓ Component '{key}' installed and configured successfully![/bold green]")
            self.notify(f"{key} installed successfully!", severity="information")
            self._refresh_all_data(full_rebuild=True)
        except Exception as e:
            self.log_message(f"[bold red]✗ Failed to install {key}: {e}[/bold red]")
            self.notify(f"Installation failed: {e}", severity="error")

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
        self.query_one(TabbedContent).active = "tab-logs"
        log_select = self.query_one("#select-log-file", Select)
        log_name = log_select.value
        if not log_name or log_name == Select.BLANK:
            if self._available_logs:
                first_key = sorted(self._available_logs.keys())[0]
                self._updating_selects = True
                try:
                    log_select.value = first_key
                finally:
                    self._updating_selects = False
                log_name = first_key
            else:
                self.notify("No log files are currently available.", severity="warning")
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

            elif key == "redis":
                if shutil.which("systemctl"):
                    subprocess.run(["sudo", "systemctl", action, "redis-server"], check=True)
                else:
                    subprocess.run(["sudo", "service", "redis-server", action], check=True)

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
