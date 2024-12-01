import argparse
import json
import logging
import sys
from pathlib import Path

import coloredlogs
import yaml

from Tests.scripts.utils.log_util import install_logging

YML_FILE_PACK_ID = ""
JSON_FILE_PACK_ID = ""
RED_PRINT = "\033[0m"


def extract_pack_id(file_path: str):
    file_path = Path(file_path)
    file_path_parts = file_path.parts
    return file_path_parts[1]


def update_yaml(pack_id: str, file_path: str):
    yaml_content = {"contentitemexportablefields": {"contentitemfields": {"packID": pack_id}}}

    with open(file_path, "a") as yaml_file:
        yaml.dump(yaml_content, yaml_file, default_flow_style=False, sort_keys=False)


def update_json(pack_id: str, file_path: str):
    with open(file_path) as file:
        data = json.load(file)

    data["PackID"] = pack_id

    with open(file_path, "w") as file:
        json.dump(data, file, indent=4)


def adding_pack_id_to_file(options: argparse.Namespace):
    paths = options.paths
    paths_list = paths.split(",")

    for path in paths_list:
        pack_id = extract_pack_id(path)
        logging.debug(f"Adding pack ID {pack_id} to the content item: {path}.")
        if path.endswith("yml"):
            update_yaml(pack_id, path)
        elif path.endswith("json"):
            update_json(pack_id, path)
        else:
            logging.debug(f"Failed to add a pack ID to the file {path}; it may not be installed on the tenant.")


def run(options: argparse.Namespace):
    try:
        logging.debug("Starting to add pack IDs to the content item files.")
        adding_pack_id_to_file(options)
        logging.debug("Finished adding pack IDs to the content item files.")

    except Exception as e:
        logging.error(e)
        sys.exit(1)


def options_handler(args=None):
    install_logging("Add_packID_to_content_items.log", logger=logging)
    parser = argparse.ArgumentParser(
        description="Validations for override-content pipeline. Docs: <confluence link>"  # TODO
    )
    parser.add_argument("--paths", required=True, help="A list of content item paths to override.")
    options = parser.parse_args(args)

    return options


if __name__ == "__main__":
    coloredlogs.install(level="DEBUG", fmt="[%(levelname)s] - %(message)s")
    options = options_handler()
    run(options)
