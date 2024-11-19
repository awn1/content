import argparse
import json
import os
import subprocess
import sys
from distutils.util import strtobool

from Tests.Marketplace.common import get_buckets_from_marketplaces
from Tests.Marketplace.marketplace_constants import GCPConfig
from Tests.Marketplace.marketplace_services import init_storage_client, load_json
from Tests.scripts.utils import logging_wrapper as logging
from Tests.scripts.utils.log_util import install_logging


def option_handler():
    """Validates and parses script arguments.

    Returns:
        Namespace: Parsed arguments object.

    """
    parser = argparse.ArgumentParser(description="Upload Core Packs.")
    # disable-secrets-detection-start
    parser.add_argument("-sv", "--server_version", help="The server version of the core packs list to override.", required=True)
    parser.add_argument("-cpi", "--ci_pipeline_id", help="The id of the pipeline", required=True)
    parser.add_argument(
        "-t", "--test_override_core_packs", help="True for a test pipeline, False for a prod pipeline", default="True"
    )
    parser.add_argument("-mp", "--marketplaces", help="The marketplace version.", default="xsoar")

    # disable-secrets-detection-end
    return parser.parse_args()


def upload_to_bucket(bucket_name: str, server_version: str, core_packs_data: dict, dev_path: str = ""):
    """
    Upload the updated core packs list to the bucket.

    Args:
        bucket_name (str): The name of the bucket.
        server_version (str): The server version.
        core_packs_data (dict): The data of the new core packs list.
        dev_path (str): In a test override core packs flow, there is a different path in the dev bucket vs. a prod
            bucket.
    """
    try:
        storage_client = init_storage_client()
        storage_bucket = storage_client.bucket(bucket_name)
        updated_core_packs_list_path = os.path.join(dev_path, GCPConfig.CONTENT_PACKS_PATH, f"corepacks-{server_version}.json")
        path_blob = storage_bucket.blob(updated_core_packs_list_path)
        if path_blob.exists():
            path_blob.upload_from_string(json.dumps(core_packs_data), content_type="application/json")
            logging.info(
                f"Uploaded the updated core packs file data to {updated_core_packs_list_path} in bucket " f"{bucket_name}"
            )
        else:
            logging.error(f"The path {path_blob} doesn't exist in the bucket {bucket_name}")
    except Exception as e:
        logging.exception(f"Failed to upload the file to the bucket. Additional Info: {e!s}")
        sys.exit(1)


def main():
    install_logging("upload_override_core_packs.log", logger=logging)
    options = option_handler()
    packs_artifacts_path = os.getenv("ARTIFACTS_FOLDER") or ""
    server_version = options.server_version
    ci_pipeline_id = options.ci_pipeline_id
    test = options.test_override_core_packs
    marketplaces = options.marketplaces

    logging.debug(f"Performing {test=} override core packs list for the {marketplaces=} {server_version=}.")
    marketplaces_prod_buckets_names, marketplaces_dev_buckets_names = get_buckets_from_marketplaces(marketplaces)
    for prod_bucket_name, dev_bucket_name in zip(marketplaces_prod_buckets_names, marketplaces_dev_buckets_names):
        artifacts_core_packs_list = os.path.join(packs_artifacts_path, prod_bucket_name, f"corepacks-{server_version}.json")
        if os.path.exists(artifacts_core_packs_list):
            logging.info(f"The core packs file {artifacts_core_packs_list} exists. ")
            core_packs_data = load_json(artifacts_core_packs_list)
            if strtobool(test):
                subprocess.run(["./Tests/scripts/prepare_override_core_packs_for_testing.sh", dev_bucket_name, prod_bucket_name])
                dev_path = f"upload-flow/builds/test_override_core_packs/{ci_pipeline_id}"
                logging.info(f"Uploading to {dev_bucket_name} the updated list {core_packs_data}")
                upload_to_bucket(dev_bucket_name, server_version, core_packs_data, dev_path)
            else:
                logging.info(f"Uploading to {prod_bucket_name} the updated list {core_packs_data}")
                upload_to_bucket(prod_bucket_name, server_version, core_packs_data)
        else:
            logging.info(f"There is no updated core packs list in the path {artifacts_core_packs_list}.")


if __name__ == "__main__":
    main()
