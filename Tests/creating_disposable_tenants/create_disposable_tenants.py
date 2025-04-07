### This script creates disposable tenants for our test builds.
### For more information, see the Confluence pages:
### https://confluence-dc.paloaltonetworks.com/pages/viewpage.action?spaceKey=DemistoContent&title=XSOAR-NG+-+Build+Machines
### https://confluence-dc.paloaltonetworks.com/display/DemistoContent/XSIAM+-+Build+Machines


import argparse
import getpass
import json
import logging
import os
import re
import sys
from collections import OrderedDict, defaultdict
from distutils.util import strtobool
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from slack_sdk import WebClient

from Tests.scripts.common import string_to_bool
from Tests.scripts.gitlab_basic_slack_notifier import build_link_to_message
from Tests.scripts.infra.viso_api import DEFAULT_TTL, VisoAPI
from Tests.scripts.infra.xsoar_api import XsiamClient, XsoarClient
from Tests.scripts.utils.log_util import install_logging

load_dotenv()

CONTENT_TENANTS_GROUP_OWNER = os.getenv("CONTENT_TENANTS_GROUP_OWNER", "")
CONTENT_GITLAB_CI = bool(strtobool(os.getenv("CONTENT_GITLAB_CI", "true")))
NEW_TENANTS_INFO_PATH = os.getenv("NEW_TENANTS_INFO_PATH", "new_tenants_info.json")
VERSIONS_FILE_PATH = os.getenv("VERSIONS_FILE_PATH")

SLACK_TOKEN = os.getenv("SLACK_TOKEN", "")
SLACK_WORKSPACE_NAME = os.getenv("SLACK_WORKSPACE_NAME", "")
PIPELINE_SLACK_CHANNEL = os.getenv("PIPELINE_SLACK_CHANNEL")
THREAD_TS = os.getenv("THREAD_TS")

INSTANCE_NAME_PREFIX = "qa2-test-"
XSIAM_VERSION = "ga"
XSOAR_SAAS_DEMISTO_VERSION = "99.99.98"
FIELDS_TO_GET_FROM_VISO = ["fqdn", "xsoar_version"]
AGENT_NAME_DEFAULT_MESSAGE = "<ADD_AGENT_HOST_NAME_HERE>"
AGENT_IP_DEFAULT_MESSAGE = "<ADD_AGENT_HOST_IP_HERE>"
SERVER_TYPES = [XsoarClient.SERVER_TYPE, XsiamClient.SERVER_TYPE]

MAX_TTL = 144  # hours


class FlowType:
    BUILD = "build"
    NIGHTLY = "nightly"
    UPLOAD = "upload"


BUILD_MACHINE_FLOWS = [FlowType.BUILD, FlowType.NIGHTLY, FlowType.UPLOAD]
FLOWS_WITH_AGENT = [FlowType.BUILD, FlowType.NIGHTLY]


def get_invalid_args(
    viso_api: VisoAPI,
    count_per_type: int,
    total_count: int,
    server_type: str,
    versions_file_path: Path | None,
    ttl: int,
    owner: str,
) -> list[str]:
    errors = []
    if (available_tokens := viso_api.get_available_tokens_for_group(CONTENT_TENANTS_GROUP_OWNER)) < total_count:
        errors.append(
            f"Insufficient tokens available. {total_count} tenants requested, but only {available_tokens} tokens available."
        )
    if count_per_type <= 0:
        errors.append("count_per_type must be a positive integer")
    if server_type not in SERVER_TYPES:
        errors.append(f"server_type must be either {' or '.join(SERVER_TYPES)}")
    if ttl < 1 or ttl > MAX_TTL:
        errors.append(f"TTL value must be between 1 and {MAX_TTL} hours")
    if versions_file_path:
        if not versions_file_path.exists():
            errors.append(f"Versions file not found at {versions_file_path.as_posix()}")
        else:
            try:
                json.loads(versions_file_path.read_text())
            except (json.JSONDecodeError, UnicodeDecodeError):
                errors.append(f"Error parsing versions file at {versions_file_path.as_posix()}")
    if not owner and CONTENT_GITLAB_CI:
        errors.append("Owner must be provided if running in GitLab CI")
    return errors


def extract_xsoar_ng_version(version: str) -> str:
    """Extract the XSOAR NG version from the provided version string.
    E.g. master-v8.8.0-1436883-667f2e66 -> 8.8.0
    """
    if match_xsoar_version := re.search(r".-v(\d+\.\d+\.\d+)", version):
        return match_xsoar_version.group(1)
    return version


def prepare_outputs(
    new_tenants_info: dict[str, list[str]],
    tenants_info: list[dict],
    server_type: str = "",
    enabled: bool = False,
) -> dict[str, dict[str, Any]]:
    """
    Prepare output information for created tenants.

    Args:
        new_tenants_info (dict[str, list[str]]):
            Dictionary that maps the flow type (e.g., 'build', 'nightly', 'upload') to a list of
            tenant IDs for which new tenants were created.
        tenants_info (list[dict]): List of tenant information dictionaries.
        server_type (str, optional): Type of server (XSIAM or XSOAR). Defaults to "".
        enabled (bool, optional): Whether the tenant is enabled. Defaults to False.

    Returns:
        dict: Dictionary containing prepared output information for each tenant.
    """
    outputs_info = {}
    dict_tenants_info = {item["lcaas_id"]: item for item in tenants_info}

    for flow_type, tenant_ids in new_tenants_info.items():
        for tenant_id in tenant_ids:
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
                            "agent_host_name": AGENT_NAME_DEFAULT_MESSAGE,
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
            existing_data = json.loads(output_path.read_text())
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


