import typer
from ndev.common.logger import logger
from ndev.common.config import init_layout

app = typer.Typer(
    help="ndev: Compile, install, and manage isolated PHP-FPM versions on Debian.",
    no_args_is_help=True
)

ext_app = typer.Typer(
    help="Manage PHP extensions for installed versions.",
    no_args_is_help=True
)
app.add_typer(ext_app, name="ext")

# Register commands
from ndev.linux.commands.install import install_cmd
app.command("install")(install_cmd)

from ndev.linux.commands.uninstall import uninstall_cmd
app.command("uninstall")(uninstall_cmd)

from ndev.linux.commands.start import start_cmd
app.command("start")(start_cmd)

from ndev.linux.commands.stop import stop_cmd
app.command("stop")(stop_cmd)

from ndev.linux.commands.restart import restart_cmd
app.command("restart")(restart_cmd)

from ndev.linux.commands.reload import reload_cmd
app.command("reload")(reload_cmd)

from ndev.linux.commands.status import status_cmd
app.command("status")(status_cmd)

from ndev.linux.commands.list import list_cmd
app.command("list")(list_cmd)

from ndev.linux.commands.current import current_cmd
app.command("current")(current_cmd)

from ndev.linux.commands.use import use_cmd
app.command("use")(use_cmd)

from ndev.linux.commands.available import available_cmd
app.command("available")(available_cmd)

from ndev.linux.commands.doctor import doctor_cmd
app.command("doctor")(doctor_cmd)

from ndev.linux.commands.update import update_cmd
app.command("update")(update_cmd)

from ndev.linux.commands.clean import clean_cmd
app.command("clean")(clean_cmd)

from ndev.linux.commands.logs import logs_cmd
app.command("logs")(logs_cmd)

from ndev.linux.commands.grok import grok_cmd
app.command("grok")(grok_cmd)

from ndev.linux.commands.vhost import vhost_cmd
app.command("vhost")(vhost_cmd)

from ndev.linux.commands.ctl import ctl_cmd
app.command("ctl")(ctl_cmd)

from ndev.linux.commands.setup import setup_cmd
app.command("setup")(setup_cmd)

from ndev.linux.commands.upgrade import app as upgrade_app
app.add_typer(upgrade_app, name="upgrade")

from ndev.linux.commands.db import db_app
app.add_typer(db_app, name="db")

from ndev.linux.commands.mailpit import mailpit_app
app.add_typer(mailpit_app, name="mailpit")

from ndev.linux.commands.modules import module_app
app.add_typer(module_app, name="module")

from ndev.linux.commands.postgres import postgres_app
app.add_typer(postgres_app, name="postgres")

from ndev.linux.commands.mongodb import mongodb_app
app.add_typer(mongodb_app, name="mongodb")

@app.command("ui")
def ui_cmd():
    """Launch the interactive Textual TUI dashboard."""
    from ndev.tui import run_dashboard
    run_dashboard()

@app.command("tui", hidden=True)
def tui_cmd():
    """Alias for ui."""
    from ndev.tui import run_dashboard
    run_dashboard()

@app.command("dashboard", hidden=True)
def dashboard_cmd():
    """Alias for ui."""
    from ndev.tui import run_dashboard
    run_dashboard()

@app.command("shell")
def shell():
    """Enter the interactive bubblewrap build environment shell."""
    from ndev.linux.chroot.shell import enter_sandbox_shell
    enter_sandbox_shell()

# Extension command implementations
@ext_app.command("list")
def ext_list(version: str = typer.Argument(None, help="PHP version (e.g. 8.4.12)")):
    """List loaded extensions for a PHP version."""
    from ndev.linux.php.extensions import list_extensions
    if not version:
        from ndev.common.utils import get_version_or_prompt
        version = get_version_or_prompt(version, "PHP version")
    if not version:
        logger.error("PHP version is required.")
        raise typer.Exit(code=1)
    try:
        exts = list_extensions(version)
        for ext in exts:
            print(ext)
    except Exception as e:
        logger.error(f"Error listing extensions: {e}")
        raise typer.Exit(code=1)

