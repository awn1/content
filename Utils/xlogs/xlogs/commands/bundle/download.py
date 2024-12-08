from pathlib import Path

import tabulate
import typer
from google.cloud import storage
from google.cloud.exceptions import Forbidden
from google.cloud.storage.blob import Blob
from xlogs.commands.common import logger, remove_engine_prefix

LOG_BUNDLE_PATH = "xsoar/logs/encrypted-logs-bundle"


def get_xsoar_files_bucket(project_id: str) -> storage.Bucket:
    project_id = remove_engine_prefix(project_id)
    return storage.Client(project=project_id).bucket(f"{project_id}-xsoar-files")


def list_blobs(project_id: str) -> tuple[storage.Blob]:
    bucket = get_xsoar_files_bucket(project_id)

    try:
        return tuple(bucket.list_blobs(prefix=LOG_BUNDLE_PATH))
    except Forbidden as e:
        logger.error(e)  # no need for exc_info/stack trace
        raise typer.Exit(1)


def bundle_download_path(project_id: str, dest_path_base: Path, bundle: Blob):
    return dest_path_base / f"{project_id}--{bundle.time_created.strftime('%Y-%m-%dT%H-%M')}"


def choose_bundle_blob(bundles: list[Blob], last: bool) -> Blob:
    match len(bundles):
        case 0:
            logger.error("No matching log bundles found")
            raise typer.Exit(code=1)

        case 1:
            return bundles[0]

        case _:  # multiple bundles found
            if last:
                return bundles[-1]

            print(tabulate.tabulate([[b.time_created] for b in bundles], headers=["Time Created (UTC)"], showindex="always"))
            bundle_index = typer.prompt("Select a bundle index to extract", type=int)
            return bundles[bundle_index]
