import argparse
import json
import os

from demisto_sdk.commands.common.constants import MarketplaceVersions, MarketplaceVersionToMarketplaceName

from Tests.Marketplace.marketplace_constants import GCPConfig
from Tests.Marketplace.marketplace_services import init_storage_client, load_json
from Tests.Marketplace.upload_packs import get_packs_ids_to_upload_and_update
from Tests.scripts.utils import logging_wrapper as logging
from Tests.scripts.utils.log_util import install_logging


def extract_failed_to_upload(packs_results_upload: dict) -> set[str]:
    """
    Extracts the set of failed packs from the upload results dictionary.

    Args:
        packs_results_upload (Dict): Dictionary containing the results of the upload.

    Returns:
        Set[str]: A set of keys representing the failed packs.
    """
    upload_packs = packs_results_upload.get("upload_packs_to_marketplace_storage", {})
    failed_packs = set(upload_packs.get("failed_packs", {}).keys())
    logging.debug(f"failed_to_upload packs: {failed_packs}")
    return failed_packs


def upload_to_bucket(service_account: str, failed_packs_data: dict, marketplace: MarketplaceVersions = MarketplaceVersions.XSOAR):
    """
    Uploads content status data to the bucket name based on the marketplace version.

    Args:
        service_account (str): Path to the service account JSON key file.
        marketplace (MarketplaceVersions): The marketplace version to determine the bucket name.
        failed_packs_data (dict): The failed_packs_data to be uploaded to the bucket.

    Raises:
        Exception: If the upload process fails.
    """
    try:
        production_bucket_name = MarketplaceVersionToMarketplaceName.get(marketplace)
        storage_client = init_storage_client(service_account)
        storage_bucket = storage_client.bucket(production_bucket_name)
        content_status_storage_path = os.path.join("content/packs/", f"{GCPConfig.CONTENT_STATUS}.json")
        content_status_blob = storage_bucket.blob(content_status_storage_path)
        content_status_blob.upload_from_string(json.dumps(failed_packs_data), content_type="application/json")
        logging.info(f"Uploaded content_status data to {content_status_storage_path} in bucket {production_bucket_name}")
    except Exception as e:
        logging.exception(f"Failed to upload the file to the bucket. Additional Info: {e!s}")


def option_handler():
    parser = argparse.ArgumentParser(description="Upload failed packs information to GCS.")
    parser.add_argument("-pu", "--packs_to_upload_file", required=True, help="Path to the content_packs_to_upload.json file")
    parser.add_argument("-pru", "--packs_results_upload", required=False, help="Path to packs_results_upload.json")
    parser.add_argument("-pri", "--packs_results_install", required=False, help="Path to packs_results_install.json")
    parser.add_argument("-s", "--service_account", required=True, help="Path to the gcloud service account JSON file")
    parser.add_argument("-mp", "--marketplace", required=True, help="Marketplace version")
    return parser.parse_args()


def main():
    install_logging("extract_and_upload_failed_packs.log", logger=logging)
    option = option_handler()

    service_account = option.service_account
    marketplace = MarketplaceVersions(option.marketplace)

    failed_packs_data = {}
    packs_to_upload, packs_to_update_metadata = get_packs_ids_to_upload_and_update(option.packs_to_upload_file)
    failed_packs_upload = (
        extract_failed_to_upload(load_json(option.packs_results_upload)) if option.packs_results_upload else set()
    )

    # failed_packs_install = extract_failed_to_install(load_json(option.packs_results_install))
    # if option.packs_results_install else set() - TODO CIAC-10977

    if failed_packs_upload:
        failed_packs_data["failed_to_upload"] = {
            "packs_to_upload": list(failed_packs_upload.intersection(packs_to_upload)),
            "packs_to_update_metadata": list(failed_packs_upload.intersection(packs_to_update_metadata)),
        }

    upload_to_bucket(service_account, failed_packs_data, marketplace)


if __name__ == "__main__":
    main()
