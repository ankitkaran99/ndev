# ndev

<p align="center">
  <h1 align="center">ndev</h1>
  <p align="center"><strong>Universal, Zero-Config Local PHP & Web Development Stack for Windows and Linux.</strong></p>
</p>

<p align="center">
  <a href="https://pypi.org/project/ndev-stack/"><img src="https://img.shields.io/pypi/v/ndev-stack.svg?color=blue" alt="PyPI Version"></a>
  <a href="https://pypi.org/project/ndev-stack/"><img src="https://img.shields.io/pypi/pyversions/ndev-stack.svg" alt="Python Versions"></a>
  <a href="https://github.com/ankitkaran99/ndev/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License"></a>
</p>

<p align="center">
  <img src="ui.png" alt="ndev Interactive Terminal UI Dashboard" width="90%">
</p>

---

`ndev` is an all-in-one developer environment manager that isolates, orchestrates, and runs multi-version **PHP** runtimes, **Nginx** web server, **MariaDB / MySQL**, **Redis** in-memory store, **phpMyAdmin**, **Mailpit** email sandbox, local **SSL** certificates (`mkcert`), and public HTTP tunnels (`ngrok`) on **Windows 10/11** and **Linux** (Debian/Ubuntu).

---

## Key Features

- **Multi-Version PHP Environment**:
  - **Windows**: Zero-compilation prebuilt official binaries from `windows.php.net` (PHP 5.6 – 8.5, Thread-Safe & Non-Thread-Safe, x64/x86).
  - **Linux**: Sandboxed, unprivileged source compilation with `bubblewrap` and self-healing multiarch library paths.
- **Process Orchestration & FastCGI / FPM**:
  - **Windows**: Multi-process `php-cgi.exe` FastCGI worker pools load-balanced through Nginx `upstream` blocks.
  - **Linux**: Native `php-fpm` worker daemons over isolated Unix sockets (`~/.ndev/run/php<ver>.sock`).
- **Interactive Asynchronous TUI Dashboard (`ndev ui`)**:
  - Full-screen real-time terminal UI built with Textual for live monitoring, batch start/stop/restart, on-the-fly CLI PHP version switching, folder-picker virtual host creator, and live log tailing.
- **Automated Nginx Virtual Hosts (`ndev vhost`)**:
  - Generates Nginx server blocks with custom FastCGI upstreams, HTTP $\rightarrow$ HTTPS redirects, trusted local SSL certificates, and hosts file mappings.
- **In-Memory Store (`ndev redis`)**:
  - Native background Redis server management (`6379`) with interactive `redis-cli` terminal integration.
- **Local Email Sandbox (`ndev mailpit`)**:
  - Embedded zero-dependency SMTP email catcher (`127.0.0.1:1025`) and web inbox (`http://127.0.0.1:8025`).
- **Database & Web Administration (`ndev db` & `ndev pma`)**:
  - Portable MariaDB server (`3306`) with user/database management CLI tools and local phpMyAdmin (`http://127.0.0.1:8080`).
- **Single-Command Stack Upgrader (`ndev upgrade`)**:
  - Automated version scanning and non-destructive upgrading for Nginx, MariaDB, Redis, Mailpit, phpMyAdmin, mkcert, and Composer.

---

## Architecture & Platform Mapping

```text
ndev/
├── main.py                 # Cross-platform dispatcher & runtime detector
├── common/                 # Shared utilities, configs, logger, GitHub API
├── win/                    # Windows native subsystem (FastCGI, Shims, Click CLI, TUI)
│   ├── core/               # php, services, fcgi, vhost, db, redis_core, mailpit, pma, upgrade
│   └── templates/          # Nginx virtual host configuration templates
└── linux/                  # Linux native subsystem (PHP-FPM, Typer CLI, TUI, Chroot)
    ├── php/                # Source resolver, downloader, extensions, builder
    ├── chroot/             # Bubblewrap sandbox manager
    └── runtime/            # FPM, PMA, Mailpit, and systemd daemons
```

