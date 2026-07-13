import os
import sys
import shutil
import subprocess
import typer
from typing import Optional
from rich.console import Console
from ndev.logger import logger

console = Console()

db_app = typer.Typer(help="Manage MySQL databases and users", invoke_without_command=True)

# Shared options for commands
def execute_sql_mysql(host: str, port: int, user: str, password: Optional[str], sql: str) -> subprocess.CompletedProcess:
    cmd = ["mysql", "-h", host, "-P", str(port), "-u", user, "--batch", "--skip-column-names"]
    if password:
        cmd.append(f"--password={password}")
    return subprocess.run(cmd, input=sql, capture_output=True, text=True)

def confirm_destructive(force: bool, database: str, message: str):
    if force:
        return
    console.print(f"\n[bold yellow]WARNING: {message}[/bold yellow]")
    confirm = typer.prompt("Type the database/username to confirm")
    if confirm != database:
        logger.error("Confirmation failed. Aborting.")
        raise typer.Exit(code=1)

def run_wizard():
    console.print("\n========================================")
    console.print("      NDev MySQL Database Manager Wizard")
    console.print("========================================")
    
    # 1. Connection Details
    host = typer.prompt("Host", default="localhost")
    port = typer.prompt("Port", default=3306, type=int)
    
    admin_user = typer.prompt("Admin username", default="root")
    admin_password = typer.prompt("Admin password", default="", hide_input=True)
    
    # 2. Action
    console.print("\nOperation:")
    console.print("  1) Create Database")
    console.print("  2) Drop Database")
    console.print("  3) Create User")
    console.print("  4) Drop User")
    op_choice = typer.prompt("Choice [1-4]", default=1, type=int)
    
    action_map = {1: "create-db", 2: "drop-db", 3: "create-user", 4: "drop-user"}
    action = action_map.get(op_choice, "create-db")
    
    target_name = typer.prompt("Database/Username")
    if not target_name:
        logger.error("Target name is required.")
        raise typer.Exit(code=1)
        
    # Execute actions
    if action == "create-db":
        owner = typer.prompt("User to grant privileges to (optional)", default="")
        user_host = typer.prompt("Host for mysql user (optional)", default="%") if owner else "%"
        execute_create_db(host, port, admin_user, admin_password, target_name, owner, user_host, "utf8mb4", "utf8mb4_unicode_ci")
    elif action == "drop-db":
        confirm_destructive(False, target_name, f"You are about to DROP database '{target_name}' permanently.")
        execute_drop_db(host, port, admin_user, admin_password, target_name)
    elif action == "create-user":
        new_password = typer.prompt("New password for user", hide_input=True)
        grant_db = typer.prompt("Database to grant privileges to", default=target_name)
        user_host = typer.prompt("Host for mysql user (optional)", default="%")
        execute_create_user(host, port, admin_user, admin_password, target_name, new_password, grant_db, user_host)
    elif action == "drop-user":
        confirm_destructive(False, target_name, f"You are about to DROP user '{target_name}' permanently.")
        execute_drop_user(host, port, admin_user, admin_password, target_name, "%")

def execute_create_db(host: str, port: int, user: str, password: Optional[str], database: str, owner: str, user_host: str, charset: str, collation: str):
    logger.info(f"Creating MySQL database '{database}'...")
    if not shutil.which("mysql"):
        logger.error("mysql CLI tool not found.")
        raise typer.Exit(code=1)
    sql = f"CREATE DATABASE IF NOT EXISTS `{database}` CHARACTER SET {charset} COLLATE {collation};"
    res = execute_sql_mysql(host, port, user, password, sql)
    if res.returncode != 0:
        logger.error(f"MySQL Error:\n{res.stderr}")
        raise typer.Exit(code=1)
        
    if owner:
        logger.info(f"Granting all privileges on {database} to {owner}...")
        grant_sql = f"GRANT ALL PRIVILEGES ON `{database}`.* TO '{owner}'@'{user_host}'; FLUSH PRIVILEGES;"
        res = execute_sql_mysql(host, port, user, password, grant_sql)
        if res.returncode != 0:
            logger.error(f"MySQL Error:\n{res.stderr}")
            raise typer.Exit(code=1)
    console.print(f"[bold green]Database '{database}' created successfully.[/bold green]")

def execute_drop_db(host: str, port: int, user: str, password: Optional[str], database: str):
    logger.info(f"Dropping MySQL database '{database}'...")
    if not shutil.which("mysql"):
        logger.error("mysql CLI tool not found.")
        raise typer.Exit(code=1)
    sql = f"DROP DATABASE IF EXISTS `{database}`;"
    res = execute_sql_mysql(host, port, user, password, sql)
    if res.returncode != 0:
        logger.error(f"MySQL Error:\n{res.stderr}")
        raise typer.Exit(code=1)
    console.print(f"[bold green]Database '{database}' dropped successfully.[/bold green]")

