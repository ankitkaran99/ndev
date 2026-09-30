"""
ngrok tunnel wrapper for ndev-win virtual hosts.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from . import paths, vhost

HTTP_PORT = 80
HTTPS_PORT = 443


def list_vhosts() -> list[str]:
    """Return list of domain names with configured Nginx virtual hosts."""
    return [v["domain"] for v in vhost.list_vhosts()]


def _ngrok_exe() -> str:
    # 1. Check shim dir
    shim_exe = paths.SHIM_DIR / "ngrok.exe"
    if shim_exe.exists():
        return str(shim_exe)

    # 2. Check config
    cfg = paths.load_config()
    path = cfg.get("ngrok_path")
    if path and Path(path).exists():
        return str(path)

    # 3. Check system PATH
    which_path = shutil.which("ngrok") or shutil.which("ngrok.exe")
    if which_path:
        return which_path

    raise FileNotFoundError("ngrok isn't installed -- run `ndev setup` first")


def start_tunnel(domain: str, ssl: bool | None = None) -> tuple[subprocess.Popen, Path]:
    """
    Start `ngrok http` against Nginx.
    Rewrites the request Host header to `domain` and rewrites any response
    redirect Location headers from the local domain back to the ngrok public URL.
    Returns (Popen, policy_file_path).
    """
    import re
    clean_domain = re.sub(r"^https?://", "", domain.strip().lower()).rstrip("/")
    vhost_meta = vhost.get_vhost(clean_domain)
    known = list_vhosts()
    if not vhost_meta and clean_domain not in known:
        raise FileNotFoundError(
            f"No vhost found for '{clean_domain}'. Known vhosts: {known or '(none)'}"
        )

    # Determine SSL mode: use explicit flag if provided, otherwise auto-detect from vhost config
    is_ssl = ssl if ssl is not None else bool(vhost_meta and vhost_meta.get("ssl"))

    target = f"https://localhost:{HTTPS_PORT}" if is_ssl else str(HTTP_PORT)

    # Build traffic policy YAML to ensure:
    # 1. Request Host header is rewritten to clean_domain so Nginx routes to the right vhost.
    # 2. Response Location header rewriting prevents external devices from being redirected
    #    to the unresolvable local domain (e.g. *.local).
    policy_content = f'''on_http_request:
  - actions:
      - type: add-headers
        config:
          headers:
            Host: "{clean_domain}"

on_http_response:
  - expressions:
      - 'res.status_code >= 300 && res.status_code < 400 && "location" in res.headers'
      - 'res.headers["location"][0].contains("://{clean_domain}")'
    actions:
      - type: add-headers
        config:
          headers:
            Location: '${{res.headers["location"][0].replace("https://{clean_domain}", conn.server_name.size() > 0 ? "https://" + conn.server_name : "").replace("http://{clean_domain}", conn.server_name.size() > 0 ? "https://" + conn.server_name : "")}}'
'''

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as tmp:
        tmp.write(policy_content)
        policy_file = Path(tmp.name)

    cmd = [_ngrok_exe(), "http", target, "--traffic-policy-file", str(policy_file)]
    if is_ssl:
        cmd.append("--upstream-tls-verify=false")

    proc = subprocess.Popen(cmd)
    return proc, policy_file