| Subsystem | Windows 10/11 (`ndev-win`) | Linux Debian/Ubuntu (`ndev-linux`) |
| :--- | :--- | :--- |
| **PHP Distribution** | Precompiled binaries from `windows.php.net` | Compiles from official source via `bubblewrap` sandbox |
| **Process Model** | Multi-worker `php-cgi.exe` pools via Nginx `upstream` | Native `php-fpm` daemons over Unix domain sockets |
| **CLI & PATH** | Global batch shims in `%USERPROFILE%\.ndev\shims\` | Symlinks in `~/.local/bin/` |
| **Privilege Elevation**| Win32 `ShellExecuteExW` (`runas`) only for `hosts` | `sudo` for Nginx and `/etc/hosts` |
| **Web Server** | Portable Nginx in `%USERPROFILE%\.ndev\nginx\` | System Nginx via `apt install nginx` |
| **Database** | Portable MariaDB in `%USERPROFILE%\.ndev\mariadb\` | System MariaDB via `apt install mariadb-server` |
| **In-Memory Cache** | Portable Redis in `%USERPROFILE%\.ndev\redis\` | System Redis via `apt install redis-server` |
| **Email Sandbox** | Standalone prebuilt Mailpit binary | Standalone prebuilt Mailpit binary |
| **phpMyAdmin** | Served via PHP CLI server (`http://127.0.0.1:8080`) | Served via PHP CLI server (`http://127.0.0.1:8080`) |
| **Local SSL** | Standalone `mkcert.exe` in `shims\` | System `mkcert` package via `apt` |
| **TUI Dashboard** | Asynchronous Textual TUI (`ndev ui`) | Asynchronous Textual TUI (`ndev ui`) |

---

## Directory Structure & Layout

### Windows Layout (`%USERPROFILE%\.ndev`)
```text
%USERPROFILE%\.ndev\
├── certs\                  # Local SSL certificates and cacert.pem CA bundle
├── downloads\              # Cached zip downloads
├── mariadb\                # Portable MariaDB installation & data directory
│   ├── bin\                # mysqld.exe, mysql.exe, mysqldump.exe
│   └── data\               # Database storage
├── nginx\                  # Portable Nginx installation
│   ├── conf\
│   │   ├── nginx.conf      # Main Nginx config (includes ndev-vhosts/*.conf)
│   │   └── ndev-vhosts\    # Virtual host configurations (*.conf)
│   ├── logs\               # Nginx access/error logs per virtual host
│   └── temp\               # FastCGI and proxy client temporary body storage
├── php\
│   └── <version>\          # Extracted PHP binaries (php.exe, php-cgi.exe, php.ini, ext/)
├── pma\                    # Standalone phpMyAdmin installation & config.inc.php
├── redis\                  # Portable Redis server and redis-cli binaries
├── run\                    # Active PID and FastCGI worker state files (JSON)
├── shims\                  # Global batch shims for PATH (php, composer, mysql, redis-cli, mailpit, ndev, etc.)
├── mailpit.db              # Persistent message database for Mailpit
└── config.json             # Global configuration (ports, worker counts)
```

### Linux Layout (`~/.ndev`)
```text
~/.ndev/
├── bin/                    # Standalone binaries (mailpit)
├── builds/                 # Source tarballs and compilation build directories
├── cache/                  # Download and build cache
├── certs/                  # Local SSL certificates and mkcert root CA
├── chroot/                 # Sandboxed development packages and build root
├── downloads/              # Downloaded source archives
├── logs/                   # Service and daemon logs (pma.log, mailpit.log, etc.)
├── php/
│   └── <version>/          # Compiled PHP installations (bin/, sbin/, etc/php.ini, etc/php-fpm.d/)
├── phpmyadmin/             # Standalone phpMyAdmin installation & config.inc.php
├── run/                    # Active PID and Unix domain socket files (*.sock, *.pid)
├── current                 # Symlink pointing to the currently active PHP version directory
├── mailpit.db              # Persistent message database for Mailpit
└── config.toml             # Global build and runtime configuration
```

---

## Installation

### Standard Installation via PyPI

Install `ndev-stack` using `pip` or `pipx`:

```bash
# Using pip
pip install ndev-stack