@ext_app.command("install")
def ext_install(
    ext_name: str = typer.Argument(None, help="Extension name (e.g. redis)"),
    version: str = typer.Argument(None, help="PHP version (e.g. 8.4.12)"),
    show_logs: bool = typer.Option(
        False,
        "--show-logs",
        "-s",
        help="Show verbose compilation and installation logs"
    )
):
    """Install and enable a PECL extension."""
    from ndev.linux.php.extensions import install_extension
    if not ext_name:
        ext_name = typer.prompt("Extension name (e.g. redis)").strip()
    if not ext_name:
        logger.error("Extension name is required.")
        raise typer.Exit(code=1)
    if not version:
        from ndev.common.utils import get_version_or_prompt
        version = get_version_or_prompt(version, "PHP version")
    if not version:
        logger.error("PHP version is required.")
        raise typer.Exit(code=1)
    try:
        install_extension(version, ext_name, show_logs=show_logs)
    except Exception as e:
        logger.error(f"Error installing extension: {e}")
        raise typer.Exit(code=1)

@ext_app.command("uninstall")
def ext_uninstall(
    ext_name: str = typer.Argument(None, help="Extension name (e.g. redis)"),
    version: str = typer.Argument(None, help="PHP version (e.g. 8.4.12)")
):
    """Disable/uninstall an extension."""
    from ndev.linux.php.extensions import disable_extension
    if not ext_name:
        ext_name = typer.prompt("Extension name (e.g. redis)").strip()
    if not ext_name:
        logger.error("Extension name is required.")
        raise typer.Exit(code=1)
    if not version:
        from ndev.common.utils import get_version_or_prompt
        version = get_version_or_prompt(version, "PHP version")
    if not version:
        logger.error("PHP version is required.")
        raise typer.Exit(code=1)
    try:
        disable_extension(version, ext_name)
    except Exception as e:
        logger.error(f"Error uninstalling extension: {e}")
        raise typer.Exit(code=1)

@ext_app.command("enable")
def ext_enable(
    ext_name: str = typer.Argument(None, help="Extension name (e.g. redis)"),
    version: str = typer.Argument(None, help="PHP version (e.g. 8.4.12)")
):
    """Enable an installed extension."""
    from ndev.linux.php.extensions import enable_extension
    if not ext_name:
        ext_name = typer.prompt("Extension name (e.g. redis)").strip()
    if not ext_name:
        logger.error("Extension name is required.")
        raise typer.Exit(code=1)
    if not version:
        from ndev.common.utils import get_version_or_prompt
        version = get_version_or_prompt(version, "PHP version")
    if not version:
        logger.error("PHP version is required.")
        raise typer.Exit(code=1)
    try:
        enable_extension(version, ext_name)
    except Exception as e:
        logger.error(f"Error enabling extension: {e}")
        raise typer.Exit(code=1)

@ext_app.command("disable")
def ext_disable(
    ext_name: str = typer.Argument(None, help="Extension name (e.g. redis)"),
    version: str = typer.Argument(None, help="PHP version (e.g. 8.4.12)")
):
    """Disable an extension."""
    from ndev.linux.php.extensions import disable_extension
    if not ext_name:
        ext_name = typer.prompt("Extension name (e.g. redis)").strip()
    if not ext_name:
        logger.error("Extension name is required.")
        raise typer.Exit(code=1)
    if not version:
        from ndev.common.utils import get_version_or_prompt
        version = get_version_or_prompt(version, "PHP version")
    if not version:
        logger.error("PHP version is required.")
        raise typer.Exit(code=1)
    try:
        disable_extension(version, ext_name)
    except Exception as e:
        logger.error(f"Error disabling extension: {e}")
        raise typer.Exit(code=1)


@app.callback()
def main():
    # Initialize the folder structure in ~/.ndev
    init_layout()

if __name__ == "__main__":
    app()
