from pathlib import Path

from google.cloud.storage.blob import Blob
from xlogs.commands.bundle.download import bundle_download_path
from xlogs.commands.bundle.extract import extract
from xlogs.commands.common import logger


def download_and_extract(project_id: str, bundle_password: str, dest_path_base: Path, bundle: Blob, force_download: bool):
    extract_dest_path = bundle_download_path(project_id, dest_path_base, bundle)

    if (not force_download) and extract_dest_path.exists() and any(tuple(extract_dest_path.rglob("*"))):
        logger.debug(f"Skipping download, bundle already exists at {extract_dest_path}")

    else:
        logger.info(f"Downloading {bundle.name}")
        extract(zip_bytes=bundle.download_as_bytes(), dest=extract_dest_path, bundle_password=bundle_password)
        logger.info(f"Extracted bundle to {extract_dest_path}")

    return extract_dest_path
