import argparse
import json
import os
import sys
from distutils.util import strtobool
from pathlib import Path

from Tests.Marketplace.common import get_buckets_from_marketplaces
from Tests.Marketplace.marketplace_services import init_storage_client
from Tests.scripts.utils import logging_wrapper as logging
from Tests.scripts.utils.log_util import install_logging


def option_handler():
    """Validates and parses script arguments.

    Returns:
        Namespace: Parsed arguments object.

    """
    parser = argparse.ArgumentParser(description="Deploy Groups File")
    # disable-secrets-detection-start
    parser.add_argument("-cpi", "--ci_pipeline_id", help="The id of the pipeline", required=True)
    parser.add_argument(
        "-dr", "--dry_run", type=strtobool, help="true for a dry run pipeline, false for a prod pipeline", default="true"
    )
    parser.add_argument("-mp", "--marketplace", help="The marketplace version.", default="xsoar")

    # disable-secrets-detection-end
    return parser.parse_args()


def upload_to_bucket(bucket_name: str, group_name: str, group_packs: list[dict], dev_file_path: str):
    """
    Upload the group config file to the bucket.

    Args:
        bucket_name (str): The name of the bucket.
        group_name (str): The group name.
        group_packs (list): List of packs for a group.
        dev_file_path (str): The dev file path.
    """
    try:
        storage_client = init_storage_client()
        storage_bucket = storage_client.bucket(bucket_name)
        deploy_path = os.path.join(dev_file_path, f"content/config/auto_upgrade_{group_name}.json")
        path_blob = storage_bucket.blob(deploy_path)
        path_blob.upload_from_string(json.dumps(group_packs), content_type="application/json")
        logging.info(f"The deploy to {deploy_path} finish successfully")
    except Exception as e:
        logging.exception(f"Failed to upload the file to the bucket. Additional Info: {e!s}")
        sys.exit(1)


def get_bucket_name_and_dev_path(marketplace: str, dry_run: str, ci_pipeline_id: str):
    """
    Get the bucket name and the dev file path. the dev file path is based on the pipeline id.
    Args:
        marketplace (str): The marketplace name.
        dry_run (str): true for a dry run pipeline, false for a prod pipeline.
        ci_pipeline_id (str): The id of the pipeline.
    """
    marketplaces_prod_buckets_names, marketplaces_dev_buckets_names = get_buckets_from_marketplaces(marketplace)
    if not marketplaces_prod_buckets_names or not marketplaces_dev_buckets_names:
        logging.exception(f"Failed to retrieve the buckets name for {marketplace=}")
        sys.exit(1)
    if not dry_run:
        return marketplaces_prod_buckets_names[0], ""
    dev_file_path = os.path.join("upload-flow/builds/test_groups_file", ci_pipeline_id)
    return marketplaces_dev_buckets_names[0], dev_file_path


def read_config_file() -> dict[str, list]:
    """
    Read the config file and return the parsed file.
    Returns:
        dict: The parsed file.
    """
    return json.loads(Path("config/auto_upgrade_config.json").read_text())


def filter_groups_per_marketplace(parsed_file, marketplace):
    """
    Filter the groups per marketplace.
    Args:
        parsed_file (dict): The parsed file.
        marketplace (str): The marketplace name.
    Returns:
        dict: A dictionary of groups and their packs.
    """
    filtered_groups_per_marketplace = {}
    for group, group_info in parsed_file.items():
        # file comments ignore
        if group == "__comment__":
            continue
        if marketplace in group_info.get("marketplaces"):
            filtered_groups_per_marketplace[group] = {"packs": group_info.get("packs")}
    return filtered_groups_per_marketplace


def get_groups_packs_for_marketplace(marketplace: str) -> dict[str, list]:
    """
    Get all relevant groups for specific marketplace.
    Args:
        marketplace (str): The marketplace name.
    Returns:
        dict: A dictionary of groups and their packs.
    """
    parsed_file: dict = read_config_file()
    return filter_groups_per_marketplace(parsed_file, marketplace)


def main():
    install_logging("deploy_groups_file.log", logger=logging)
    options = option_handler()
    ci_pipeline_id = options.ci_pipeline_id
    dry_run = options.dry_run
    marketplace = options.marketplace

    marketplace_bucket_name, dev_file_path = get_bucket_name_and_dev_path(marketplace, dry_run, ci_pipeline_id)
    groups_name_to_packs = get_groups_packs_for_marketplace(marketplace)
    for group_name, group_packs in groups_name_to_packs.items():
        upload_to_bucket(
            bucket_name=marketplace_bucket_name, group_name=group_name, group_packs=group_packs, dev_file_path=dev_file_path
        )


if __name__ == "__main__":
    main()
