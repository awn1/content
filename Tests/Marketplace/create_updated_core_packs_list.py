import argparse
import json
import os
import sys
from pathlib import Path

from Tests.Marketplace.common import get_buckets_from_marketplaces
from Tests.Marketplace.marketplace_constants import GCPConfig
from Tests.Marketplace.marketplace_services import init_storage_client
from Tests.scripts.utils import logging_wrapper as logging
from Tests.scripts.utils.log_util import install_logging


def parse_packs_to_update(packs_to_update: str) -> dict:
    """
    Parse the list of corepacks to update.
    for example:
    input- pack1:1.0.0,pack2:1.0.0
    output- {'pack1': '1.0.0', 'packs': '1.0.0'}

    Args:
         packs_to_update (str): a list of packs and their pack version separated with commas in the following
            format: pack1:1.0.0,pack2:1.0.0.
    Returns:
        a dict containing the packs to update and their new version.
    """
    if not packs_to_update or ":" not in packs_to_update:
        logging.error("The parameter 'PACK_VERSIONS', should be in the format: pack1:1.0.0,pack2:1.0.0")
        sys.exit(1)
    packs_to_update_list = packs_to_update.split(",")
    packs_dict = {}
    for pack_version in packs_to_update_list:
        pack_version_split = pack_version.split(":")
        pack = pack_version_split[0].strip()
        ver = pack_version_split[1].strip()
        packs_dict[pack] = ver
    logging.debug(f"{packs_dict=}")
    return packs_dict


def create_updated_corepacks_list(
    corepacks_current_list: list[str], packs_to_update: dict, server_version: str, marketplace_bucket_name: str
) -> list:
    """
    Return the updated corepacks list.

    Args:
         corepacks_current_list (list): The current corepacks list.
         packs_to_update (dict): a dict containing the packs to update and their new version.
            format: pack1:1.0.0,pack2:1.0.0.
        server_version (str)
        marketplace_bucket_name (str): the name of the bucket to update with the new list.
    Returns:
        A list of the updated corepacks list.
    """

    # create a list of the full paths of the packs to update
    full_path_packs_to_update = []
    current_packs_to_update: list[str] = []  # the current paths of the packs we need to update
    for pack, version in packs_to_update.items():
        full_path_packs_to_update.append(f"{pack}/{version}/{pack}.zip")
        current_pack_path = [p for p in corepacks_current_list if pack == p.split("/")[0]]
        current_packs_to_update = current_packs_to_update + current_pack_path

    # remove the old paths, if the path of the pack is in the current_packs_to_update it means that the pack version
    # in the list will be updated and it needs to be removed.
    updated_corepack_list = [pack for pack in corepacks_current_list if pack not in current_packs_to_update]
    # add the new packs paths
    updated_corepack_list = updated_corepack_list + full_path_packs_to_update

    logging.debug(
        f"The updated corepack list for {server_version=} and {marketplace_bucket_name=} content is " f"{updated_corepack_list=}"
    )
    return updated_corepack_list


def option_handler():
    """Validates and parses script arguments.

    Returns:
        Namespace: Parsed arguments object.

    """
    parser = argparse.ArgumentParser(description="Store packs in cloud storage.")
    # disable-secrets-detection-start
    parser.add_argument("-mp", "--marketplaces", help="The marketplace version.", default="xsoar")
    # parser.add_argument("-uc", "--upload_commit", help="Last upload commit", required=True)
    parser.add_argument("-p", "--packs", help="The name of the packs to override", required=True)
    parser.add_argument("-sv", "--server_version", help="The server version of the core packs list to override", required=True)

    # disable-secrets-detection-end
    return parser.parse_args()


