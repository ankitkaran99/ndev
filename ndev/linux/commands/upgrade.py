"""
`ndev upgrade` command for Linux stack components.
"""
from __future__ import annotations

from typing import Optional
import typer
from rich.console import Console
from rich.table import Table

from ndev.linux.runtime import upgrade as upgrade_rt

app = typer.Typer(help="Check for and upgrade stack components (Nginx, Mailpit, MariaDB, PMA, mkcert, Composer).")
console = Console()


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    component: Optional[str] = typer.Argument(None, help="Component to upgrade (nginx, mailpit, mariadb, pma, mkcert, composer, or all)"),
    check: bool = typer.Option(False, "--check", "-c", help="Only check for updates without applying upgrades."),
):
    if ctx.invoked_subcommand is not None:
        return

    console.print("\n[bold blue]ndev Linux Stack Component Updates & Upgrades[/bold blue]")

    with console.status("[bold green]Checking component versions...[/bold green]"):
        if component and component.lower() != "all":
            infos = [info for info in upgrade_rt.check_all() if info.name == component.lower() or component.lower() in info.name]
            if not infos:
                console.print(f"[bold red]Unknown component '{component}'. Available: {', '.join(upgrade_rt.COMPONENTS)}[/bold red]")
                raise typer.Exit(1)
        else:
            infos = upgrade_rt.check_all()

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
            ok, msg = upgrade_rt.upgrade_component(target)
        if ok:
            console.print(f"[bold green]✓ {msg}[/bold green]")
        else:
            console.print(f"[bold red]✗ {msg}[/bold red]")

    console.print("\n[bold green]Upgrade process complete![/bold green]")
