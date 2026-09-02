# ndev

`ndev` is a powerful, non-root developer tool suite to compile, install, and manage isolated PHP-FPM runtimes, custom PECL extensions, MySQL/MariaDB databases, Nginx virtual hosts, trusted local SSL certificates, Mailpit email sandbox, and public HTTP tunneling on **Debian/Ubuntu-based Linux systems**.

It allows you to run multiple isolated PHP-FPM versions simultaneously without interfering with system-wide packages or requiring system-level modifications.

---

## Key Features

- **Sandboxed PHP Compilation**: Automatically builds and isolates any PHP release (`5.6`, `7.4`, `8.0`, `8.1`, `8.2`, `8.3`, `8.4`, `8.5`) from official source inside an unprivileged `bubblewrap` sandbox with custom, self-healing multiarch compile paths.
- **Root-Free Development Packages**: Automatically downloads, relocates, and resolves required system development packages (`libsqlite3-dev`, `libonig-dev`, `libxml2-dev`, etc.) fully in user space.
- **Interactive Terminal UI Dashboard (`ui`)**: Modern, asynchronous Textual TUI dashboard for real-time stack monitoring, live auto-refresh, quick batch actions (Start/Stop/Restart All), active CLI PHP switching, integrated log tailing, and virtual host launching.
- **Interactive Control Menu (`ctl`)**: Unified interactive CLI service selector to inspect and manage Nginx, MariaDB, phpMyAdmin, and custom `ndev` compiled FPM instances.
- **Nginx Virtual Host Manager (`vhost`)**: Automated Nginx server blocks with custom PHP-FPM sockets, canonical HTTP $\rightarrow$ HTTPS redirects, trusted local SSL certificate generation (`mkcert`), and `/etc/hosts` mapping.
- **SQL Database Manager (`db`)**: Interactive wizard and CLI suite to create/drop databases, manage users, grant permissions, and export SQL dumps (`mysqldump`).
- **PECL Extension Manager (`ext`)**: Compiles and installs custom PECL extensions (Redis, Xdebug, etc.) and enables or disables them per PHP version.
- **Local Email Sandbox (`mailpit`)**: Zero-dependency local SMTP email catcher & modern web UI (`http://127.0.0.1:8025`) using prebuilt binaries.
- **phpMyAdmin Background Service (`pma`)**: One-command background phpMyAdmin service management served locally over `http://127.0.0.1:8080`.
- **Public HTTP Tunneling (`grok`)**: Interactive ngrok tunnel launcher to proxy local virtual hosts over the web with automatic Host header rewriting.
- **Interactive Sandbox Shell (`shell`)**: Launch an interactive shell inside the bubblewrap build environment.
- **Automated Stack Setup (`setup`)**: Automatic system package installer for MariaDB, Nginx, and Composer (installs Composer and `ndev` shims to `~/.local/bin/`).

---

## Differences Between Linux (`ndev`) and Windows (`ndev-win`)

| Subsystem | Linux Original (`ndev`) | Windows Counterpart (`ndev-win`) |
| :--- | :--- | :--- |
| **PHP Distribution** | Compiles PHP from official source using `bubblewrap` sandbox and `gcc`/`make` | Downloads official precompiled Windows builds from `windows.php.net` (NTS & TS, x64 & x86) |
| **Process Model** | Native `php-fpm` daemon with Unix domain sockets (`~/.ndev/run/php<ver>.sock`) | Multi-process worker pool of `php-cgi.exe` instances over deterministic TCP ports (`13000+`), balanced via Nginx `upstream` |
| **CLI & PATH Switching** | Linux symlinks in `~/.local/bin/` (`php`, `composer`, `ndev`) pointing to `~/.ndev/current/` | Windows batch shims in `%USERPROFILE%\.ndev\shims\` (`php.bat`, `composer.bat`, `ndev.bat`) |
| **Privilege Elevation** | `sudo` for Nginx and `/etc/hosts` changes | Scoped Windows UAC elevation via Win32 `ShellExecuteExW` (`runas`) only when updating `hosts` file |
| **Web Server** | Host system package installed via `apt install nginx` (`/etc/nginx/`) | Portable standalone Nginx zip extracted to `%USERPROFILE%\.ndev\nginx\` |
| **Database** | Host system package installed via `apt install mariadb-server` | Portable MariaDB zip extracted to `%USERPROFILE%\.ndev\mariadb\` initialized via `mariadb-install-db.exe` |
| **PECL Extensions** | Source compilation (`phpize`, `./configure`, `make`) within build sandbox | Precompiled official PECL `.dll` downloads matching PHP version, VS compiler (`vs16`, `vs17`), and thread safety |
| **Email Sandbox** | Prebuilt Linux Mailpit binary in `~/.ndev/bin/mailpit` | Prebuilt Windows Mailpit binary in `%USERPROFILE%\.ndev\shims\mailpit.exe` |
| **phpMyAdmin** | Served via PHP's built-in web server (`php -S 127.0.0.1:8080`) | Served via PHP's built-in web server (`php.exe -S 127.0.0.1:8080`) |
| **Local SSL** | `mkcert` package via `apt` (`~/.ndev/certs/`) | Portable `mkcert.exe` downloaded into `%USERPROFILE%\.ndev\shims\` |
| **TUI Dashboard** | Asynchronous Textual TUI (`ndev ui`) with live auto-refresh | Asynchronous Textual TUI (`ndev ui`) with live auto-refresh |

---

## Directory Structure & Layout

All runtimes, templates, and service configurations are organized under `~/.ndev`:

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

## Quick Start & Installation

### 1. Prerequisites (APT)

Ensure the host system has the base build dependencies installed:

```bash
sudo apt update
sudo apt install -y bubblewrap build-essential pkg-config
```

#### Optional Component Packages:
```bash
# Web server & local SSL
sudo apt install -y nginx mkcert
mkcert -install