def send_slack_notification(color: str, title: str, text: str = "", title_link: str = "") -> None:
    """
    Send a Slack notification with the output data.

    Args:
        color (str): The color to be used for the Slack attachment.
        title (str): The title of the Slack attachment.
        text (str, optional): The text to be included in the Slack attachment.
        title_link (str, optional): The URL to be used as the title link for the Slack attachment. Defaults to an empty string.

    Raises:
        Exception: For any errors during the Slack notification process.
    """
    required_env = (PIPELINE_SLACK_CHANNEL, SLACK_TOKEN)
    if all(required_env):
        try:
            slack_client = WebClient(token=SLACK_TOKEN)
            response = slack_client.chat_postMessage(
                channel=PIPELINE_SLACK_CHANNEL,
                thread_ts=THREAD_TS,
                attachments=[
                    {
                        "color": color,
                        "title": title,
                        "fallback": title,
                        "text": text,
                        "title_link": title_link,
                    }
                ],
                link_names=True,
            )
            link = build_link_to_message(response)
            logging.info(
                f"Successfully sent Slack message to channel {PIPELINE_SLACK_CHANNEL}." f" Message link: {link}" if link else ""
            )
        except Exception as e:
            logging.error(f"Error sending Slack notification: {e}")
    else:
        logging.info("Skipping Slack notification due to missing configuration.")


def options_handler() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Script to create a disposable tenants.")
    parser.add_argument(
        "-c",
        "--count-per-type",
        type=int,
        required=False,
        help="The number of disposable tenants to create.",
        default=1,
    )
    parser.add_argument(
        "--server-type",
        required=True,
        choices=SERVER_TYPES,
        help="The type of server to create the tenant for (XSOAR or XSIAM).",
    )
    parser.add_argument(
        "-o",
        "--output-path",
        type=Path,
        help="The path to write the output file to.",
        default=NEW_TENANTS_INFO_PATH,
    )
    parser.add_argument(
        "--versions-file-path",
        required=False,
        type=Path,
        help="The path to the file containing the server versions.",
        default=VERSIONS_FILE_PATH,
    )
    parser.add_argument(
        "--owner",
        help="The owner of the disposable tenants. Default: the current user.",
    )
    parser.add_argument(
        "--flow-types",
        help="The flow type for the disposable tenants. Can be one or more.",
        default="",
    )
    parser.add_argument(
        "--ttl", help=f"The TTL (Time-to-Live) in hours for the disposable tenants (1-{MAX_TTL}).", default=DEFAULT_TTL, type=int
    )
    parser.add_argument(
        "--enabled",
        help="Is the disposable tenant enabled or not.",
        default=False,
        type=string_to_bool,
    )

    return parser.parse_args()


def main() -> None:
    install_logging("Create_disposable_tenants.log", logger=logging)
    try:
        load_dotenv()
        args = options_handler()
        owner: str = args.owner
        count_per_type: int = args.count_per_type
        server_type: str = args.server_type
        flow_types: list[str] = args.flow_types.split(",")
        versions_file_path: Path | None = args.versions_file_path
        ttl: int = args.ttl
        total_count: int = count_per_type * len(flow_types)
        VISO_API_URL = os.environ["VISO_API_URL"]
        VISO_API_KEY = os.environ["VISO_API_KEY"]
        viso_api = VisoAPI(base_url=VISO_API_URL, api_key=VISO_API_KEY)

        if invalid_args := get_invalid_args(
            viso_api=viso_api,
            count_per_type=count_per_type,
            total_count=total_count,
            server_type=server_type,
            versions_file_path=versions_file_path,
            ttl=ttl,
            owner=owner,
        ):
            logging.error(f"The following errors were found in the input arguments:\n- {f'{os.linesep}- '.join(invalid_args)}")
            send_slack_notification(
                "danger", "Error creating disposable tenants, invaid arguments", "\n".join("• " + arg for arg in invalid_args)
            )
            sys.exit(1)
        versions = {}
        if versions_file_path:
            versions = json.loads(versions_file_path.read_text()).get("types", {}).get(server_type, {})
        logging.info(
            f"Starting to create total of {total_count} disposable tenants, "
            f"for {server_type=} and flow_types={', '.join(flow_types)} with {versions=}"
        )
        new_tenants_info = defaultdict(list)
        pairs = [(flow_type, i) for flow_type in flow_types for i in range(1, count_per_type + 1)]
        is_error = False
        owner = owner or getpass.getuser()
        for total, (flow_type, _) in enumerate(pairs, start=1):
            try:
                tenant_lcaas_id = viso_api.create_disposable_tenant(
                    owner=owner,
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
                    ttl=ttl,
                )["lcaas_id"]
                new_tenants_info[flow_type].append(tenant_lcaas_id)
                logging.info(
                    f"Created {total}/{total_count} disposable tenants for {flow_type=} with LCAAS ID: {tenant_lcaas_id}"
                )
            except Exception as e:
                is_error = True
                logging.error(f"Failed to create disposable tenant {total}/{total_count} for {flow_type=}:\n{e}")

        tenants_info = viso_api.get_all_tenants(group_owner=CONTENT_TENANTS_GROUP_OWNER, fields=FIELDS_TO_GET_FROM_VISO)
        if outputs := prepare_outputs(new_tenants_info, tenants_info, server_type, args.enabled):
            save_to_output_file(args.output_path, outputs)
        if is_error:
            send_slack_notification(
                "danger", "Error creating disposable tenants", f"Failed to create {total_count} disposable tenants."
            )
            sys.exit(1)
        send_slack_notification(
            "good",
            "Successfully created disposable tenants",
            f"Created {total_count} disposable tenants.\n{os.linesep.join(map(lambda tenant: f'• {tenant}', outputs))}",
        )
    except Exception as e:
        logging.exception(f"Unexpected error occurred while running the script:\n{e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
