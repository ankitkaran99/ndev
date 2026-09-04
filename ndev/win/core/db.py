"""
MariaDB database/user management, shelling out to mysql.exe and mysqldump.exe.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Optional

from . import paths

DEFAULT_ROOT_PASSWORD = "root"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 3306


def _mysql_exe() -> str:
    exe = paths.MARIADB_DIR / "bin" / "mysql.exe"
    if exe.exists():
        return str(exe)
    system_exe = shutil.which("mysql") or shutil.which("mysql.exe")
    if system_exe:
        return system_exe
    raise FileNotFoundError("MariaDB/MySQL client isn't installed -- run `ndev setup` first")


def _mysqldump_exe() -> str:
    exe = paths.MARIADB_DIR / "bin" / "mysqldump.exe"
    if exe.exists():
        return str(exe)
    system_exe = shutil.which("mysqldump") or shutil.which("mysqldump.exe")
    if system_exe:
        return system_exe
    raise FileNotFoundError("mysqldump isn't installed -- run `ndev setup` first")


def run_sql(
    sql: str,
    root_password: str = DEFAULT_ROOT_PASSWORD,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    user: str = "root",
) -> str:
    cmd = [
        _mysql_exe(),
        "-h", host,
        "-P", str(port),
        "-u", user,
        "--connect-timeout=5",
        f"--password={root_password}" if root_password else "",
        "--batch",
        "--skip-column-names",
        "-e", sql,
    ]
    cmd = [arg for arg in cmd if arg]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        err = result.stderr.strip()
        if "Access denied for user" in err:
            raise RuntimeError(f"Authentication failed: Access denied for '{user}'. Please verify your database password.")
        raise RuntimeError(f"MySQL error: {err}")
    return result.stdout


def test_connection(
    root_password: str = DEFAULT_ROOT_PASSWORD,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    user: str = "root",
) -> tuple[bool, str]:
    """Test connection to MariaDB and return (success, error_message)."""
    try:
        run_sql("SELECT 1;", root_password=root_password, host=host, port=port, user=user)
        return True, ""
    except Exception as e:
        return False, str(e)


def _escape_sql_ident(ident: str) -> str:
    """Safely escape a SQL identifier using backticks."""
    clean = ident.replace("`", "``")
    return f"`{clean}`"


def _escape_sql_string(val: str) -> str:
    """Safely escape a SQL string literal."""
    return val.replace("\\", "\\\\").replace("'", "''")


def create_db(
    name: str,
    owner: str = "",
    user_host: str = "%",
    charset: str = "utf8mb4",
    collation: str = "utf8mb4_unicode_ci",
    root_password: str = DEFAULT_ROOT_PASSWORD,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> None:
    db_ident = _escape_sql_ident(name)
    sql = f"CREATE DATABASE IF NOT EXISTS {db_ident} CHARACTER SET {charset} COLLATE {collation};"
    if owner:
        owner_str = _escape_sql_string(owner)
        host_str = _escape_sql_string(user_host)
        sql += f" GRANT ALL PRIVILEGES ON {db_ident}.* TO '{owner_str}'@'{host_str}'; FLUSH PRIVILEGES;"
    run_sql(sql, root_password=root_password, host=host, port=port)


def drop_db(
    name: str,
    root_password: str = DEFAULT_ROOT_PASSWORD,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> None:
    db_ident = _escape_sql_ident(name)
    run_sql(f"DROP DATABASE IF EXISTS {db_ident};", root_password=root_password, host=host, port=port)


def export_db(
    name: str,
    output_path: Optional[str | Path] = None,
    root_password: str = DEFAULT_ROOT_PASSWORD,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    user: str = "root",
    quick: bool = True,
    single_transaction: bool = True,
    routines: bool = True,
    triggers: bool = True,
) -> str:
    cmd = [
        _mysqldump_exe(),
        "-h", host,
        "-P", str(port),
        "-u", user,
    ]
    if root_password:
        cmd.append(f"--password={root_password}")
    if quick:
        cmd.append("--quick")
    if single_transaction:
        cmd.append("--single-transaction")
    if routines:
        cmd.append("--routines")
    if triggers:
        cmd.append("--triggers")
    cmd.append(name)

    if output_path:
        out = Path(output_path).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            res = subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"mysqldump error: {res.stderr.strip()}")
        return str(out)
    else:
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"mysqldump error: {res.stderr.strip()}")
        return res.stdout


def list_databases(
    root_password: str = DEFAULT_ROOT_PASSWORD,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> list[str]:
    out = run_sql("SHOW DATABASES;", root_password=root_password, host=host, port=port)
    lines = [line.strip() for line in out.strip().splitlines() if line.strip()]
    system_dbs = {"information_schema", "mysql", "performance_schema", "sys"}
    return [db for db in lines if db.lower() not in system_dbs]


def create_user(
    username: str,
    password: str,
    grant_db: Optional[str] = None,
    user_host: str = "localhost",
    root_password: str = DEFAULT_ROOT_PASSWORD,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> None:
    u_str = _escape_sql_string(username)
    p_str = _escape_sql_string(password)
    h_str = _escape_sql_string(user_host)
    
    hosts_to_create = [h_str]
    if user_host in ("localhost", "127.0.0.1"):
        hosts_to_create = ["localhost", "127.0.0.1", "%"]

    sql_parts = []
    for h in hosts_to_create:
        sql_parts.append(f"CREATE USER IF NOT EXISTS '{u_str}'@'{h}' IDENTIFIED BY '{p_str}';")
        if grant_db:
            db_ident = _escape_sql_ident(grant_db)
            sql_parts.append(f"GRANT ALL PRIVILEGES ON {db_ident}.* TO '{u_str}'@'{h}';")
    sql_parts.append("FLUSH PRIVILEGES;")
    run_sql(" ".join(sql_parts), root_password=root_password, host=host, port=port)


def drop_user(
    username: str,
    user_host: str = "localhost",
    root_password: str = DEFAULT_ROOT_PASSWORD,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> None:
    u_str = _escape_sql_string(username)
    h_str = _escape_sql_string(user_host)
    hosts_to_drop = [h_str]
    if user_host in ("localhost", "127.0.0.1"):
        hosts_to_drop = ["localhost", "127.0.0.1", "%"]

    sql_parts = []
    for h in hosts_to_drop:
        sql_parts.append(f"DROP USER IF EXISTS '{u_str}'@'{h}';")
    sql_parts.append("FLUSH PRIVILEGES;")
    run_sql(" ".join(sql_parts), root_password=root_password, host=host, port=port)


def list_users(
    root_password: str = DEFAULT_ROOT_PASSWORD,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> list[str]:
    out = run_sql("SELECT CONCAT(User, '@', Host) FROM mysql.user;", root_password=root_password, host=host, port=port)
    lines = [line.strip() for line in out.strip().splitlines() if line.strip()]
    system_users = {"root@localhost", "root@127.0.0.1", "root@::1", "mariadb.sys@localhost", "mysql@localhost"}
    return [u for u in lines if u.lower() not in system_users]


def import_db(
    name: str,
    sql_file_path: str | Path,
    root_password: str = DEFAULT_ROOT_PASSWORD,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    user: str = "root",
) -> None:
    """Import a SQL dump file into a database."""
    file_path = Path(sql_file_path).resolve()
    if not file_path.exists():
        raise FileNotFoundError(f"SQL file does not exist: {file_path}")

    # Ensure database exists before import
    create_db(name, root_password=root_password, host=host, port=port)

    cmd = [
        _mysql_exe(),
        "-h", host,
        "-P", str(port),
        "-u", user,
        "--connect-timeout=5",
    ]
    if root_password:
        cmd.append(f"--password={root_password}")
    cmd.append(name)

    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        res = subprocess.run(cmd, stdin=f, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"MySQL import error: {res.stderr.strip()}")