# Database client
sudo apt install -y default-mysql-client
```

### 2. Clone & Install ndev

```bash
# 1. Clone repository
git clone https://github.com/ankitkaran99/ndev.git
cd ndev

# 2. Create virtual environment and install in editable mode
python3 -m venv .venv
.venv/bin/pip install -e .

# 3. Setup system components and local shims
.venv/bin/ndev setup
```

Add `~/.local/bin` to your `PATH` if not already present:
```bash
export PATH="$HOME/.local/bin:$PATH"
```

---

## Usage Guide

### PHP Version Management

```bash
# List available PHP versions from php.net
ndev available

# Compile and install a PHP version from source (e.g. 8.4, 8.3, 7.4)
ndev install 8.4

# List locally installed PHP versions and FPM daemon status
ndev list

# Switch globally active CLI PHP version
ndev use 8.4

# Show current active CLI PHP version
ndev current

# Check for newer minor/patch releases
ndev update

# Uninstall a PHP version
ndev uninstall 7.4
```

---

### Process & Service Management

```bash
# Start / Stop / Restart a PHP-FPM pool or service
ndev start 8.4
ndev stop 8.4
ndev restart 8.4

# Control Nginx, MariaDB, phpMyAdmin, or Mailpit
ndev start pma
ndev start mailpit

# Reload PHP-FPM configuration
ndev reload 8.4

# View service status
ndev status
ndev status 8.4
ndev status pma
ndev status mailpit
```

---

### Interactive Terminal UI Dashboard (`ui` / `dashboard`)

Launch the modern, responsive Textual TUI dashboard for real-time monitoring and process control:

```bash
ndev ui
# Aliases: ndev tui, ndev dashboard
```

* **Live Status Dashboard**: Real-time health, PIDs, Unix sockets, and listening ports for Nginx, MariaDB, phpMyAdmin, Mailpit, and all PHP-FPM daemons.
* **Quick Batch Actions**: One-click **Start All**, **Stop All**, **Restart All**, and **Reload Nginx**.
* **On-the-fly CLI PHP Switcher**: Change globally active CLI PHP version instantly via dropdown.
* **Integrated Log Tail Viewer**: Select and inspect live tails for Nginx, MariaDB, PHP, and Virtual Host logs.
* **Virtual Host Navigator**: View local vhost mappings, docroots, SSL status, and open sites directly in your default browser.
* **Asynchronous & Non-Blocking**: Built with Textual workers — all background actions and I/O polling run smoothly without freezing the UI.

---

### Interactive CLI Control Menu (`ctl`)

Launch the interactive terminal service selector:
```bash
ndev ctl
```

---

### Virtual Host Management (`vhost`)

Create and manage local Nginx sites mapped to `127.0.0.1`:

```bash
# Interactive wizard (requires sudo for /etc/nginx/ and /etc/hosts)
sudo ndev vhost

# Create a standard HTTP virtual host
sudo ndev vhost --domain project.local --root /home/user/projects/myproject --php 8.4