# Or using pipx (isolated application environment)
pipx install ndev-stack
```

> **Note**: The package is published on PyPI as `ndev-stack`, which provides the global commands `ndev`, `ndev-win`, and `ndev-linux`.

### Development / Source Installation

```bash
git clone https://github.com/ankitkaran99/ndev.git
cd ndev
pip install -e .
```

---

## Quick Start Guide

### Windows 10 / 11

```powershell
# 1. Install ndev-stack
pip install ndev-stack

# 2. Download and configure portable stack (Nginx, MariaDB, Redis, mkcert, Mailpit, Composer)
ndev setup

# 3. Add shims to user PATH (one-time setup for global CLI access)
[Environment]::SetEnvironmentVariable("Path", $env:Path + ";$env:USERPROFILE\.ndev\shims", "User")
$env:Path += ";$env:USERPROFILE\.ndev\shims"

# 4. Verify installation & launch interactive dashboard
ndev doctor
ndev ui
```

### Linux (Debian / Ubuntu)

```bash
# 1. Install system build dependencies
sudo apt update
sudo apt install -y bubblewrap build-essential pkg-config nginx mkcert redis-server default-mysql-client
mkcert -install

# 2. Install ndev-stack
pip install ndev-stack

# 3. Bootstrap runtime environment and shims
ndev setup
export PATH="$HOME/.local/bin:$PATH"

# 4. Verify installation & launch interactive dashboard
ndev doctor
ndev ui
```

---

## Quick Command Reference

| Command | Action |
|---|---|
| `ndev ui` | Launch real-time Textual TUI dashboard (*aliases: `tui`, `dashboard`*) |
| `ndev available` | List available PHP releases (`--archives` for legacy versions) |
| `ndev install <ver>` | Install / compile a PHP version (`8.4`, `8.3`, `7.4`, etc.) |
| `ndev use <ver>` | Switch active CLI PHP version on PATH |
| `ndev current` | Show active CLI PHP version |
| `ndev list` | List installed PHP versions and daemon / worker pool status |
| `ndev start <target>` | Start service or pool (`all`, `nginx`, `mariadb`, `redis`, `pma`, `mailpit`, `<ver>`) |
| `ndev stop <target>` | Stop service or pool (`all`, `nginx`, `mariadb`, `redis`, `pma`, `mailpit`, `<ver>`) |
| `ndev restart <target>`| Restart service or pool (`all`, `nginx`, `mariadb`, `redis`, `pma`, `mailpit`, `<ver>`) |
| `ndev reload nginx` | Reload Nginx configuration without downtime |
| `ndev status` | View real-time service status dashboard |
| `ndev ctl` | Interactive terminal service control menu |
| `ndev vhost` | Interactive virtual host creation wizard with local SSL |
| `ndev vhost-list` | List all configured virtual hosts |
| `ndev vhost-remove` | Remove virtual host and clean up hosts file |
| `ndev db` | Interactive SQL database management wizard |
| `ndev redis` | Manage Redis server or launch interactive `redis-cli` |
| `ndev mailpit` | Manage local email sandbox (`install`, `start`, `stop`, `launch`, `open`) |
| `ndev pma` | Manage phpMyAdmin background service (`http://127.0.0.1:8080`) |
| `ndev ext` | Manage PECL extensions (`list`, `install`, `enable`, `disable`) |
| `ndev grok` | Public HTTP tunneling for local virtual hosts via ngrok |
| `ndev upgrade` | Check for and upgrade stack components (Nginx, MariaDB, Redis, PMA, Mailpit, mkcert, Composer) |
| `ndev upgrade --check` | Check component versions against upstream releases without upgrading |
| `ndev shell` | Interactive developer subshell pre-loaded with PHP/Composer/MySQL/Redis on PATH |
| `ndev doctor` | Run environment diagnostics and health checks |
| `ndev logs` | View and tail service and virtual host logs |
| `ndev clean` | Clean up downloads cache and stale runtime state |

