import shutil
import subprocess
import typer
from rich.console import Console
from rich.table import Table
from ndev.constants import NDEV_DIR, CONFIG_FILE
from ndev.logger import logger

console = Console()

def doctor_cmd():
    """Run diagnostic checks on the host and sandbox environments."""
    table = Table(title="ndev Doctor Diagnostic Report")
    table.add_column("Check", style="bold cyan")
    table.add_column("Status")
    table.add_column("Details")
    
    bwrap_path = shutil.which("bwrap")
    if bwrap_path:
        try:
            res = subprocess.run(["bwrap", "--version"], capture_output=True, text=True)
            table.add_row("Bubblewrap (bwrap)", "[green]OK[/green]", f"Found at {bwrap_path} ({res.stdout.strip()})")
        except Exception as e:
            table.add_row("Bubblewrap (bwrap)", "[red]FAILED[/red]", f"Found at {bwrap_path} but failed to run: {e}")
    else:
        table.add_row("Bubblewrap (bwrap)", "[red]MISSING[/red]", "bubblewrap is required to build PHP in a sandbox.")
        
    gcc_path = shutil.which("gcc")
    if gcc_path:
        table.add_row("GCC Compiler", "[green]OK[/green]", f"Found at {gcc_path}")
    else:
        table.add_row("GCC Compiler", "[red]MISSING[/red]", "gcc is required to compile PHP.")
        
    make_path = shutil.which("make")
    if make_path:
        table.add_row("Make Utility", "[green]OK[/green]", f"Found at {make_path}")
    else:
        table.add_row("Make Utility", "[red]MISSING[/red]", "make is required to build PHP.")
        
    if NDEV_DIR.exists():
        table.add_row("Layout Directory (~/.ndev)", "[green]OK[/green]", f"Exists at {NDEV_DIR}")
    else:
        table.add_row("Layout Directory (~/.ndev)", "[yellow]WARNING[/yellow]", "Not initialized yet.")
        
    if CONFIG_FILE.exists():
        table.add_row("Configuration File", "[green]OK[/green]", f"Found at {CONFIG_FILE}")
    else:
        table.add_row("Configuration File", "[yellow]WARNING[/yellow]", "Not initialized yet.")
        
    console.print(table)
