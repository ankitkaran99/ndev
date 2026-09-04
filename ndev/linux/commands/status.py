import typer
from rich.console import Console
from rich.table import Table
from ndev.linux.runtime.fpm import get_fpm_status
from ndev.common.logger import logger

console = Console()

def status_cmd(target: str = typer.Argument(None, help="PHP version or service (e.g. 8.4, pma, mailpit) to check status for")):
    """Check status of a PHP-FPM version or service like pma or mailpit."""
    if target and target.lower() in ["pma", "phpmyadmin"]:
        from ndev.linux.runtime.pma import get_pma_status
        status = get_pma_status()
        table = Table(title="phpMyAdmin Service Status")
        table.add_column("Property", style="bold cyan")
        table.add_column("Value")
        
        status_text = "[bold green]Running[/bold green]" if status["running"] else "[bold red]Stopped[/bold red]"
        table.add_row("Service", "phpMyAdmin (pma)")
        table.add_row("Status", status_text)
        table.add_row("PID", str(status["pid"]) if status["pid"] else "N/A")
        table.add_row("Port", str(status["port"]) if status["port"] else "N/A")
        table.add_row("URL", status["url"] if status["url"] else "N/A")
        console.print(table)
        return

    if target and target.lower() in ["mailpit", "mail"]:
        from ndev.linux.runtime.mailpit import get_mailpit_status
        status = get_mailpit_status()
        table = Table(title="Mailpit Service Status")
        table.add_column("Property", style="bold cyan")
        table.add_column("Value")

        status_text = "[bold green]Running[/bold green]" if status["running"] else "[bold red]Stopped[/bold red]"
        table.add_row("Service", "Mailpit")
        table.add_row("Status", status_text)
        table.add_row("PID", str(status["pid"]) if status["pid"] else "N/A")
        table.add_row("SMTP Server", f"127.0.0.1:{status['smtp_port']}")
        table.add_row("Web UI URL", status["url"] if status["url"] else f"http://127.0.0.1:{status['web_port']} (Stopped)")
        console.print(table)
        return

    from ndev.common.utils import get_version_or_prompt
    try:
        version = get_version_or_prompt(target, "PHP version or service to check status")
        if version and version.lower() in ["pma", "phpmyadmin"]:
            from ndev.linux.runtime.pma import get_pma_status
            status = get_pma_status()
            table = Table(title="phpMyAdmin Service Status")
            table.add_column("Property", style="bold cyan")
            table.add_column("Value")
            status_text = "[bold green]Running[/bold green]" if status["running"] else "[bold red]Stopped[/bold red]"
            table.add_row("Service", "phpMyAdmin (pma)")
            table.add_row("Status", status_text)
            table.add_row("PID", str(status["pid"]) if status["pid"] else "N/A")
            table.add_row("Port", str(status["port"]) if status["port"] else "N/A")
            table.add_row("URL", status["url"] if status["url"] else "N/A")
            console.print(table)
            return

        if not version:
            logger.error("No version or service specified.")
            raise typer.Exit(code=1)
        status = get_fpm_status(version)
        
        table = Table(title=f"PHP-FPM {version} Status")
        table.add_column("Property", style="bold cyan")
        table.add_column("Value")
        
        status_text = "[bold green]Running[/bold green]" if status["running"] else "[bold red]Stopped[/bold red]"
        table.add_row("Version", status["version"])
        table.add_row("Status", status_text)
        table.add_row("PID", str(status["pid"]) if status["pid"] else "N/A")
        table.add_row("Socket Path", status["socket"])
        table.add_row("Socket Active", "[green]Yes[/green]" if status["socket_exists"] else "[yellow]No[/yellow]")
        
        console.print(table)
    except Exception as e:
        logger.error(f"Failed to get service status: {e}")
        raise typer.Exit(code=1)