---

## Detailed Usage Guide

### 1. Interactive Terminal UI Dashboard (`ndev ui`)

Launch the modern, responsive Textual TUI dashboard for real-time monitoring and process control:

```bash
ndev ui
# Aliases: ndev tui, ndev dashboard
```

<p align="center">
  <img src="ui.png" alt="ndev TUI Dashboard" width="90%">
</p>

- **Live Status Grid**: Monitor real-time status, PIDs, and active ports for Nginx, MariaDB, Redis, PMA, Mailpit, and PHP worker pools.
- **One-Click Component Setup & Upgrades**: Install uninstalled services (**Redis**, **PMA**, **Mailpit**, **Nginx**, **MariaDB**, **mkcert**, **Composer**) or upgrade existing components with single-click UI actions.
- **Interactive Virtual Host Manager**: Create new virtual hosts (`＋ Create VHost`) with automatic local SSL (`mkcert`) and an integrated folder-picker dialog.
- **PHP Runtime Management**: Install any PHP version (`＋ Install PHP`), uninstall versions (`✖ Uninstall Selected`), or change the active CLI PHP version via dropdown.
- **Batch Actions**: One-click **Start All**, **Stop All**, **Restart All**, and **Reload Nginx** from the persistent sidebar.
- **Integrated Log Tail Viewer**: Select and inspect live logs for Nginx, MariaDB, Redis, PHP, and Virtual Hosts.

---

### 2. PHP Version Management

```bash
# List available PHP releases (from php.net / windows.php.net)
ndev available
ndev available --archives    # include legacy releases (5.6 - 7.3)

# Install a PHP version (prebuilt on Windows, source-compiled on Linux)
ndev install 8.4

# List locally installed PHP versions and daemon/pool status
ndev list

# Switch globally active CLI PHP version
ndev use 8.4

# Show current active CLI PHP version
ndev current

# Uninstall a PHP version
ndev uninstall 7.4
```

---

### 3. Service & Process Management

```bash
# Start / Stop / Restart a PHP pool or individual service
ndev start 8.4
ndev stop 8.4
ndev restart 8.4

# Control core services
ndev start nginx
ndev start mariadb
ndev start redis
ndev start pma
ndev start mailpit

# Batch operations
ndev start all
ndev stop all
ndev restart all

# Reload Nginx configuration without downtime
ndev reload nginx

# View service status
ndev status
```

---

### 4. Virtual Host Management (`vhost`)

Create and manage local Nginx sites mapped to `127.0.0.1`:

```bash
# Interactive wizard (auto-prompts for domain, document root, PHP version, and SSL)
ndev vhost

# Create a standard HTTP virtual host
ndev vhost --domain project.local --root /path/to/project --php 8.4

# Create an HTTPS virtual host with trusted local SSL certificates (mkcert)
ndev vhost --domain project.local --root /path/to/project --php 8.4 --ssl

# List all configured virtual hosts
ndev vhost-list

# Remove a virtual host (removes Nginx conf and cleans hosts file)
ndev vhost-remove --domain project.local
```

---

### 5. Redis In-Memory Store (`redis`)

Manage the local Redis server and launch the interactive `redis-cli`:

> [!TIP]
> **Redis Connection Defaults**:
> * **Host**: `127.0.0.1` or `localhost`
> * **Port**: `6379`
> * **Password**: None (default)

```bash
# Start Redis server
ndev redis start
ndev start redis

# Check Redis status
ndev redis status
ndev status redis

# Open interactive redis-cli terminal
ndev redis cli

# Stop or restart Redis server
ndev redis stop
ndev redis restart
```

