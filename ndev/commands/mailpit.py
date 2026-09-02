"""
Mailpit CLI commands for ndev (Linux).
"""
import typer
from rich.console import Console
from rich.table import Table

from ndev.runtime.mailpit import (
    DEFAULT_SMTP_PORT,
    DEFAULT_WEB_PORT,
    get_mailpit_status,
    launch_mailpit,
    restart_mailpit,
    setup_mailpit,
    start_mailpit,
    stop_mailpit,
)

console = Console()
mailpit_app = typer.Typer(
    help="Manage Mailpit local email sandbox & SMTP catcher.",
    no_args_is_help=True,
)


@mailpit_app.command("install")
def mailpit_install():
    """Download and install the prebuilt Mailpit Linux binary."""
    setup_mailpit()


@mailpit_app.command("start")
def mailpit_start(
    smtp_port: int = typer.Option(DEFAULT_SMTP_PORT, "--smtp-port", help="SMTP listening port"),
    web_port: int = typer.Option(DEFAULT_WEB_PORT, "--web-port", help="Web UI listening port"),
):
    """Start Mailpit background service."""
    start_mailpit(smtp_port=smtp_port, web_port=web_port)


@mailpit_app.command("stop")
def mailpit_stop():
    """Stop Mailpit background service."""
    stop_mailpit()


@mailpit_app.command("restart")
def mailpit_restart(
    smtp_port: int = typer.Option(DEFAULT_SMTP_PORT, "--smtp-port", help="SMTP listening port"),
    web_port: int = typer.Option(DEFAULT_WEB_PORT, "--web-port", help="Web UI listening port"),
):
    """Restart Mailpit background service."""
    restart_mailpit(smtp_port=smtp_port, web_port=web_port)


@mailpit_app.command("status")
def mailpit_status():
    """Show status of Mailpit service."""
    st = get_mailpit_status()
    table = Table(title="Mailpit Service Status")
    table.add_column("Property", style="bold cyan")
    table.add_column("Value")

    status_text = "[bold green]Running[/bold green]" if st["running"] else "[bold red]Stopped[/bold red]"
    table.add_row("Service", "Mailpit")
    table.add_row("Status", status_text)
    table.add_row("PID", str(st["pid"]) if st["pid"] else "N/A")
    table.add_row("SMTP Server", f"127.0.0.1:{st['smtp_port']}")
    table.add_row("Web UI URL", st["url"] if st["url"] else f"http://127.0.0.1:{st['web_port']} (Stopped)")
    console.print(table)


@mailpit_app.command("launch")
def mailpit_launch_cmd():
    """Open Mailpit web UI in default browser (starts service if stopped)."""
    launch_mailpit()


@mailpit_app.command("open", hidden=True)
def mailpit_open_alias():
    """Alias for launch."""
    launch_mailpit()
