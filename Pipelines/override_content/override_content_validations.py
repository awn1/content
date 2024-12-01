import argparse
import logging
import re
import sys

import coloredlogs
from demisto_sdk.commands.content_graph.interface.neo4j.neo4j_graph import (
    Neo4jContentGraphInterface,
)

from Tests.scripts.utils.log_util import install_logging

ENV_TYPE_OPTIONS = ["dev", "prod"]
DEV_TENANT_PATTERN = r"^qa2-test-\d+$"
PROD_TENANT_PATTERN = r"^xdr-[a-zA-Z]{2}-\d+$"
RED_PRINT = "\033[0m"


def is_content_item_in_graph(content_path: str, marketplace: str) -> bool:
    content_type = None
    with Neo4jContentGraphInterface() as interface:
        if res := interface.search(
            marketplace=marketplace,
            path=content_path,
        ):
            content_type = res[0].content_type
            logging.debug(f"Content type for {content_path} is {content_type} with mp {marketplace}, result is {bool(res)}")
        return bool(res)


def validate_variables(options: argparse.Namespace):
    paths = options.paths
    packs = options.packs
    logging.debug(f"Got the values: paths - {paths}, packs - {packs}")

    if paths and packs:
        raise ValueError(RED_PRINT + "Specify a pack or a content items, not both." + RED_PRINT)

    elif not paths and not packs:
        raise ValueError(RED_PRINT + "Specify a pack or content item to override." + RED_PRINT)

    env_type = options.env_type
    if env_type not in ENV_TYPE_OPTIONS:
        raise ValueError(
            RED_PRINT + f"Got invalid env_type: {env_type}. Specify one of the possible values: {ENV_TYPE_OPTIONS}" + RED_PRINT
        )

    invalid_tenant_ids = []
    if env_type == "dev":
        pattern = DEV_TENANT_PATTERN
        template = "qa2-test-<numbers>"
    else:
        pattern = PROD_TENANT_PATTERN
        template = "xdr-<region>-<numbers>"

    tenant_ids = options.tenant_ids
    tenant_ids_list = tenant_ids.split(",")
    for tenant_id in tenant_ids_list:
        if not re.match(pattern, tenant_id):
            invalid_tenant_ids.append(tenant_id)

    if invalid_tenant_ids:
        raise ValueError(
            RED_PRINT + f"Got invalid tenant ids: {invalid_tenant_ids} for {env_type} environment. Make sure to use "
            f"the '{template}' template." + RED_PRINT
        )


def validate_content_items_marketplace(options: argparse.Namespace):
    if paths := options.paths:
        paths_list = paths.split(",")
        marketplace = options.marketplace
        missing_content_items = []
        for path in paths_list:
            logging.debug(f"Validating path {path} with marketplace - {marketplace}")
            if not is_content_item_in_graph(path, marketplace):
                logging.debug(f"Did not find the content item path '{path}' on the desired marketplace - {marketplace}")
                missing_content_items.append(path)

        if missing_content_items:
            raise ValueError(
                RED_PRINT + f"The following content items do not exist in {marketplace=}: {missing_content_items}.\n"
                "New content must be uploaded as part of a pack upload - for this, use the PACKS variable." + RED_PRINT
            )


def validate_file_types(options: argparse.Namespace):
    if paths := options.paths:
        paths_list = paths.split(",")
        invalid_content_item_file_type = []
        for path in paths_list:
            if not path.endswith((".yml", ".json")):
                invalid_content_item_file_type.append(path)

        if invalid_content_item_file_type:
            raise ValueError(
                RED_PRINT + f"Invalid file types detected in the following content items: {invalid_content_item_file_type} .\n"
                "Make sure to select a valid file for override: either a .yml or a .json file." + RED_PRINT
            )


def run(options: argparse.Namespace):
    try:
        logging.debug("Starting the pipeline validations.")
        validate_variables(options)
        validate_content_items_marketplace(options)
        validate_file_types(options)
        logging.debug("Finished validations successfully.")

    except Exception as e:
        logging.error(e)
        sys.exit(1)


def options_handler(args=None):
    install_logging("Override_content_validations.log", logger=logging)
    parser = argparse.ArgumentParser(
        description="Validations for override-content pipeline. " "Docs: <confluence link>"  # TODO
    )
    parser.add_argument("--paths", required=False, nargs="?", help="A list of content item paths to override.")
    parser.add_argument("--packs", required=False, nargs="?", help="A list of packs to override.")
    parser.add_argument("--marketplace", required=True, help="The marketplace type of the tenant to upload to.")
    parser.add_argument("--tenant_ids", required=True, help="The tenant ids to upload to.")
    parser.add_argument("--env_type", required=True, help="The environment type to upload to.")
    options = parser.parse_args(args)

    return options


if __name__ == "__main__":
    coloredlogs.install(level="DEBUG", fmt="[%(levelname)s] - %(message)s")
    options = options_handler()
    run(options)