def execute_create_user(host: str, port: int, user: str, password: Optional[str], new_user: str, new_pass: str, grant_db: Optional[str], user_host: str):
    logger.info(f"Creating user '{new_user}' on MySQL...")
    if not shutil.which("mysql"):
        logger.error("mysql CLI tool not found.")
        raise typer.Exit(code=1)
    sql = f"CREATE USER IF NOT EXISTS '{new_user}'@'{user_host}' IDENTIFIED BY '{new_pass}';"
    res = execute_sql_mysql(host, port, user, password, sql)
    if res.returncode != 0:
        logger.error(f"MySQL Error:\n{res.stderr}")
        raise typer.Exit(code=1)
        
    if grant_db:
        logger.info(f"Granting all privileges on {grant_db}.* to {new_user}...")
        grant_sql = f"GRANT ALL PRIVILEGES ON `{grant_db}`.* TO '{new_user}'@'{user_host}'; FLUSH PRIVILEGES;"
        res = execute_sql_mysql(host, port, user, password, grant_sql)
        if res.returncode != 0:
            logger.error(f"MySQL Error:\n{res.stderr}")
            raise typer.Exit(code=1)
    console.print(f"[bold green]User '{new_user}' created successfully.[/bold green]")

def execute_drop_user(host: str, port: int, user: str, password: Optional[str], drop_user: str, user_host: str):
    logger.info(f"Dropping user '{drop_user}' on MySQL...")
    if not shutil.which("mysql"):
        logger.error("mysql CLI tool not found.")
        raise typer.Exit(code=1)
    sql = f"DROP USER IF EXISTS '{drop_user}'@'{user_host}'; FLUSH PRIVILEGES;"
    res = execute_sql_mysql(host, port, user, password, sql)
    if res.returncode != 0:
        logger.error(f"MySQL Error:\n{res.stderr}")
        raise typer.Exit(code=1)
    console.print(f"[bold green]User '{drop_user}' dropped successfully.[/bold green]")

# CLI command entry points
@db_app.callback(invoke_without_command=True)
def db_callback(ctx: typer.Context):
    """Wizard to manage databases & users if run without subcommands."""
    if ctx.invoked_subcommand is None:
        run_wizard()

@db_app.command("create")
@db_app.command("create-db")
def create_db_cmd(
    name: str = typer.Argument(..., help="Database name"),
    host: str = typer.Option("localhost", "--host", "-h", help="Database host"),
    port: int = typer.Option(3306, "--port", "-P", help="Database port"),
    user: str = typer.Option("root", "--user", "-u", help="Admin username"),
    password: Optional[str] = typer.Option(None, "--password", "-p", help="Admin password"),
    owner: Optional[str] = typer.Option(None, "--owner", help="MySQL user to grant privileges on"),
    user_host: str = typer.Option("%", "--user-host", help="MySQL user host (default: %)"),
    charset: str = typer.Option("utf8mb4", "--charset", help="MySQL charset"),
    collation: str = typer.Option("utf8mb4_unicode_ci", "--collation", help="MySQL collation")
):
    """Create a MySQL database."""
    execute_create_db(host, port, user, password, name, owner or "", user_host, charset, collation)

@db_app.command("drop")
@db_app.command("drop-db")
def drop_db_cmd(
    name: str = typer.Argument(..., help="Database name"),
    host: str = typer.Option("localhost", "--host", "-h", help="Database host"),
    port: int = typer.Option(3306, "--port", "-P", help="Database port"),
    user: str = typer.Option("root", "--user", "-u", help="Admin username"),
    password: Optional[str] = typer.Option(None, "--password", "-p", help="Admin password"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt")
):
    """Drop a MySQL database."""
    confirm_destructive(force, name, f"You are about to DROP database '{name}' permanently.")
    execute_drop_db(host, port, user, password, name)

@db_app.command("create-user")
def create_user_cmd(
    username: str = typer.Argument(..., help="Username"),
    new_password: str = typer.Option(..., "--new-password", help="Password for the user"),
    host: str = typer.Option("localhost", "--host", "-h", help="Database host"),
    port: int = typer.Option(3306, "--port", "-P", help="Database port"),
    user: str = typer.Option("root", "--user", "-u", help="Admin username"),
    password: Optional[str] = typer.Option(None, "--password", "-p", help="Admin password"),
    grant_db: Optional[str] = typer.Option(None, "--grant-db", help="Database to grant privileges to"),
    user_host: str = typer.Option("%", "--user-host", help="MySQL user host (default: %)")
):
    """Create a database user."""
    db_to_grant = grant_db if grant_db else username
    execute_create_user(host, port, user, password, username, new_password, db_to_grant, user_host)

@db_app.command("drop-user")
def drop_user_cmd(
    username: str = typer.Argument(..., help="Username"),
    host: str = typer.Option("localhost", "--host", "-h", help="Database host"),
    port: int = typer.Option(3306, "--port", "-P", help="Database port"),
    user: str = typer.Option("root", "--user", "-u", help="Admin username"),
    password: Optional[str] = typer.Option(None, "--password", "-p", help="Admin password"),
    user_host: str = typer.Option("%", "--user-host", help="MySQL user host (default: %)"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt")
):
    """Drop a database user."""
    confirm_destructive(force, username, f"You are about to DROP user '{username}' permanently.")
    execute_drop_user(host, port, user, password, username, user_host)
