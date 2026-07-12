import hashlib
from pathlib import Path
import httpx
from rich.progress import Progress, TextColumn, BarColumn, DownloadColumn, TransferSpeedColumn, TimeRemainingColumn
from ndev.constants import DOWNLOADS_DIR
from ndev.logger import logger

def calculate_sha256(filepath: Path) -> str:
    """Calculate the SHA-256 checksum of a file."""
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(8192):
            sha256.update(chunk)
    return sha256.hexdigest()

def download_php_source(filename: str, sha256_expected: str, download_url: str) -> Path:
    """Download PHP source tarball and verify its SHA-256 checksum."""
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    target_path = DOWNLOADS_DIR / filename
    
    if target_path.exists():
        logger.info(f"Checking cached download: {filename}")
        checksum = calculate_sha256(target_path)
        if checksum == sha256_expected:
            logger.info("Cache hit: Download is valid.")
            return target_path
        else:
            logger.warning("Cache mismatch: Re-downloading source...")
            target_path.unlink()
            
    logger.info(f"Downloading {filename} from {download_url}...")
    
    with httpx.Client() as client:
        with client.stream("GET", download_url) as response:
            response.raise_for_status()
            total_size = int(response.headers.get("content-length", 0))
            
            with Progress(
                TextColumn("[bold blue]{task.description}"),
                BarColumn(),
                DownloadColumn(),
                TransferSpeedColumn(),
                TimeRemainingColumn()
            ) as progress:
                task = progress.add_task("Downloading", total=total_size)
                
                with open(target_path, "wb") as f:
                    for chunk in response.iter_bytes(chunk_size=8192):
                        f.write(chunk)
                        progress.update(task, advance=len(chunk))
                        
    checksum = calculate_sha256(target_path)
    if sha256_expected and checksum != sha256_expected:
        target_path.unlink()
        raise ValueError(f"SHA-256 checksum mismatch for {filename}. Expected {sha256_expected}, got {checksum}")
        
    logger.info("Download completed and verified successfully.")
    return target_path
