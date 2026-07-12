import os
import sys
import shutil
import subprocess
import typer
from typing import Optional
from rich.console import Console
from ndev.logger import logger

console = Console()

db_app = typer.Typer(help="Manage SQL databases and users (MySQL/PostgreSQL)", invoke_without_command=True)

# Shared options for commands
def execute_sql_mysql(host: str, port: int, user: str, password: Optional[str], sql: str) -> subprocess.CompletedProcess:
    cmd = ["mysql", "-h", host, "-P", str(port), "-u", user, "--batch", "--skip-column-names"]
    if password:
        cmd.append(f"--password={password}")
    return subprocess.run(cmd, input=sql, capture_output=True, text=True)

def execute_sql_pgsql(host: str, port: int, user: str, password: Optional[str], sql: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    if password:
        env["PGPASSWORD"] = password
    cmd = ["psql", "-h", host, "-p", str(port), "-U", user, "-d", "postgres", "-v", "ON_ERROR_STOP=1", "--no-align", "--tuples-only", "-q"]
    return subprocess.run(cmd, input=sql, capture_output=True, text=True, env=env)

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
    console.print("      NDev SQL Database Manager Wizard")
    console.print("========================================")
    
    # 1. Select Engine
    console.print("\nDatabase Engine:")
    console.print("  1) MySQL")
    console.print("  2) PostgreSQL")
    engine_choice = typer.prompt("Choice [1-2]", default=1, type=int)
    driver = "mysql" if engine_choice == 1 else "pgsql"
    
    # 2. Connection Details
    host = typer.prompt("Host", default="localhost")
    default_port = 3306 if driver == "mysql" else 5432
    port = typer.prompt("Port", default=default_port, type=int)
    
    default_admin = "root" if driver == "mysql" else "postgres"
    admin_user = typer.prompt("Admin username", default=default_admin)
    admin_password = typer.prompt("Admin password", default="", hide_input=True)
    
    # 3. Action
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
        if driver == "mysql":
            owner = typer.prompt("User to grant privileges to (optional)", default="")
            user_host = typer.prompt("Host for mysql user (optional)", default="%") if owner else "%"
            execute_create_db(driver, host, port, admin_user, admin_password, target_name, owner, user_host, "utf8mb4", "utf8mb4_unicode_ci")
        else:
            owner = typer.prompt("Database owner (optional)", default="")
            execute_create_db(driver, host, port, admin_user, admin_password, target_name, owner, "", "", "")
    elif action == "drop-db":
        confirm_destructive(False, target_name, f"You are about to DROP database '{target_name}' permanently.")
        execute_drop_db(driver, host, port, admin_user, admin_password, target_name)
    elif action == "create-user":
        new_password = typer.prompt("New password for user", hide_input=True)
        grant_db = typer.prompt("Database to grant privileges to", default=target_name)
        user_host = typer.prompt("Host for mysql user (optional)", default="%") if driver == "mysql" else "%"
        execute_create_user(driver, host, port, admin_user, admin_password, target_name, new_password, grant_db, user_host)
    elif action == "drop-user":
        confirm_destructive(False, target_name, f"You are about to DROP user '{target_name}' permanently.")
        execute_drop_user(driver, host, port, admin_user, admin_password, target_name, "%" if driver == "mysql" else "")

def execute_create_db(driver: str, host: str, port: int, user: str, password: Optional[str], database: str, owner: str, user_host: str, charset: str, collation: str):
    logger.info(f"Creating {driver} database '{database}'...")
    if driver == "mysql":
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
    else:
        if not shutil.which("psql"):
            logger.error("psql CLI tool not found.")
            raise typer.Exit(code=1)
        owner_clause = f' OWNER "{owner}"' if owner else ""
        sql = f'CREATE DATABASE "{database}"{owner_clause};'
        res = execute_sql_pgsql(host, port, user, password, sql)
        if res.returncode != 0:
            logger.error(f"PostgreSQL Error:\n{res.stderr}")
            raise typer.Exit(code=1)
        console.print(f"[bold green]Database '{database}' created successfully.[/bold green]")

def execute_drop_db(driver: str, host: str, port: int, user: str, password: Optional[str], database: str):
    logger.info(f"Dropping {driver} database '{database}'...")
    if driver == "mysql":
        if not shutil.which("mysql"):
            logger.error("mysql CLI tool not found.")
            raise typer.Exit(code=1)
        sql = f"DROP DATABASE IF EXISTS `{database}`;"
        res = execute_sql_mysql(host, port, user, password, sql)
        if res.returncode != 0:
            logger.error(f"MySQL Error:\n{res.stderr}")
            raise typer.Exit(code=1)
        console.print(f"[bold green]Database '{database}' dropped successfully.[/bold green]")
    else:
        if not shutil.which("psql"):
            logger.error("psql CLI tool not found.")
            raise typer.Exit(code=1)
        # Terminate active connections first
        term_sql = f"""SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE datname = '{database}' AND pid <> pg_backend_pid();
DROP DATABASE IF EXISTS "{database}";"""
        res = execute_sql_pgsql(host, port, user, password, term_sql)
        if res.returncode != 0:
            logger.error(f"PostgreSQL Error:\n{res.stderr}")
            raise typer.Exit(code=1)
        console.print(f"[bold green]Database '{database}' dropped successfully.[/bold green]")

def execute_create_user(driver: str, host: str, port: int, user: str, password: Optional[str], new_user: str, new_pass: str, grant_db: Optional[str], user_host: str):
    logger.info(f"Creating user '{new_user}' on {driver}...")
    if driver == "mysql":
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
    else:
        if not shutil.which("psql"):
            logger.error("psql CLI tool not found.")
            raise typer.Exit(code=1)
        sql = f"CREATE USER \"{new_user}\" WITH LOGIN PASSWORD '{new_pass}';"
        res = execute_sql_pgsql(host, port, user, password, sql)
        if res.returncode != 0:
            logger.error(f"PostgreSQL Error:\n{res.stderr}")
            raise typer.Exit(code=1)
            
        if grant_db:
            logger.info(f"Granting all privileges on DATABASE {grant_db} to {new_user}...")
            grant_sql = f"GRANT ALL PRIVILEGES ON DATABASE \"{grant_db}\" TO \"{new_user}\";"
            res = execute_sql_pgsql(host, port, user, password, grant_sql)
            if res.returncode != 0:
                logger.error(f"PostgreSQL Error:\n{res.stderr}")
                raise typer.Exit(code=1)
        console.print(f"[bold green]User '{new_user}' created successfully.[/bold green]")

def execute_drop_user(driver: str, host: str, port: int, user: str, password: Optional[str], drop_user: str, user_host: str):
    logger.info(f"Dropping user '{drop_user}' on {driver}...")
    if driver == "mysql":
        if not shutil.which("mysql"):
            logger.error("mysql CLI tool not found.")
            raise typer.Exit(code=1)
        sql = f"DROP USER IF EXISTS '{drop_user}'@'{user_host}'; FLUSH PRIVILEGES;"
        res = execute_sql_mysql(host, port, user, password, sql)
        if res.returncode != 0:
            logger.error(f"MySQL Error:\n{res.stderr}")
            raise typer.Exit(code=1)
        console.print(f"[bold green]User '{drop_user}' dropped successfully.[/bold green]")
    else:
        if not shutil.which("psql"):
            logger.error("psql CLI tool not found.")
            raise typer.Exit(code=1)
            
        # Reassign ownership of database objects to postgres admin first, to allow dropping the user
        transfer_sql = f"""REASSIGN OWNED BY "{drop_user}" TO "{user}";
DROP OWNED BY "{drop_user}";
DROP USER IF EXISTS "{drop_user}";"""
        res = execute_sql_pgsql(host, port, user, password, transfer_sql)
        if res.returncode != 0:
            logger.error(f"PostgreSQL Error:\n{res.stderr}")
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
    driver: str = typer.Option("mysql", "--driver", "-d", help="Database driver: mysql|pgsql"),
    host: str = typer.Option("localhost", "--host", "-h", help="Database host"),
    port: Optional[int] = typer.Option(None, "--port", "-P", help="Database port"),
    user: Optional[str] = typer.Option(None, "--user", "-u", help="Admin username"),
    password: Optional[str] = typer.Option(None, "--password", "-p", help="Admin password"),
    owner: Optional[str] = typer.Option(None, "--owner", help="Owner (PG) or MySQL user to grant privileges on"),
    user_host: str = typer.Option("%", "--user-host", help="MySQL user host (default: %)"),
    charset: str = typer.Option("utf8mb4", "--charset", help="MySQL charset"),
    collation: str = typer.Option("utf8mb4_unicode_ci", "--collation", help="MySQL collation")
):
    """Create a SQL database."""
    actual_port = port if port else (3306 if driver == "mysql" else 5432)
    actual_user = user if user else ("root" if driver == "mysql" else "postgres")
    execute_create_db(driver, host, actual_port, actual_user, password, name, owner or "", user_host, charset, collation)

