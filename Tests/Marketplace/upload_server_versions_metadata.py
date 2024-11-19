import argparse
import os

from Tests.Marketplace.marketplace_constants import GCPConfig
from Tests.Marketplace.marketplace_services import json_write
from Tests.scripts.utils import logging_wrapper as logging
from Tests.scripts.utils.log_util import install_logging


def upload_server_versions_metadata(artifacts_dir: str):
    """
    Upload the versions-metadata.json to the build artifacts folder.

    Args:
        artifacts_dir (str): The CI artifacts directory to upload the versions-metadata.json file to.
    """
    versions_metadata_path = os.path.join(artifacts_dir, GCPConfig.VERSIONS_METADATA_FILE)
    json_write(versions_metadata_path, GCPConfig.versions_metadata_contents)
    logging.success(f"Finished copying {GCPConfig.VERSIONS_METADATA_FILE} to artifacts to {artifacts_dir}.")


def option_handler():
    """Validates and parses script arguments.

    Returns:
        Namespace: Parsed arguments object.

    """
    parser = argparse.ArgumentParser(description="Store packs in cloud storage.")
    # disable-secrets-detection-start
    parser.add_argument("-pa", "--packs_artifacts_path", help="The full path of packs artifacts", required=True)

    # disable-secrets-detection-end
    return parser.parse_args()


def main():
    install_logging("versions_metadata.log", logger=logging)
    options = option_handler()
    packs_artifacts_path = options.packs_artifacts_path

    # upload server versions metadata to bucket
    logging.info(f"Start copying the versions-metadata.json file to {packs_artifacts_path}")
    upload_server_versions_metadata(packs_artifacts_path)


if __name__ == "__main__":
    main()