#### Laravel / Symfony / WordPress Configuration:
```env
REDIS_HOST=127.0.0.1
REDIS_PASSWORD=null
REDIS_PORT=6379
```

---

### 6. SQL Database Manager (`db`) & phpMyAdmin (`pma`)

Manage MySQL/MariaDB databases, users, and web administration:

> [!TIP]
> **Default MariaDB / MySQL Credentials**:
> * **Host**: `127.0.0.1` or `localhost`
> * **Port**: `3306`
> * **Username**: `root`
> * **Password**: `root` (Windows) / system auth (Linux)
> * **phpMyAdmin URL**: [http://127.0.0.1:8080](http://127.0.0.1:8080)

```bash
# Launch interactive database management wizard
ndev db

# Create database and user
ndev db create-db mydb --owner myuser
ndev db create-user myuser --new-password secret --grant-db mydb

# Export & import database dumps
ndev db export-db mydb -o backup.sql
ndev db import-db mydb backup.sql

# Start phpMyAdmin web UI
ndev start pma
ndev pma
```

---

### 7. Local Email Sandbox (`mailpit`)

Catch every outgoing e-mail your local applications send using [Mailpit](https://github.com/axllent/mailpit):

> [!TIP]
> **SMTP & Web UI Defaults**:
> * **SMTP Server**: `127.0.0.1:1025`
> * **Web Inbox**: [http://127.0.0.1:8025](http://127.0.0.1:8025)
> * No authentication required — all emails are safely intercepted locally.

```bash
# Start Mailpit (auto-installs if not present)
ndev mailpit start
ndev start mailpit

# Open Web UI in default browser
ndev mailpit launch
ndev mailpit open

# Stop or restart Mailpit
ndev mailpit stop
ndev mailpit restart
```

#### Configuring Mailpit in your Project:

**Laravel (`.env`):**
```env
MAIL_MAILER=smtp
MAIL_HOST=127.0.0.1
MAIL_PORT=1025
MAIL_USERNAME=null
MAIL_PASSWORD=null
MAIL_ENCRYPTION=null
```

**PHP (`php.ini`):**
```ini
[mail function]
SMTP = 127.0.0.1
smtp_port = 1025
```

---

### 8. Stack Upgrade Engine (`upgrade`)

Scan for and upgrade stack components (Nginx, MariaDB, Redis, PMA, Mailpit, mkcert, Composer) safely against latest upstream releases:

```bash
# Check for available updates across all stack components
ndev upgrade --check

# Upgrade all components to latest stable releases
ndev upgrade

# Upgrade a specific component
ndev upgrade redis
ndev upgrade mailpit
ndev upgrade pma
```

---

### 9. Diagnostics & Developer Tools

```bash
# Run full environment health check
ndev doctor

# Launch pre-configured developer subshell
ndev shell

# Tail live logs for services or virtual hosts
ndev logs
ndev logs 8.4
ndev logs nginx

# Tunnel local virtual host to public web via ngrok
ndev grok

# Clean download cache and temporary files
ndev clean
```

---

## Configuration Files

### Windows
* **Global Settings**: `%USERPROFILE%\.ndev\config.json`
* **PHP Configuration**: `%USERPROFILE%\.ndev\php\<version>\php.ini`
* **Nginx Main Config**: `%USERPROFILE%\.ndev\nginx\conf\nginx.conf`
* **Virtual Host Configs**: `%USERPROFILE%\.ndev\nginx\conf\ndev-vhosts\*.conf`
* **FastCGI Worker Pools**: Base port `13000` with 4 workers per PHP version (customizable in `config.json`).

### Linux
* **Global Settings**: `~/.ndev/config.toml`
* **PHP Configuration**: `~/.ndev/php/<version>/etc/php.ini`
* **PHP Extensions**: `~/.ndev/php/<version>/etc/conf.d/<ext>.ini`
* **PHP-FPM Pool Config**: `~/.ndev/php/<version>/etc/php-fpm.d/www.conf`

---

## License

MIT License. See [LICENSE](LICENSE) for more details.
