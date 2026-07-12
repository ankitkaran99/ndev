import httpx
from ndev.logger import logger

def fetch_releases(major_version: int) -> dict:
    """Fetch PHP releases metadata for a major version from php.net."""
    url = f"https://www.php.net/releases/index.php?json=1&version={major_version}&max=100"
    try:
        response = httpx.get(url, timeout=10.0)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.warning(f"Failed to fetch PHP releases for major version {major_version}: {e}")
        return {}
