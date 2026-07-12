# ndev

`ndev` is a powerful, non-root CLI developer tool suite to download, compile, install, and manage isolated PHP-FPM versions, custom extensions, databases, Nginx virtual hosts, and public tunneling on Debian-based systems.

It allows you to run multiple isolated PHP-FPM services simultaneously without interfering with the system-wide software or requiring system-level changes.

---

## Key Features

- **Sandboxed Compilation**: Automatically builds any PHP version from source inside an isolated `bubblewrap` environment with custom, self-healing multiarch compile paths.
- **Root-free Sandbox Packages**: Downloads, relocates, and resolves required system development packages (`libsqlite3-dev`, `libonig-dev`, etc.) fully within user-space.
- **Unified Services Control (`ctl`)**: An interactive dashboard to inspect and manage Nginx, MariaDB, PostgreSQL, System PHP-FPM, and custom `ndev` compiled FPM instances.
- **SQL Database Manager (`db`)**: An interactive wizard and CLI suite to create/drop databases and users for MySQL and PostgreSQL.
- **Ngrok HTTP Tunneling (`grok`)**: Lists active virtual hosts, configures request routing headers, and proxies local traffic over the public web with `ngrok`.
- **Nginx Virtual Host Manager (`vhost`)**: Prompts for domains, roots, and PHP-FPM sockets, configures Nginx, updates `/etc/hosts`, and reloads configurations (requires sudo).
- **Extension Manager (`ext`)**: Installs and compiles custom PECL extensions (like Redis) and enables or disables them per version.

---

## Directory Structure & Configuration Files

All compiled code, templates, and service configurations are organized under `~/.ndev`:
- **Builds directory**: `~/.ndev/builds/` (PHP source downloads & extractions)
- **Installations**: `~/.ndev/php/<version>/`
- **Sockets & PIDs**: `~/.ndev/run/`
- **Configuration Templates**: `~/.ndev/templates/` (templates copied when initializing new versions)

### Where to edit config files:
For any installed version (e.g. `8.4.23`), you can modify its behavior by editing the following files:
- **Global PHP Configuration (`php.ini`)**: `~/.ndev/php/<version>/etc/php.ini` (e.g. adjust `memory_limit`, `upload_max_filesize`, `display_errors`, etc.)
- **Extension configurations (`conf.d/`)**: `~/.ndev/php/<version>/etc/conf.d/<ext_name>.ini` (e.g. configure Xdebug parameters, Redis connection settings, etc.)
- **PHP-FPM Server Configuration (`php-fpm.conf`)**: `~/.ndev/php/<version>/etc/php-fpm.conf` (controls FPM daemon settings, logs, etc.)
- **PHP-FPM Pool Configuration (`www.conf`)**: `~/.ndev/php/<version>/etc/php-fpm.d/www.conf` (controls worker processes counts, user/group execution, and sockets)

---

## Installation

### 1. Install System Dependencies (APT)

Before installing the Python package, ensure the host system has the necessary packages installed (for Debian/Ubuntu-based systems):

```bash
# Required packages for sandbox construction, compilation, and package discovery
sudo apt update
sudo apt install -y bubblewrap build-essential pkg-config
```

#### Optional Feature-specific Packages:
Depending on which features of `ndev` you plan to use, you will need to install their corresponding host packages:
- **Nginx Virtual Host Manager (`vhost`)**: Requires `nginx` on the host.
  ```bash
  sudo apt install -y nginx
  ```
- **SQL Database Manager (`db`)**: Requires standard client utilities.
  ```bash
  sudo apt install -y mysql-client postgresql-client
  ```
- **Ngrok HTTP Tunneling (`grok`)**: Requires the `ngrok` binary to be installed on your system. Follow the official instructions on [ngrok.com](https://ngrok.com/download) to install it.

### 2. Set Up ndev

```bash
# Clone the repository
git clone https://github.com/ankitkaran99/ndev.git
cd ndev

# Set up virtual environment and install dependencies
python3 -m venv .venv
.venv/bin/pip install -e .
```

---

## Usage

### Core Commands

| Command | Description |
|---|---|
| `available` | List all available PHP versions from php.net |
| `install <version>` | Resolve, download, and compile a PHP version from source |
| `uninstall <version>` | Remove an installed PHP version |
| `list` | List all locally installed PHP versions |
| `current` | Show the active CLI PHP version |
| `use <version>` | Set a PHP version as the active CLI binary |
| `doctor` | Run diagnostics on compile tools, bubblewrap, and packages |
| `shell` | Open an interactive shell inside the build sandbox |

### Daemon and Socket Commands

| Command | Description |
|---|---|
| `start <version>` | Start PHP-FPM service for a version |
| `stop <version>` | Stop PHP-FPM service for a version |
| `restart <version>` | Restart PHP-FPM service for a version |
| `reload <version>` | Gracefully reload FPM configuration |
| `status <version>` | Show status and active socket details for a version |
| `logs <version>` | Tail active PHP-FPM log output |

### Extensions Manager

Manage PECL extensions for a specific PHP version:
```bash
# List all active/inactive extensions
ndev ext list 8.4.23

# Install a PECL extension (e.g. redis)
ndev ext install redis 8.4.23

# Disable/Enable extensions
ndev ext disable redis 8.4.23
ndev ext enable redis 8.4.23
```

### Integrated Dev Tools

#### 1. Services Control (`ctl`)
Launch the interactive dashboard to manage local web servers, databases, and FPMs:
```bash
ndev ctl
```

#### 2. SQL Database Manager (`db`)
Manage MySQL and PostgreSQL databases:
```bash
# Run the interactive wizard
ndev db

# Create/Drop databases
ndev db create-db school --driver mysql
ndev db drop-db school --driver pgsql

# Create/Drop database users
ndev db create-user john --new-password secret --grant-db school
ndev db drop-user john
```

#### 3. Nginx Virtual Host Manager (`vhost`)
Easily set up Nginx configurations matching a domain to a project root and PHP socket:
```bash
sudo ndev vhost --domain project.local --root /home/user/project --php "ndev 8.4"
```

#### 4. Ngrok HTTP Tunneling (`grok`)
Proxy local Nginx virtual hosts over public URLs:
```bash
ndev grok
```
