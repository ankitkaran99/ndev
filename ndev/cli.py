import typer
from ndev.logger import logger
from ndev.config import init_layout

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
from ndev.commands.install import install_cmd
app.command("install")(install_cmd)

from ndev.commands.uninstall import uninstall_cmd
app.command("uninstall")(uninstall_cmd)

from ndev.commands.start import start_cmd
app.command("start")(start_cmd)

from ndev.commands.stop import stop_cmd
app.command("stop")(stop_cmd)

from ndev.commands.restart import restart_cmd
app.command("restart")(restart_cmd)

from ndev.commands.reload import reload_cmd
app.command("reload")(reload_cmd)

from ndev.commands.status import status_cmd
app.command("status")(status_cmd)

from ndev.commands.list import list_cmd
app.command("list")(list_cmd)

from ndev.commands.current import current_cmd
app.command("current")(current_cmd)

from ndev.commands.use import use_cmd
app.command("use")(use_cmd)

from ndev.commands.available import available_cmd
app.command("available")(available_cmd)

from ndev.commands.doctor import doctor_cmd
app.command("doctor")(doctor_cmd)

from ndev.commands.update import update_cmd
app.command("update")(update_cmd)

from ndev.commands.clean import clean_cmd
app.command("clean")(clean_cmd)

from ndev.commands.logs import logs_cmd
app.command("logs")(logs_cmd)

from ndev.commands.grok import grok_cmd
app.command("grok")(grok_cmd)

from ndev.commands.vhost import vhost_cmd
app.command("vhost")(vhost_cmd)

from ndev.commands.ctl import ctl_cmd
app.command("ctl")(ctl_cmd)

from ndev.commands.db import db_app
app.add_typer(db_app, name="db")

@app.command("shell")
def shell():
    """Enter the interactive bubblewrap build environment shell."""
    from ndev.chroot.shell import enter_sandbox_shell
    enter_sandbox_shell()

# Extension command implementations
@ext_app.command("list")
def ext_list(version: str = typer.Argument(..., help="PHP version (e.g. 8.4.12)")):
    """List loaded extensions for a PHP version."""
    from ndev.php.extensions import list_extensions
    try:
        exts = list_extensions(version)
        for ext in exts:
            print(ext)
    except Exception as e:
        logger.error(f"Error listing extensions: {e}")
        raise typer.Exit(code=1)

@ext_app.command("install")
def ext_install(
    ext_name: str = typer.Argument(..., help="Extension name (e.g. redis)"),
    version: str = typer.Argument(..., help="PHP version (e.g. 8.4.12)")
):
    """Install and enable a PECL extension."""
    from ndev.php.extensions import install_extension
    try:
        install_extension(version, ext_name)
    except Exception as e:
        logger.error(f"Error installing extension: {e}")
        raise typer.Exit(code=1)

@ext_app.command("uninstall")
def ext_uninstall(
    ext_name: str = typer.Argument(..., help="Extension name (e.g. redis)"),
    version: str = typer.Argument(..., help="PHP version (e.g. 8.4.12)")
):
    """Disable/uninstall an extension."""
    from ndev.php.extensions import disable_extension
    try:
        disable_extension(version, ext_name)
    except Exception as e:
        logger.error(f"Error uninstalling extension: {e}")
        raise typer.Exit(code=1)

@ext_app.command("enable")
def ext_enable(
    ext_name: str = typer.Argument(..., help="Extension name (e.g. redis)"),
    version: str = typer.Argument(..., help="PHP version (e.g. 8.4.12)")
):
    """Enable an installed extension."""
    from ndev.php.extensions import enable_extension
    try:
        enable_extension(version, ext_name)
    except Exception as e:
        logger.error(f"Error enabling extension: {e}")
        raise typer.Exit(code=1)

@ext_app.command("disable")
def ext_disable(
    ext_name: str = typer.Argument(..., help="Extension name (e.g. redis)"),
    version: str = typer.Argument(..., help="PHP version (e.g. 8.4.12)")
):
    """Disable an extension."""
    from ndev.php.extensions import disable_extension
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
