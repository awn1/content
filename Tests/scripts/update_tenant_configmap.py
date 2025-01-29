### This script updates the XSOAR feature flags configmap in the Viso cluster.
### For more information, see the Confluence pages:
### https://confluence-dc.paloaltonetworks.com/pages/viewpage.action?spaceKey=DemistoContent&title=XSOAR-NG+-+Build+Machines
### https://confluence-dc.paloaltonetworks.com/display/DemistoContent/XSIAM+-+Build+Machines


import argparse
import contextlib
import json
import logging
import os
from pathlib import Path

from Tests.scripts.infra.resources.constants import COMMENT_FIELD_NAME
from Tests.scripts.infra.viso_api import VisoAPI
from Tests.scripts.infra.xsoar_api import XsiamClient, XsoarClient
from Tests.scripts.utils.log_util import install_logging

CONFIG_MAP_NAME = "configmap-xsoar-feature-flags"
BASE_MAP_DICT = {
    "CONTENT_PACK_VERIFY": "false",
    "CONTENT_PACK_BASE_DELETE_ALLOWED": "true",
    "VERSION_CONTROL_ENABLED": "false",
}
XSIAM_MAP_DICT = {
    "FORWARD_REQUEST_HEADER_TIMEOUT": "600",
    "FORWARD_REQUEST_TIMEOUT": "600",
    "EXTERNAL_CONTENT_INSTALLATION_POLLING": "10",
} | BASE_MAP_DICT
XSOAR_MARKETPLACE_BYPASS_URL = "marketplace-saas-dist-dev/upload-flow/builds-xsoar-ng/qa2-test-{lcaas_id}"
XSIAM_MARKETPLACE_BYPASS_URL = "marketplace-v2-dist-dev/upload-flow/builds-xsiam/qa2-test-{lcaas_id}"
SERVER_TYPE_TO_MAP_DICT = {
    XsoarClient.SERVER_TYPE: BASE_MAP_DICT,
    XsiamClient.SERVER_TYPE: XSIAM_MAP_DICT,
}
MARKETPLACE_BOOTSTRAP_BYPASS_URL_KEY = "MARKETPLACE_BOOTSTRAP_BYPASS_URL"
SERVER_TYPE_TO_MARKETPLACE_BYPASS_URL = {
    XsoarClient.SERVER_TYPE: XSOAR_MARKETPLACE_BYPASS_URL,
    XsiamClient.SERVER_TYPE: XSIAM_MARKETPLACE_BYPASS_URL,
}


def load_json_file(file_path: Path) -> dict:
    with contextlib.suppress(Exception):
        return json.loads(file_path.read_text())
    logging.error(f"Error loading JSON file at: {file_path}")
    return {}


def options_handler() -> argparse.Namespace:
    install_logging("Update_tenant_config_map.log")
    parser = argparse.ArgumentParser(description="Script to update the tenant config map.")
    parser.add_argument(
        "--tenates-file-path",
        required=True,
        type=Path,
        help="The path to the file containing the tenants info.",
    )

    return parser.parse_args()


def main() -> None:
    args = options_handler()

    try:
        VISO_API_URL = os.environ["VISO_API_URL"]
        VISO_API_KEY = os.environ["VISO_API_KEY"]
        viso_api = VisoAPI(base_url=VISO_API_URL, api_key=VISO_API_KEY)

        tenates_info = load_json_file(args.tenates_file_path)
        tenates_info.pop(COMMENT_FIELD_NAME, None)
        for tenant_id, tenant_data in tenates_info.items():
            logging.info(f"Updating config map for tenant: {tenant_id}")
            lcaas_id = tenant_id.split("-")[-1]
            server_type = tenant_data.get("server_type")
            map_dict = SERVER_TYPE_TO_MAP_DICT[server_type]
            if tenant_data.get("build_machine"):
                map_dict.update(
                    {
                        MARKETPLACE_BOOTSTRAP_BYPASS_URL_KEY: SERVER_TYPE_TO_MARKETPLACE_BYPASS_URL[server_type].format(
                            lcaas_id=lcaas_id
                        )
                    }
                )

            viso_api.update_config_map([lcaas_id], CONFIG_MAP_NAME, map_dict)
            logging.info(f"Successfully updated config map for tenant: {tenant_id}")

    except Exception as e:
        logging.error(f"Unexpected error occurred while running the script: {e}")


if __name__ == "__main__":
    main()
