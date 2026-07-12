import httpx
from packaging.version import parse as parse_version
from ndev.github import fetch_releases
from ndev.logger import logger

def resolve_version(version_input: str) -> tuple[str, str, str, str]:
    """
    Resolve version input (e.g. '8.4', '8.5.8') to:
    (exact_version, filename, sha256, download_url)
    """
    version_input = version_input.strip().lower()
    if version_input.startswith("php-"):
        version_input = version_input[4:]
        
    parts = version_input.split(".")
    try:
        major = int(parts[0])
    except ValueError:
        raise ValueError(f"Invalid version format: '{version_input}'")
        
    logger.info(f"Resolving version prefix '{version_input}'...")
    releases = fetch_releases(major)
    if not releases:
        raise ValueError(f"No releases found or network error for PHP version {major}")
        
    matching_versions = []
    for v in releases.keys():
        if v.startswith(version_input):
            matching_versions.append(v)
            
    if not matching_versions:
        raise ValueError(f"Could not resolve version prefix '{version_input}' to any active release.")
        
    resolved_version = max(matching_versions, key=parse_version)
    logger.info(f"Resolved to version: {resolved_version}")
    
    release_data = releases[resolved_version]
    sources = release_data.get("source", [])
    
    chosen_source = None
    for ext in [".tar.xz", ".tar.gz", ".tar.bz2"]:
        for src in sources:
            if src.get("filename", "").endswith(ext):
                chosen_source = src
                break
        if chosen_source:
            break
            
    if not chosen_source:
        if sources:
            chosen_source = sources[0]
        else:
            raise ValueError(f"No source downloads available for resolved version {resolved_version}")
            
    filename = chosen_source["filename"]
    sha256 = chosen_source.get("sha256", "")
    download_url = f"https://www.php.net/distributions/{filename}"
    
    return resolved_version, filename, sha256, download_url
