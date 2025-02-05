### This script creates disposable tenants for our test builds.
### For more information, see the Confluence pages:
### https://confluence-dc.paloaltonetworks.com/pages/viewpage.action?spaceKey=DemistoContent&title=XSOAR-NG+-+Build+Machines
### https://confluence-dc.paloaltonetworks.com/display/DemistoContent/XSIAM+-+Build+Machines


import argparse
import contextlib
import getpass
import json
import logging
import os
import re
from collections import OrderedDict
from pathlib import Path

from Tests.scripts.common import string_to_bool
from Tests.scripts.infra.viso_api import DEFAULT_TTL, VisoAPI
from Tests.scripts.infra.xsoar_api import XsiamClient, XsoarClient
from Tests.scripts.utils.log_util import install_logging

CONTENT_TENANTS_GROUP_OWNER = os.getenv("CONTENT_TENANTS_GROUP_OWNER", "")
INSTANCE_NAME_PREFIX = "qa2-test-"
XSIAM_VERSION = "ga"
XSOAR_SAAS_DEMISTO_VERSION = "99.99.98"
FIELDS_TO_GET_FROM_VISO = ["fqdn", "xsoar_version"]
AGENT_NAME_DEFAULT_MESSAGE = "<ADD_AGENT_HOST_NAME_HERE>"
AGENT_IP_DEFAULT_MESSAGE = "<ADD_AGENT_HOST_IP_HERE>"


class FlowType:
    BUILD = "build"
    NIGHTLY = "nightly"
    UPLOAD = "upload"


BUILD_MACHINE_FLOWS = [FlowType.BUILD, FlowType.NIGHTLY, FlowType.UPLOAD]
FLOWS_WITH_AGENT = [FlowType.BUILD, FlowType.NIGHTLY]


def load_json_file(file_path: Path) -> dict:
    with contextlib.suppress(Exception):
        return json.loads(file_path.read_text())
    logging.error(f"Error loading JSON file at: {file_path}")
    return {}


def extract_xsoar_ng_version(version: str) -> str:
    """Extract the XSOAR NG version from the provided version string.
    E.g. master-v8.8.0-1436883-667f2e66 -> 8.8.0
    """
    if match_xsoar_version := re.search(r".-v(\d+\.\d+\.\d+)", version):
        return match_xsoar_version.group(1)
    return version


def prepare_outputs(
    tenants_lcaas_ids: list[str],
    tenants_info: list[dict],
    server_type: str = "",
    flow_type: str = "",
    enabled: bool = False,
) -> dict:
    """
    Prepare output information for created tenants.

    Args:
        tenants_lcaas_ids (list[str]): List of tenant lcaas IDs.
        tenants_info (list[dict]): List of tenant information dictionaries.
        server_type (str, optional): Type of server (XSIAM or XSOAR). Defaults to "".
        flow_type (str, optional): Type of flow. Defaults to "".

    Returns:
        dict: Dictionary containing prepared output information for each tenant.
    """
    outputs_info = {}
    dict_tenants_info = {item["lcaas_id"]: item for item in tenants_info}

    for tenant_id in tenants_lcaas_ids:
        tenant_info = dict_tenants_info.get(tenant_id, {})
        demisto_version = extract_xsoar_ng_version(tenant_info.get("xsoar_version", ""))
        instance_name = f"{INSTANCE_NAME_PREFIX}{tenant_id}"
        tenant_url = tenant_info.get("fqdn")
        outputs_info[instance_name] = {
            "ui_url": f"https://{tenant_url}/",
            "instance_name": instance_name,
            "base_url": f"https://api-{tenant_url}",
            "enabled": enabled,
            "flow_type": flow_type,
            "build_machine": flow_type.lower() in BUILD_MACHINE_FLOWS,
            "server_type": server_type,
        }
        if server_type == XsiamClient.SERVER_TYPE:
            outputs_info[instance_name].update({"xsiam_version": XSIAM_VERSION, "demisto_version": demisto_version})
            if flow_type.lower() in FLOWS_WITH_AGENT:
                outputs_info[instance_name].update(
                    {
                        "agent_host_name": AGENT_IP_DEFAULT_MESSAGE,
                        "agent_host_ip": AGENT_IP_DEFAULT_MESSAGE,
                    }
                )
        elif server_type == XsoarClient.SERVER_TYPE:
            outputs_info[instance_name].update(
                {
                    "xsoar_ng_version": demisto_version,
                    "demisto_version": XSOAR_SAAS_DEMISTO_VERSION,
                }
            )
    outputs_info = dict(sorted(outputs_info.items()))
    logging.debug(f"The outputs info:\n{json.dumps(outputs_info, indent=4)}")
    return outputs_info


