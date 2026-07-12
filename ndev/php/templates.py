import os
import getpass
from pathlib import Path
from jinja2 import Template
from ndev.constants import RUN_DIR, LOGS_DIR
from ndev.logger import logger

PHP_INI_TEMPLATE = """[PHP]
engine = On
short_open_tag = Off
precision = 14
output_buffering = 4096
zlib.output_compression = Off
implicit_flush = Off
unserialize_callback_func =
serialize_precision = -1
disable_functions =
disable_classes =
zend.enable_gc = On
expose_php = On
max_execution_time = 30
max_input_time = 60
memory_limit = 128M
error_reporting = E_ALL & ~E_DEPRECATED & ~E_STRICT
display_errors = On
display_startup_errors = On
log_errors = On
log_errors_max_len = 1024
ignore_repeated_errors = Off
ignore_repeated_source = Off
report_memleaks = On
html_errors = On
variables_order = "GPCS"
request_order = "GP"
register_argc_argv = Off
auto_globals_jit = On
post_max_size = 8M
default_mimetype = "text/html"
default_charset = "UTF-8"
doc_root =
user_dir =
enable_dl = Off
file_uploads = On
upload_max_filesize = 2M
max_file_uploads = 20
allow_url_fopen = On
allow_url_include = Off
default_socket_timeout = 60

[CLI Server]
cli_server.color = On

[Date]
date.timezone = UTC
"""

PHP_FPM_CONF_TEMPLATE = """[global]
pid = {{ run_dir }}/php-fpm-{{ major_minor }}.pid
error_log = {{ logs_dir }}/php-fpm-{{ major_minor }}.log
log_level = notice
include = {{ prefix }}/etc/php-fpm.d/*.conf
"""

WWW_CONF_TEMPLATE = """[www]
user = {{ user }}
group = {{ group }}
listen = {{ run_dir }}/php{{ major_minor }}.sock
listen.owner = {{ user }}
listen.group = {{ group }}
listen.mode = 0666

pm = dynamic
pm.max_children = 5
pm.start_servers = 2
pm.min_spare_servers = 1
pm.max_spare_servers = 3
"""

def get_major_minor(version: str) -> str:
    parts = version.split(".")
    return f"{parts[0]}{parts[1]}"

def write_default_configs(prefix: Path, version: str):
    """Generate and write default configs to the installed PHP prefix."""
    etc_dir = prefix / "etc"
    fpm_d = etc_dir / "php-fpm.d"
    conf_d = etc_dir / "conf.d"
    
    # Create directories
    etc_dir.mkdir(parents=True, exist_ok=True)
    fpm_d.mkdir(parents=True, exist_ok=True)
    conf_d.mkdir(parents=True, exist_ok=True)
    
    # Get current user details
    user = getpass.getuser()
    # On some systems, group matches user
    group = user
    
    major_minor = get_major_minor(version)
    
    context = {
        "prefix": str(prefix),
        "run_dir": str(RUN_DIR),
        "logs_dir": str(LOGS_DIR),
        "major_minor": major_minor,
        "user": user,
        "group": group
    }
    
    # 1. php.ini
    php_ini_path = etc_dir / "php.ini"
    if not php_ini_path.exists():
        php_ini_path.write_text(PHP_INI_TEMPLATE)
        logger.info(f"Generated default php.ini at {php_ini_path}")
        
    # 2. php-fpm.conf
    php_fpm_conf_path = etc_dir / "php-fpm.conf"
    if not php_fpm_conf_path.exists():
        rendered = Template(PHP_FPM_CONF_TEMPLATE).render(context)
        php_fpm_conf_path.write_text(rendered)
        logger.info(f"Generated default php-fpm.conf at {php_fpm_conf_path}")
        
    # 3. www.conf
    www_conf_path = fpm_d / "www.conf"
    if not www_conf_path.exists():
        rendered = Template(WWW_CONF_TEMPLATE).render(context)
        www_conf_path.write_text(rendered)
        logger.info(f"Generated default www.conf at {www_conf_path}")