# Create an HTTPS virtual host with trusted local SSL certificates (mkcert)
sudo ndev vhost --domain project.local --root /home/user/projects/myproject --php 8.4 --ssl
```

---

### SQL Database Manager (`db`)

Manage MySQL/MariaDB databases and users:

```bash
# Launch interactive database wizard
ndev db

# Create a database
ndev db create-db mydb --owner myuser

# Create a database user with privileges
ndev db create-user myuser --new-password secret --grant-db mydb

# Export database dump
ndev db export-db mydb -o backup.sql

# Import database dump
ndev db import-db mydb backup.sql

# Drop a database
ndev db drop-db mydb
```

---

### PECL Extension Manager (`ext`)

Compile and manage PECL extensions for any installed PHP version:

```bash
# List loaded extensions for a PHP version
ndev ext list 8.4

# Install and compile a PECL extension (e.g. redis, xdebug)
ndev ext install redis 8.4

# Enable or disable an extension
ndev ext enable redis 8.4
ndev ext disable redis 8.4
```

---

### phpMyAdmin Management (`pma`)

Manage the phpMyAdmin database administration web UI served locally in the background:

> [!TIP]
> **phpMyAdmin Access & Credentials**:
> * **URL**: [http://127.0.0.1:8080](http://127.0.0.1:8080)
> * **Default Username**: `root`

```bash
# Start phpMyAdmin on port 8080 (auto-installs on first run)
ndev start pma

# Check status
ndev status pma

# Stop or restart phpMyAdmin
ndev stop pma
ndev restart pma
```

---

### Local Email Sandbox (`mailpit`)

Catch every outgoing e-mail your local project sends without hitting real inboxes, using [Mailpit](https://github.com/axllent/mailpit) — a fast, zero-dependency prebuilt binary with a modern web UI.

> [!TIP]
> **SMTP & Web UI Defaults**:
> * **SMTP server** → `127.0.0.1:1025` ← point your PHP / Laravel / WordPress app here
> * **Web inbox**   → [http://127.0.0.1:8025](http://127.0.0.1:8025)
> * No authentication required — every sent email is safely captured locally.

```bash
# Install prebuilt binary from GitHub releases
ndev mailpit install

# Start the sandbox (auto-downloads if not present)
ndev mailpit start
ndev start mailpit

# Launch / open Web UI in your default browser
ndev mailpit launch
ndev mailpit open

# View status
ndev mailpit status
ndev status mailpit

# Stop or restart
ndev mailpit stop
ndev stop mailpit
ndev mailpit restart
ndev restart mailpit

# Custom ports
ndev mailpit start --smtp-port 2525 --web-port 8085
```

#### Configuring your PHP project to use Mailpit

**Laravel (`.env`):**
```env
MAIL_MAILER=smtp
MAIL_HOST=127.0.0.1
MAIL_PORT=1025
MAIL_USERNAME=null
MAIL_PASSWORD=null
MAIL_ENCRYPTION=null
```

**Native PHP (`php.ini`):**
```ini
[mail function]
SMTP      = 127.0.0.1
smtp_port = 1025
```

**WordPress (`wp-config.php` / SMTP Plugin):**
* **Host**: `127.0.0.1`
* **Port**: `1025`
* **Encryption**: None / Plain
* **Authentication**: None / No

Or via Symfony Mailer / PHPMailer / Python / Node.js — just send SMTP traffic to `127.0.0.1:1025`.

---

### Interactive Developer Shell (`shell`)

Open an interactive shell inside the bubblewrap build sandbox:

```bash
ndev shell
```

---

### Public HTTP Tunneling (`grok`)

Tunnel any configured local virtual host to the public web via `ngrok`:

```bash
ndev grok
```

---

### Diagnostics & Log Viewing

```bash
# Run environment diagnostics
ndev doctor

# View / tail PHP-FPM logs
ndev logs 8.4

# Clean download cache and temporary build files
ndev clean
```

---

## Configuration

You can customize compilation and runtime settings by editing `~/.ndev/config.toml` or individual PHP configuration files:

* **Global Config**: `~/.ndev/config.toml`
* **PHP Configuration (`php.ini`)**: `~/.ndev/php/<version>/etc/php.ini`
* **Extension Configuration (`conf.d/`)**: `~/.ndev/php/<version>/etc/conf.d/<ext>.ini`
* **PHP-FPM Server Configuration**: `~/.ndev/php/<version>/etc/php-fpm.conf`
* **PHP-FPM Pool Configuration**: `~/.ndev/php/<version>/etc/php-fpm.d/www.conf`