def save_to_output_file(output_path: Path, output_data: dict) -> None:
    """
    Save the output data to a file, merging with existing data if present.

    This function attempts to load existing data from the specified output path,
    merges it with the new output data, sorts the combined data by server_type
    and flow_type, and then saves the result back to the file.

    Args:
        output_path (Path): The path to the output file.
        output_data (dict): The new data to be saved.

    Raises:
        json.JSONDecodeError: If there's an error decoding existing JSON data.
        Exception: For any unexpected errors during the process.
    """
    logging.debug(f"Attempting to save output data to: {output_path}")

    try:
        existing_data = {}
        if output_path.exists():
            logging.debug(f"Loaded existing data from: {output_path}")
            existing_data = load_json_file(output_path)
        else:
            logging.debug(f"No existing data found at: {output_path}, starting fresh.")

        existing_data.update(output_data)
        sorted_output_data = OrderedDict(
            sorted(
                existing_data.items(),
                key=lambda item: (item[1]["server_type"], item[1]["flow_type"]),
            )
        )

        with open(output_path, "w") as f:
            json.dump(sorted_output_data, f, indent=4)
        logging.info(f"Output data successfully saved to: {output_path}")

    except json.JSONDecodeError:
        logging.error(f"Error decoding JSON from file: {output_path}. The file may be corrupted.")
    except Exception as e:
        logging.error(f"Unexpected error occurred: {e}")


def options_handler() -> argparse.Namespace:
    install_logging("Create_disposable_tenants.log", logger=logging)
    parser = argparse.ArgumentParser(description="Script to create a disposable tenants.")
    parser.add_argument(
        "-c",
        "--count",
        type=int,
        required=False,
        help="The number of disposable tenants to create.",
        default=1,
    )
    parser.add_argument(
        "--server-type",
        required=True,
        choices=[XsoarClient.SERVER_TYPE, XsiamClient.SERVER_TYPE],
        help="The type of server to create the tenant for (XSOAR or XSIAM).",
    )
    parser.add_argument(
        "-o",
        "--output-path",
        required=True,
        type=Path,
        help="The path to write the output file to.",
    )
    parser.add_argument(
        "--versions-file-path",
        required=False,
        type=Path,
        help="The path to the file containing the server versions.",
    )
    parser.add_argument(
        "--owner", default=getpass.getuser(), help="The owner of the disposable tenants. Default: the current user."
    )
    parser.add_argument(
        "--flow-type",
        help="The flow type for the disposable tenants.",
        default="",
    )
    parser.add_argument(
        "--ttl",
        help="The TTL (Time-to-Live) in hours for the disposable tenants (1-420).",
        default=DEFAULT_TTL,
    )
    parser.add_argument(
        "--enabled",
        help="Is the disposable tenant enabled or not.",
        default=False,
        type=string_to_bool,
    )

    return parser.parse_args()


def main() -> None:
    args = options_handler()

    count = args.count
    server_type = args.server_type
    flow_type = args.flow_type
    try:
        VISO_API_URL = os.environ["VISO_API_URL"]
        VISO_API_KEY = os.environ["VISO_API_KEY"]
        viso_api = VisoAPI(base_url=VISO_API_URL, api_key=VISO_API_KEY)

        versions = {}
        if args.versions_file_path:
            versions = load_json_file(args.versions_file_path).get(server_type, {})

        logging.info(f"Starting to create {count} disposable tenants, for {server_type=} and {flow_type=} with {versions=}")
        tenants_lcaas_ids = []
        for i in range(1, count + 1):
            try:
                tenant_lcaas_id = viso_api.create_disposable_tenant(
                    owner=args.owner,
                    group_owner=CONTENT_TENANTS_GROUP_OWNER,
                    server_type=server_type,
                    viso_version=versions.get("viso_version", ""),
                    frontend_version=versions.get("frontend_version", ""),
                    backend_version=versions.get("backend_version", ""),
                    xsoar_version=versions.get("xsoar_version", ""),
                    pipeline_version=versions.get("pipeline_version", ""),
                    storybuilder_version=versions.get("storybuilder_version", ""),
                    rocksdb_version=versions.get("rocksdb_version", ""),
                    scortex_version=versions.get("scortex_version", ""),
                    vsg_version=versions.get("vsg_version", ""),
                    ttl=args.ttl,
                )["lcaas_id"]
                tenants_lcaas_ids.append(tenant_lcaas_id)
                logging.info(f"Created {i}/{count} disposable tenants with LCAAS ID: {tenant_lcaas_id}")
            except Exception as e:
                logging.error(f"Failed to create disposable tenant: {e}")

        tenants_info = viso_api.get_all_tenants(group_owner=CONTENT_TENANTS_GROUP_OWNER, fields=FIELDS_TO_GET_FROM_VISO)
        outputs = prepare_outputs(tenants_lcaas_ids, tenants_info, server_type, flow_type, args.enabled)
        save_to_output_file(args.output_path, outputs)
    except Exception as e:
        logging.error(f"Unexpected error occurred while running the script: {e}")


if __name__ == "__main__":
    main()
