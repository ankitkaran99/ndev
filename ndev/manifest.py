import json
import datetime
from pathlib import Path
from ndev.constants import NDEV_DIR
from ndev.logger import logger

MANIFEST_FILE = NDEV_DIR / "manifest.json"

def load_manifest() -> dict:
    """Load the manifest of installed versions."""
    if not MANIFEST_FILE.exists():
        return {"installed": {}}
    try:
        return json.loads(MANIFEST_FILE.read_text())
    except Exception as e:
        logger.warning(f"Failed to read manifest: {e}. Returning empty.")
        return {"installed": {}}

def save_manifest(manifest: dict):
    """Save the manifest of installed versions."""
    try:
        MANIFEST_FILE.write_text(json.dumps(manifest, indent=2))
    except Exception as e:
        logger.error(f"Failed to write manifest: {e}")

def add_installed_version(version: str, path: str, configure_flags: list[str]):
    """Add a version to the installed manifest."""
    manifest = load_manifest()
    manifest["installed"][version] = {
        "path": path,
        "installed_at": datetime.datetime.now().isoformat(),
        "configure_flags": configure_flags
    }
    save_manifest(manifest)

def remove_installed_version(version: str):
    """Remove a version from the installed manifest."""
    manifest = load_manifest()
    if version in manifest["installed"]:
        del manifest["installed"][version]
        save_manifest(manifest)