def get_corepacks_list_content(bucket_name: str, server_version: str) -> tuple:
    """
    Extract the list of corepacks and their versions from the corepacks file in the bucket.

    Args:
        bucket_name (str): the name of the relevant bucket.
        server_version (str): the server version of the corepacks list to update.
    Returns:
        A tuple that contains 2 lists that together are the content of the corepacks files, the corePacks list and
        upgradeCorePacks list.
    """
    # google cloud storage client initialized.
    logging.debug("init storage_client")
    storage_client = init_storage_client()
    storage_bucket = storage_client.bucket(bucket_name)
    corepacks_file_name = f"corepacks-{server_version}.json"
    core_packs_path = os.path.join(GCPConfig.CONTENT_PACKS_PATH, corepacks_file_name)
    blob = storage_bucket.blob(core_packs_path)
    if blob.exists():
        with blob.open("r") as f:
            core_packs_file_data = json.load(f)
            core_packs_list = core_packs_file_data.get("corePacks", [])
            upgrade_core_packs = core_packs_file_data.get("upgradeCorePacks", [])
    else:
        logging.exception(f"The file {core_packs_path} does not exists in the bucket {bucket_name}.")
        sys.exit(1)
    logging.debug(
        f"The current content of the corepacks list in the bucket {bucket_name}, for the server version "
        f"{server_version} is {core_packs_list=}"
    )
    return core_packs_list, upgrade_core_packs


def validate_core_packs_params(packs_to_update: dict, upgrade_core_packs: list, marketplace_bucket_name: str):
    """
    Validate that the packs from the pipeline parameters are in the core packs list.
    In case there are, fail the pipeline.

    Args:
        packs_to_update: dict (dict): The dict of the packs and the new versions.
        upgrade_core_packs (list): The core packs list.
        marketplace_bucket_name (str)
    """
    packs_list = list(packs_to_update.keys())
    not_valid_packs = []
    for pack in packs_list:
        if pack not in upgrade_core_packs:
            not_valid_packs.append(pack)
    if not_valid_packs:
        logging.error(
            f"The packs {not_valid_packs} aren't in the core packs list {upgrade_core_packs} for the bucket "
            f"{marketplace_bucket_name}."
        )
        sys.exit(1)
    logging.debug(
        f"The packs {packs_list} are on the core packs list {upgrade_core_packs} for the bucket " f"{marketplace_bucket_name}"
    )


def save_json_file_to_artifacts(file_content: dict, artifacts_path: str, marketplace_bucket_name: str, server_version: str):
    """
    Create an artifact file with the updated core packs list for the relevant marketplace.

    Args:
        file_content (dict): the content of the new list.
        artifacts_path (str): the path of the artifacts' folder.
        marketplace_bucket_name (str): the name of the relevant bucket.
        server_version (str): the server version of the core packs list to update.
    """
    file = Path(f"{artifacts_path}/{marketplace_bucket_name}/corepacks-{server_version}.json")
    file.parent.mkdir(parents=True, exist_ok=True)
    logging.debug(f"writing to the file {file}")
    with file.open("w", encoding="UTF-8") as f:
        f.write(json.dumps(file_content, indent=4))
    logging.info(f"Successfully saved the new corepacks list to {file}")


def main():
    install_logging("create_updated_core_packs_list.log", logger=logging)
    options = option_handler()
    packs_artifacts_path = os.getenv("ARTIFACTS_FOLDER") or ""
    marketplace = options.marketplaces
    packs_to_update = options.packs
    server_version = options.server_version

    logging.debug(
        f"The params to override the core packs are {packs_artifacts_path=}, {marketplace=}, "
        f"{packs_to_update=}, {server_version=}"
    )
    marketplaces_buckets_names, _ = get_buckets_from_marketplaces(marketplace)
    for marketplace_bucket_name in marketplaces_buckets_names:
        corepacks_current_list, upgrade_core_packs = get_corepacks_list_content(marketplace_bucket_name, server_version)
        dict_packs_to_update = parse_packs_to_update(packs_to_update)
        validate_core_packs_params(dict_packs_to_update, upgrade_core_packs, marketplace_bucket_name)
        updated_corepacks_list = create_updated_corepacks_list(
            corepacks_current_list=corepacks_current_list,
            packs_to_update=dict_packs_to_update,
            server_version=server_version,
            marketplace_bucket_name=marketplace_bucket_name,
        )
        if len(updated_corepacks_list) != len(upgrade_core_packs):
            logging.error(
                f"There was an error in the script, the length of the 2 lists isn't the same "
                f"{len(updated_corepacks_list)} != {len(upgrade_core_packs)}."
            )
            sys.exit(1)
        updated_json_file = {"corePacks": updated_corepacks_list, "upgradeCorePacks": upgrade_core_packs}
        save_json_file_to_artifacts(updated_json_file, packs_artifacts_path, marketplace_bucket_name, server_version)


if __name__ == "__main__":
    main()
