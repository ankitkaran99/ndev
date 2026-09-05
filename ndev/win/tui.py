"""
Textual TUI dashboard for ndev-win (local PHP/Nginx/MariaDB web stack manager).
"""
from __future__ import annotations

import asyncio
import datetime
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
    Footer,
    Header,
    Input,
    Label,
    RichLog,
    Select,
    TabbedContent,
    TabPane,
)

from .core import fcgi, logs, mailpit, paths, php, pma, redis_core, services, setup as setup_core, upgrade as upgrade_core, vhost



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
    width: 38;
    min-width: 34;
    max-width: 44;
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

#status-summary-box {
    height: auto;
    color: $text-muted;
    margin-top: 1;
    padding: 1;
    border: dashed $primary-background;
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

.status-badge-running {
    color: $success;
    text-style: bold;
}

.status-badge-stopped {
    color: $error;
    text-style: bold;
}

.status-badge-warning {
    color: $warning;
    text-style: bold;
}

#status-summary-box {
    color: $text-muted;
    margin-top: 1;
    padding: 1;
    border: dashed $primary-background;
}
"""


def _pick_directory_os(initial_path: Optional[str] = None) -> Optional[str]:
    """Open native OS folder dialog via tkinter or PowerShell FolderBrowserDialog."""
    start_dir = Path(initial_path).resolve() if initial_path and Path(initial_path).exists() else Path.cwd()
    while not start_dir.exists() and start_dir.parent != start_dir:
        start_dir = start_dir.parent

    # Try tkinter first
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        selected = filedialog.askdirectory(
            title="Select Document Root Directory",
            initialdir=str(start_dir)
        )
        root.destroy()
        if selected:
            return str(Path(selected).resolve())
        elif selected == "":
            return None
    except Exception:
        pass

    # Fallback to PowerShell FolderBrowserDialog
    try:
        import subprocess
        escaped_path = str(start_dir).replace("'", "''")
        ps_cmd = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$f = New-Object System.Windows.Forms.FolderBrowserDialog; "
            f"$f.SelectedPath = '{escaped_path}'; "
            "$f.Description = 'Select Document Root Directory'; "
            "if ($f.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { Write-Output $f.SelectedPath }"
        )
        res = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
            capture_output=True,
            text=True
        )
        if res.returncode == 0 and res.stdout.strip():
            return str(Path(res.stdout.strip()).resolve())
    except Exception:
        pass

    return None


class CreateVhostModal(ModalScreen[Optional[dict]]):
    """Modal dialog to create a new virtual host with local SSL and directory picker."""

    def __init__(self, installed_phps: list[str], default_php: Optional[str] = None) -> None:
        super().__init__()
        self.installed_phps = installed_phps
        self.default_php = default_php or (installed_phps[0] if installed_phps else "8.4")
        self._user_edited_root = False

    def compose(self) -> ComposeResult:
        php_options = [(v, v) for v in self.installed_phps] if self.installed_phps else [(self.default_php, self.default_php)]
        initial_php = self.default_php if self.default_php in [o[1] for o in php_options] else (php_options[0][1] if php_options else "8.4")
        default_root_placeholder = str(Path.home() / "Sites" / "app.test")

        with Vertical(id="modal-dialog"):
            yield Label("🌐 Create New Virtual Host", id="modal-title")
            yield Label("Domain Name (e.g. app.test):", classes="modal-label")
            yield Input(placeholder="app.test", id="input-vhost-domain", classes="modal-input")
            yield Label("Document Root Directory:", classes="modal-label")
            with Horizontal(classes="modal-input-row"):
                yield Input(placeholder=default_root_placeholder, id="input-vhost-root")
                yield Button("📁 Browse...", id="btn-vhost-browse", variant="primary")
            yield Label("PHP Version:", classes="modal-label")
            yield Select(php_options, value=initial_php, id="select-vhost-php", classes="modal-input")
            yield Checkbox("Enable Local SSL (HTTPS with mkcert)", value=True, id="chk-vhost-ssl")
            with Horizontal(id="modal-buttons"):
                yield Button("Create VHost", variant="success", id="btn-modal-create")
                yield Button("Cancel", variant="default", id="btn-modal-cancel")

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "input-vhost-domain":
            domain = event.value.strip()
            if not self._user_edited_root:
                root_input = self.query_one("#input-vhost-root", Input)
                if domain:
                    root_input.value = str(Path.home() / "Sites" / domain)
                else:
                    root_input.value = ""
        elif event.input.id == "input-vhost-root":
            domain = self.query_one("#input-vhost-domain", Input).value.strip()
            expected = str(Path.home() / "Sites" / domain) if domain else ""
            if event.value != expected:
                self._user_edited_root = bool(event.value.strip())

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-vhost-browse":
            current_val = self.query_one("#input-vhost-root", Input).value.strip()
            if not current_val:
                domain = self.query_one("#input-vhost-domain", Input).value.strip()
                current_val = str(Path.home() / "Sites" / domain) if domain else str(Path.home() / "Sites")
            chosen = _pick_directory_os(current_val)
            if chosen:
                self._user_edited_root = True
                self.query_one("#input-vhost-root", Input).value = chosen
        elif event.button.id == "btn-modal-create":
            domain = self.query_one("#input-vhost-domain", Input).value.strip()
            root = self.query_one("#input-vhost-root", Input).value.strip()
            if not root and domain:
                root = str(Path.home() / "Sites" / domain)
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
    """Generic confirmation dialog for deletions and uninstalls."""

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


DEFAULT_POPULAR_PHP = [
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
    """Modal dialog to select and install a PHP runtime."""

    def __init__(self, available_versions: Optional[list[str]] = None) -> None:
        super().__init__()
        self.available_versions = available_versions or DEFAULT_POPULAR_PHP

    def compose(self) -> ComposeResult:
        opts = [(f"PHP {v}", v) for v in self.available_versions]
        default_v = opts[0][1] if opts else "8.4.25"

        with Vertical(id="modal-dialog"):
            yield Label("🐘 Install PHP Runtime", id="modal-title")
            yield Label("Select Upstream PHP Release:", classes="modal-label")
            yield Select(opts, value=default_v, id="select-php-ver", classes="modal-input")
            yield Label("Or specify Custom Version / Query (e.g. 8.4, 8.3.17, 7.4):", classes="modal-label")
            yield Input(placeholder="Leave blank to use selected release above", id="input-custom-ver", classes="modal-input")
            yield Checkbox("Thread-Safe (TS, recommended for FastCGI)", value=True, id="chk-php-ts")
            with Horizontal(id="modal-buttons"):
                yield Button("Download & Install", variant="success", id="btn-modal-install")
                yield Button("Cancel", variant="default", id="btn-modal-cancel")


    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-modal-install":
            custom = self.query_one("#input-custom-ver", Input).value.strip()
            sel_val = self.query_one("#select-php-ver", Select).value
            selected = str(sel_val) if (sel_val is not None and sel_val != Select.BLANK) else "8.4.25"
            version = custom if custom else selected
            is_ts = self.query_one("#chk-php-ts", Checkbox).value

            self.dismiss({
                "version": version,
                "thread_safe": bool(is_ts),
                "nts": not bool(is_ts),
            })
        else:
            self.dismiss(None)


# ── MAIN APPLICATION ──────────────────────────────────────────────────────────

class NdevDashboard(App):
    """Modern asynchronous TUI dashboard for ndev."""

    TITLE = "ndev"
    SUB_TITLE = "Local Web Stack Dashboard"
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
                    yield Label("• phpMyAdmin (PMA): 8080")
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
                            yield Button("⭐ Set Active CLI", id="btn-php-set-active", variant="primary")
                            yield Button("▶ Start Pool", id="btn-php-pool-start", variant="default")
                            yield Button("⏹ Stop Pool", id="btn-php-pool-stop", variant="default")

                    with TabPane("📋 Live Console / Logs", id="tab-logs"):
                        yield RichLog(id="console-log", highlight=True, markup=True)
                        with Horizontal(classes="tab-action-bar"):
                            yield Button("Clear Console", id="btn-clear-console", variant="default")

        yield Footer()

    # ── LIFECYCLE HOOKS ───────────────────────────────────────────────────────

    async def on_mount(self) -> None:
        """Initialize data tables, load logs, populate dropdowns, and start background polling."""
        self._init_tables()
        self.log_message("[bold green]ndev TUI dashboard loaded.[/bold green]")

        # Initial data load
        self._refresh_all_data(full_rebuild=True)

        # Polling timer every 3.5 seconds
        self.set_interval(3.5, self._on_poll_timer)

    def _init_tables(self) -> None:
        """Configure columns for all DataTables."""
        svc_table = self.query_one("#table-services", DataTable)
        svc_table.add_columns("Status", "Service", "Type", "PID", "Listening Ports / Details")

        vhost_table = self.query_one("#table-vhosts", DataTable)
        vhost_table.add_columns("Domain", "URL", "PHP Version", "SSL", "Document Root")

        php_table = self.query_one("#table-php", DataTable)
        php_table.add_columns("Version", "CLI Active", "Pool Status", "Workers", "Directory Path")

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
        """Collect all service states concurrently without blocking the UI loop."""
        def _get() -> List[Dict[str, Any]]:
            results = []

            # 1. Nginx
            ng_installed = services.nginx_is_installed()
            ng_running = services.nginx_is_running() if ng_installed else False
            results.append({
                "key": "nginx",
                "name": "Nginx",
                "type": "Web Server",
                "installed": ng_installed,
                "running": ng_running,
                "pid": "-" if not ng_running else "Active",
                "details": f"Config: {paths.NGINX_CONF_D}" if ng_installed else "Run `ndev setup`",
                "url": "http://127.0.0.1",
            })

            # 2. MariaDB
            mb_installed = services.mariadb_is_installed()
            mb_st = services.mariadb_status() if mb_installed else None
            mb_running = bool(mb_st and mb_st.get("running"))
            mb_pid = str(mb_st.get("pid")) if (mb_running and mb_st) else "-"
            results.append({
                "key": "mariadb",
                "name": "MariaDB",
                "type": "Database",
                "installed": mb_installed,
                "running": mb_running,
                "pid": mb_pid,
                "details": "Port 3306 (user: root / root)" if mb_running else f"Data: {paths.MARIADB_DIR / 'data'}",
                "url": None,
            })

            # 3. Redis
            rd_installed = redis_core.is_installed()
            rd_st = redis_core.status() if rd_installed else None
            rd_running = bool(rd_st and rd_st.get("running"))
            rd_pid = str(rd_st.get("pid")) if (rd_running and rd_st) else "-"
            results.append({
                "key": "redis",
                "name": "Redis",
                "type": "In-Memory Store",
                "installed": rd_installed,
                "running": rd_running,
                "pid": rd_pid,
                "details": "Port 6379 (CLI: redis-cli)" if rd_running else f"Dir: {paths.REDIS_DIR}",
                "url": None,
            })

            # 4. phpMyAdmin
            pma_installed = (paths.PMA_DIR / "index.php").exists()
            pma_st = pma.status() if pma_installed else None
            pma_running = bool(pma_st)
            pma_pid = str(pma_st.get("pid")) if (pma_running and pma_st) else "-"
            pma_url = pma_st.get("url", "http://127.0.0.1:8080") if pma_st else "http://127.0.0.1:8080"
            results.append({
                "key": "pma",
                "name": "phpMyAdmin",
                "type": "Admin Tool",
                "installed": pma_installed,
                "running": pma_running,
                "pid": pma_pid,
                "details": f"{pma_url}" if pma_running else "Web port: 8080",
                "url": pma_url if pma_running else None,
            })

            # 5. Mailpit
            mp_installed = mailpit.is_installed()
            mp_st = mailpit.status() if mp_installed else None
            mp_running = bool(mp_st)
            mp_pid = str(mp_st.get("pid")) if (mp_running and mp_st) else "-"
            mp_url = mp_st.get("url", "http://127.0.0.1:8025") if mp_st else "http://127.0.0.1:8025"
            results.append({
                "key": "mailpit",
                "name": "Mailpit",
                "type": "Email Sandbox",
                "installed": mp_installed,
                "running": mp_running,
                "pid": mp_pid,
                "details": f"Web: {mp_url} | SMTP: 127.0.0.1:1025" if mp_running else "Web: 8025 | SMTP: 1025",
                "url": mp_url if mp_running else None,
            })

            # 6. PHP FastCGI Pools

            curr_php = php.get_current_version()
            installed_phps = php.list_installed()
            for v in installed_phps:
                workers = fcgi.status(v)
                is_running = bool(workers)
                is_active_cli = (v == curr_php)
                cli_tag = " [active CLI]" if is_active_cli else ""
                ports_str = ", ".join(str(w.port) for w in workers) if workers else "-"
                results.append({
                    "key": f"php:{v}",
                    "name": f"PHP {v}{cli_tag}",
                    "type": "FastCGI Pool",
                    "installed": True,
                    "running": is_running,
                    "pid": f"{len(workers)} workers" if is_running else "-",
                    "details": f"Ports: {ports_str}" if is_running else f"Binary: {php.php_exe(v)}",
                    "url": None,
                })

            return results

        return await asyncio.to_thread(_get)

    async def _fetch_vhosts_data(self) -> List[Dict[str, Any]]:
        return await asyncio.to_thread(vhost.list_vhosts)

    async def _fetch_php_data(self) -> Tuple[List[str], Optional[str]]:
        def _get() -> Tuple[List[str], Optional[str]]:
            return php.list_installed(), php.get_current_version()
        return await asyncio.to_thread(_get)

    async def _fetch_logs_dict(self) -> Dict[str, Path]:
        return await asyncio.to_thread(logs.get_available_logs)

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
                    f"PHP {vh.get('php', 'default')}",
                    ssl_badge,
                    vh.get("root", "-"),
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
                workers = fcgi.status(v)
                pool_badge = Text(f"RUNNING ({len(workers)})", style="bold green") if workers else Text("STOPPED", style="bold red")
                php_table.add_row(
                    v,
                    cli_badge,
                    pool_badge,
                    str(len(workers)) if workers else "0",
                    str(paths.version_dir(v)),
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
            try:
                services.nginx_start()
            except Exception as e:
                self.log_message(f"[yellow]Nginx notice: {e}[/yellow]")

            # 2. MariaDB
            try:
                services.mariadb_start()
            except Exception as e:
                self.log_message(f"[yellow]MariaDB notice: {e}[/yellow]")

            # 3. Redis
            try:
                if redis_core.is_installed() and not redis_core.status():
                    redis_core.start()
            except Exception as e:
                self.log_message(f"[yellow]Redis notice: {e}[/yellow]")

            # 4. phpMyAdmin
            try:
                if (paths.PMA_DIR / "index.php").exists() and not pma.status():
                    pma.start()
            except Exception as e:
                self.log_message(f"[yellow]phpMyAdmin notice: {e}[/yellow]")

            # 5. Mailpit
            try:
                if mailpit.is_installed() and not mailpit.status():
                    mailpit.start()
            except Exception as e:
                self.log_message(f"[yellow]Mailpit notice: {e}[/yellow]")

            # 6. PHP FastCGI Pools
            cfg = paths.load_config()
            for v in php.list_installed():
                try:
                    fcgi.start(v, php.php_cgi_exe(v), cfg["fcgi_workers_per_version"], cfg["fcgi_base_port"])
                except Exception as e:
                    self.log_message(f"[yellow]PHP {v} pool notice: {e}[/yellow]")

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
            services.nginx_stop()
            services.mariadb_stop()
            redis_core.stop()
            pma.stop()
            mailpit.stop()
            for v in php.list_installed():
                fcgi.stop(v)

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
            # Stop all
            services.nginx_stop()
            services.mariadb_stop()
            redis_core.stop()
            pma.stop()
            mailpit.stop()
            for v in php.list_installed():
                fcgi.stop(v)

            # Start all
            services.nginx_start()
            services.mariadb_start()
            try:
                if redis_core.is_installed():
                    redis_core.start()
            except Exception:
                pass
            try:
                if (paths.PMA_DIR / "index.php").exists():
                    pma.start()
            except Exception:
                pass
            try:
                if mailpit.is_installed():
                    mailpit.start()
            except Exception:
                pass
            cfg = paths.load_config()
            for v in php.list_installed():
                try:
                    fcgi.start(v, php.php_cgi_exe(v), cfg["fcgi_workers_per_version"], cfg["fcgi_base_port"])
                except Exception:
                    pass


        await asyncio.to_thread(_do)
        self.log_message("[bold green]✓ All services restarted.[/bold green]")
        self.notify("All services restarted.", severity="information")
        self._refresh_all_data(full_rebuild=False)

    @work(exclusive=True)
    async def action_reload_nginx(self) -> None:
        """Reload Nginx configuration."""
        self.log_message("[bold blue]Reloading Nginx configuration...[/bold blue]")
        try:
            await asyncio.to_thread(services.nginx_reload)
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
        elif btn_id == "btn-php-pool-start":
            self._handle_php_pool_action("start")
        elif btn_id == "btn-php-pool-stop":
            self._handle_php_pool_action("stop")
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
        installed = php.list_installed()
        active = php.get_current_version()

        def _on_modal_result(res: Optional[dict]) -> None:
            if res:
                self._create_vhost_worker(res["domain"], res["root"], res["php"], res["ssl"])

        self.push_screen(CreateVhostModal(installed, active), _on_modal_result)

    @work(exclusive=True)
    async def _create_vhost_worker(self, domain: str, root: str, php_ver: str, ssl: bool) -> None:
        self.query_one(TabbedContent).active = "tab-logs"
        self.log_message(f"[bold blue]Creating virtual host '{domain}' (PHP {php_ver}, SSL={ssl})...[/bold blue]")
        self.notify(f"Creating vhost {domain}...", severity="information")

        try:
            conf_path = await asyncio.to_thread(vhost.create_vhost, domain, root, php_ver, ssl=ssl, auto_start_pool=True)
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

        msg = f"Are you sure you want to delete virtual host '{domain}'?\n\nThis will remove its Nginx configuration, SSL certificates, and hosts file entry."
        self.push_screen(ConfirmActionModal("Delete Virtual Host", msg, confirm_label="Delete VHost", variant="error"), _on_confirm)

    @work(exclusive=True)
    async def _delete_vhost_worker(self, domain: str) -> None:
        self.log_message(f"[bold yellow]Deleting virtual host '{domain}'...[/bold yellow]")
        self.notify(f"Deleting vhost {domain}...", severity="information")

        try:
            ok = await asyncio.to_thread(vhost.remove_vhost, domain)
            if ok:
                self.log_message(f"[bold green]✓ Virtual host '{domain}' deleted successfully.[/bold green]")
                self.notify(f"Virtual host {domain} deleted.", severity="information")
            else:
                self.log_message(f"[yellow]Virtual host '{domain}' was not found or already removed.[/yellow]")
            self._refresh_all_data(full_rebuild=True)
        except Exception as e:
            self.log_message(f"[bold red]✗ Failed to delete virtual host {domain}: {e}[/bold red]")
            self.notify(f"Delete failed: {e}", severity="error")

    def action_install_php(self) -> None:
        """Open modal dialog to download and install a new PHP runtime."""
        def _on_modal_result(res: Optional[dict]) -> None:
            if res:
                self._install_php_worker(res["version"], res.get("thread_safe", True))

        self.push_screen(InstallPhpModal(), _on_modal_result)

    @work(exclusive=True)
    async def _install_php_worker(self, version_query: str, thread_safe: bool) -> None:
        self.query_one(TabbedContent).active = "tab-logs"
        self.log_message("[bold blue]═══════════════════════════════════════════════════[/bold blue]")
        self.log_message(f"[bold blue]🐘 Resolving PHP release '{version_query}' (TS={thread_safe})...[/bold blue]")
        self.notify(f"Resolving PHP {version_query}...", severity="information")

        try:
            rel = await asyncio.to_thread(php.resolve_release, version_query, thread_safe=thread_safe)
            if not rel:
                raise ValueError(f"Could not find matching Windows PHP build for '{version_query}'")

            self.log_message(f"[bold cyan]Downloading PHP {rel.version} from {rel.zip_url}...[/bold cyan]")
            self.notify(f"Downloading PHP {rel.version}...", severity="information")

            last_reported_mb = -1.0
            last_pct = -1
            def _on_progress(downloaded: int, total: int) -> None:
                nonlocal last_pct, last_reported_mb
                mb_down = downloaded / (1024 * 1024)
                if total > 0:
                    pct = int(downloaded * 100 / total)
                    # Report every 10% or at least every 3 MB
                    if (pct != last_pct and pct % 10 == 0) or (mb_down - last_reported_mb >= 3.0):
                        last_pct = pct
                        last_reported_mb = mb_down
                        mb_tot = total / (1024 * 1024)
                        self.log_message(f"  ↳ Downloaded {mb_down:.1f} MB / {mb_tot:.1f} MB ({pct}%)")
                else:
                    if mb_down - last_reported_mb >= 2.0:
                        last_reported_mb = mb_down
                        self.log_message(f"  ↳ Downloaded {mb_down:.1f} MB")


            zip_path = await asyncio.to_thread(php.download_release, rel, progress_callback=_on_progress)

            self.log_message(f"[bold cyan]Extracting and configuring PHP {rel.version} in ~/.ndev/php/{rel.version}...[/bold cyan]")
            dest = await asyncio.to_thread(php.install, rel.version, zip_path)
            self.log_message(f"[bold green]✓ PHP {rel.version} installed successfully at {dest}[/bold green]")
            self.notify(f"PHP {rel.version} installed!", severity="information")
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

        msg = f"Are you sure you want to uninstall PHP {ver}?\n\nThis will stop its FastCGI worker pool and completely remove ~/.ndev/php/{ver}."
        self.push_screen(ConfirmActionModal("Uninstall PHP Runtime", msg, confirm_label="Uninstall PHP", variant="error"), _on_confirm)

    @work(exclusive=True)
    async def _uninstall_php_worker(self, version: str) -> None:
        self.log_message(f"[bold yellow]Uninstalling PHP {version}...[/bold yellow]")
        self.notify(f"Uninstalling PHP {version}...", severity="information")

        try:
            await asyncio.to_thread(php.uninstall, version)
            self.log_message(f"[bold green]✓ PHP {version} uninstalled successfully.[/bold green]")
            self.notify(f"PHP {version} uninstalled.", severity="information")
            self._refresh_all_data(full_rebuild=True)
        except Exception as e:
            self.log_message(f"[bold red]✗ Failed to uninstall PHP {version}: {e}[/bold red]")
            self.notify(f"Uninstall failed: {e}", severity="error")

    def _handle_php_pool_action(self, action: str) -> None:
        """Start or stop the FastCGI pool for the selected PHP version."""
        php_table = self.query_one("#table-php", DataTable)
        if php_table.cursor_row is None or php_table.row_count == 0:
            self.notify("Please select a PHP version row.", severity="warning")
            return

        row_key = php_table.coordinate_to_cell_key((php_table.cursor_row, 0)).row_key
        ver = str(row_key.value)
        self._selected_service_key = f"php:{ver}"
        self._handle_selected_service_action(action)

    def _handle_selected_service_install(self) -> None:
        """Install or setup the selected service (PMA, Mailpit, Nginx, MariaDB, mkcert, Composer)."""
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
                pma.install()
            elif key == "mailpit":
                mailpit.install()
            elif key == "redis":
                redis_core.install()
            elif key == "nginx":
                setup_core.install_nginx()
            elif key == "mariadb":
                setup_core.install_mariadb()
            elif key == "mkcert":
                setup_core.install_mkcert()
            elif key == "composer":
                setup_core.install_composer()

            elif key.startswith("php:"):
                ver = key.split(":", 1)[1]
                rel = php.resolve_release(ver)
                if rel:
                    zp = php.download_release(rel)
                    php.install(rel.version, zp)

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
            curr = await asyncio.to_thread(php.get_current_version)
            if target_version != curr:
                self.log_message(f"[bold blue]Switching active CLI PHP to {target_version}...[/bold blue]")
                try:
                    await asyncio.to_thread(php.use, target_version)
                    self.log_message(f"[bold green]✓ Active PHP is now {target_version}[/bold green]")
                    self.notify(f"Active PHP set to {target_version}", severity="information")
                    self._refresh_all_data(full_rebuild=True)
                except Exception as e:
                    self.log_message(f"[bold red]✗ Failed to switch PHP: {e}[/bold red]")
                    self.notify(f"PHP switch failed: {e}", severity="error")

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
        tail_lines = logs.read_log_tail(log_path, lines=60)
        if not tail_lines:
            self.log_message("[dim](Log file is empty)[/dim]")
        else:
            for line in tail_lines:
                self.log_message(f"[dim]{line}[/dim]")

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
                if action == "start":
                    services.nginx_start()
                elif action == "stop":
                    services.nginx_stop()
                elif action == "restart":
                    services.nginx_stop()
                    services.nginx_start()

            elif key == "mariadb":
                if action == "start":
                    services.mariadb_start()
                elif action == "stop":
                    services.mariadb_stop()
                elif action == "restart":
                    services.mariadb_stop()
                    services.mariadb_start()

            elif key == "pma":
                if action == "start":
                    pma.start()
                elif action == "stop":
                    pma.stop()
                elif action == "restart":
                    pma.restart()

            elif key == "redis":
                if action == "start":
                    redis_core.start()
                elif action == "stop":
                    redis_core.stop()
                elif action == "restart":
                    redis_core.restart()

            elif key == "mailpit":
                if action == "start":
                    mailpit.start()
                elif action == "stop":
                    mailpit.stop()
                elif action == "restart":
                    mailpit.restart()


            elif key.startswith("php:"):
                ver = key.split(":", 1)[1]
                if action == "start":
                    cfg = paths.load_config()
                    fcgi.start(ver, php.php_cgi_exe(ver), cfg["fcgi_workers_per_version"], cfg["fcgi_base_port"])
                elif action == "stop":
                    fcgi.stop(ver)
                elif action == "restart":
                    fcgi.restart(ver)

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
            st = pma.status()
            url = st["url"] if st else "http://127.0.0.1:8080"
            webbrowser.open(url)
            self.log_message(f"Opening phpMyAdmin at {url}")
        elif key == "mailpit":
            st = mailpit.status()
            url = st["url"] if st else "http://127.0.0.1:8025"
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
            for vh in vhost.list_vhosts():
                if vh["domain"] == domain:
                    proto = "https" if vh.get("ssl") else "http"
                    url = f"{proto}://{domain}"
                    webbrowser.open(url)
                    self.log_message(f"Opening virtual host: {url}")
                    return
            webbrowser.open(f"http://{domain}")

    def _handle_php_set_active(self) -> None:
        """Set the highlighted PHP version as the active CLI version."""
        php_table = self.query_one("#table-php", DataTable)
        if php_table.cursor_row is not None and php_table.row_count > 0:
            row_key = php_table.coordinate_to_cell_key((php_table.cursor_row, 0)).row_key
            ver = str(row_key.value)
            self._switch_php_version(ver)

    @work(exclusive=True)
    async def _switch_php_version(self, target_version: str) -> None:
        curr = await asyncio.to_thread(php.get_current_version)
        if target_version != curr:
            self.log_message(f"[bold blue]Switching active CLI PHP to {target_version}...[/bold blue]")
            try:
                await asyncio.to_thread(php.use, target_version)
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