@db_app.command("drop")
@db_app.command("drop-db")
def drop_db_cmd(
    name: str = typer.Argument(..., help="Database name"),
    driver: str = typer.Option("mysql", "--driver", "-d", help="Database driver: mysql|pgsql"),
    host: str = typer.Option("localhost", "--host", "-h", help="Database host"),
    port: Optional[int] = typer.Option(None, "--port", "-P", help="Database port"),
    user: Optional[str] = typer.Option(None, "--user", "-u", help="Admin username"),
    password: Optional[str] = typer.Option(None, "--password", "-p", help="Admin password"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt")
):
    """Drop a SQL database."""
    actual_port = port if port else (3306 if driver == "mysql" else 5432)
    actual_user = user if user else ("root" if driver == "mysql" else "postgres")
    confirm_destructive(force, name, f"You are about to DROP database '{name}' permanently.")
    execute_drop_db(driver, host, actual_port, actual_user, password, name)

@db_app.command("create-user")
def create_user_cmd(
    username: str = typer.Argument(..., help="Username"),
    new_password: str = typer.Option(..., "--new-password", help="Password for the user"),
    driver: str = typer.Option("mysql", "--driver", "-d", help="Database driver: mysql|pgsql"),
    host: str = typer.Option("localhost", "--host", "-h", help="Database host"),
    port: Optional[int] = typer.Option(None, "--port", "-P", help="Database port"),
    user: Optional[str] = typer.Option(None, "--user", "-u", help="Admin username"),
    password: Optional[str] = typer.Option(None, "--password", "-p", help="Admin password"),
    grant_db: Optional[str] = typer.Option(None, "--grant-db", help="Database to grant privileges to"),
    user_host: str = typer.Option("%", "--user-host", help="MySQL user host (default: %)")
):
    """Create a database user."""
    actual_port = port if port else (3306 if driver == "mysql" else 5432)
    actual_user = user if user else ("root" if driver == "mysql" else "postgres")
    db_to_grant = grant_db if grant_db else username
    execute_create_user(driver, host, actual_port, actual_user, password, username, new_password, db_to_grant, user_host)

@db_app.command("drop-user")
def drop_user_cmd(
    username: str = typer.Argument(..., help="Username"),
    driver: str = typer.Option("mysql", "--driver", "-d", help="Database driver: mysql|pgsql"),
    host: str = typer.Option("localhost", "--host", "-h", help="Database host"),
    port: Optional[int] = typer.Option(None, "--port", "-P", help="Database port"),
    user: Optional[str] = typer.Option(None, "--user", "-u", help="Admin username"),
    password: Optional[str] = typer.Option(None, "--password", "-p", help="Admin password"),
    user_host: str = typer.Option("%", "--user-host", help="MySQL user host (default: %)"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt")
):
    """Drop a database user."""
    actual_port = port if port else (3306 if driver == "mysql" else 5432)
    actual_user = user if user else ("root" if driver == "mysql" else "postgres")
    confirm_destructive(force, username, f"You are about to DROP user '{username}' permanently.")
    execute_drop_user(driver, host, actual_port, actual_user, password, username, user_host)
