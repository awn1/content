import argparse
import contextlib
import json
import logging
import os
import re
import warnings
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

import urllib3
from google.auth import _default  # noqa
from jinja2 import Environment, FileSystemLoader
from lock_cloud_machines import generate_tenant_token_map
from packaging.version import Version
from slack_sdk import WebClient
from urllib3.exceptions import InsecureRequestWarning

from SecretActions.google_secret_manager_handler import GoogleSecreteManagerModule, SecretLabels
from SecretActions.SecretsBuild.merge_and_delete_dev_secrets import delete_dev_secrets
from Tests.scripts.common import join_list_by_delimiter_in_chunks, load_json_file, string_to_bool
from Tests.scripts.graph_lock_machine import (
    AVAILABLE_MACHINES,
    BUILD_IN_QUEUE,
    LOCK_DURATION,
    create_available_machines_graph,
    create_builds_waiting_in_queue_graph,
    create_lock_duration_graph,
)
from Tests.scripts.infra.resources.constants import AUTOMATION_GCP_PROJECT, COMMENT_FIELD_NAME, GSM_SERVICE_ACCOUNT
from Tests.scripts.utils.slack import (
    get_conversations_members_slack,
    get_messages_from_slack,
    get_slack_usernames_from_ids,
)

urllib3.disable_warnings(InsecureRequestWarning)
warnings.filterwarnings("ignore", _default._CLOUD_SDK_CREDENTIALS_WARNING)  # noqa

from Tests.scripts.infra.settings import Settings, XSOARAdminUser  # noqa
from Tests.scripts.infra.viso_api import VisoAPI  # noqa
from Tests.scripts.infra.xsoar_api import XsoarClient, XsiamClient, SERVER_TYPE_TO_CLIENT_TYPE, InvalidAPIKey  # noqa
from Tests.scripts.machines import (  # noqa
    get_viso_tenants_data,
    NOT_AVAILABLE,
    generate_version_cell_css_class,
    generate_records,
    get_record_display,
    generate_columns,
)

"""
This script is in charge of updating the build machine report.
In order to run the script locally authenticate to gcloud with `gcloud auth application-default login`.

Running this script without the correct configuration may delete secrets from the GSM.
Consider using dry run argument --without-viso=true.

In order to run locally use the artifact generated from the previous runs called records.json.
This may be entered to the test_data parameter of the script instead of creating real time records.
"""
ARTIFACTS_FOLDER = os.environ["ARTIFACTS_FOLDER"]
GITLAB_ARTIFACTS_URL = os.environ["GITLAB_ARTIFACTS_URL"]
CI_JOB_ID = os.environ["CI_JOB_ID"]
SLACK_TOKEN = os.getenv("SLACK_TOKEN")
XDR_PERMISSIONS_DEV = os.environ["XDR_PERMISSIONS_DEV"]
XDR_UPGRADE_CHANNEL_DEV = os.environ["XDR_UPGRADE_CHANNEL_DEV"]
DMST_CONTENT_TEAM_ID = os.environ["DMST_CONTENT_TEAM_ID"]
PERMISSION_ROLE = os.environ.get("PERMISSION_ROLE", "cortex-operator-data-access")
WITHOUT_VISO = os.getenv("WITHOUT_VISO")
WITHOUT_STATISTICS = os.getenv("WITHOUT_STATISTICS")
WITHOUT_MISSING_NAME_MAPPING = os.getenv("WITHOUT_MISSING_NAME_MAPPING")
WAIT_IN_LINE_CHANNEL_ID: str = os.environ["WAIT_IN_LINE_CHANNEL_ID"]
CONTENT_TENANTS_GROUP_OWNER = os.getenv("CONTENT_TENANTS_GROUP_OWNER")
TOKENS_COUNT_PERCENTAGE_THRESHOLD_WARNING_DEFAULT = 80  # % of the disposable tenants tokens usage to raise a warning.
TOKENS_COUNT_PERCENTAGE_THRESHOLD_ERROR_DEFAULT = 90  # % of the disposable tenants tokens usage to raise an error.
TOKENS_COUNT_PERCENTAGE_THRESHOLD_WARNING = int(
    os.getenv("TOKENS_COUNT_PERCENTAGE_THRESHOLD_WARNING", TOKENS_COUNT_PERCENTAGE_THRESHOLD_WARNING_DEFAULT)
)
TOKENS_COUNT_PERCENTAGE_THRESHOLD_ERROR = int(
    os.getenv("TOKENS_COUNT_PERCENTAGE_THRESHOLD_ERROR", TOKENS_COUNT_PERCENTAGE_THRESHOLD_ERROR_DEFAULT)
)
MAX_OWNERS_TO_NOTIFY_DISPLAY = 5
MAX_SERVER_VERSIONS_DISPLAY = 3
BUILD_MACHINES_FLOW_REQUIRING_AN_AGENT = {XsiamClient.PLATFORM_TYPE: ["build", "nightly"]}
RECORDS_FILE_NAME = "records.json"
WAIT_IN_LINE_SLACK_MESSAGES_FILE_NAME = "wait_in_line_slack_messages.json"
IGNORED_FLOW_TYPES = [
    "build-test-xsiam",  # Research team machines.
]


def create_report_html(
    current_date: str,
    records: list[dict],
    columns: list[dict],
    columns_filterable: list[int],
    managers: list[str],
    css_classes: dict[str, Any],
) -> str:
    template_path = Path(__file__).parent / "BuildMachines" / "templates"
    env = Environment(loader=FileSystemLoader(template_path))
    template = env.get_template("ReportTemplate.html")
    logging.info("Successfully loaded template.")
    report_title = f"Build Machines Report - {current_date}"
    content = template.render(
        records=records,
        report_title=report_title,
        columns_json=json.dumps(columns),
        columns=columns,
        columns_filterable=columns_filterable,
        managers=managers,
        css_classes=css_classes,
        xdr_permissions_dev=XDR_PERMISSIONS_DEV,
        xdr_upgrade_channel_dev=XDR_UPGRADE_CHANNEL_DEV,
        permission_role=PERMISSION_ROLE,
    )
    logging.info("Successfully rendered report.")
    return content


def options_handler() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Script to generate a report for the build machines.")
    parser.add_argument("--cloud_servers_path", help="Path to secret cloud server metadata file.")
    parser.add_argument("-o", "--output-path", required=True, help="The path to save the report to.")
    parser.add_argument("-n", "--name-mapping_path", help="Path to name mapping file.", required=False)
    parser.add_argument(
        "-t",
        "--test-data",
        help="Use test data and don't connect to the servers.",
        required=False,
    )
    parser.add_argument(
        "-wv",
        "--without-viso",
        type=string_to_bool,
        default=WITHOUT_VISO,
        help="Don't connect to Viso to get tenants data.",
        required=False,
    )
    parser.add_argument(
        "-ws",
        "--without-statistics",
        type=string_to_bool,
        default=WITHOUT_STATISTICS,
        help="Don't generate statistics.",
        required=False,
    )
    parser.add_argument(
        "-wmm",
        "--without-missing-name-mapping",
        type=string_to_bool,
        default=WITHOUT_MISSING_NAME_MAPPING,
        help="Don't report missing names from mapping.",
        required=False,
    )
    return parser.parse_args()


def remove_keys_without_tenant(all_tenant_lcaas_id: set[str]) -> set[str]:
    gsm_service_account = str(GSM_SERVICE_ACCOUNT) if GSM_SERVICE_ACCOUNT else None
    secret_conf = GoogleSecreteManagerModule(gsm_service_account, AUTOMATION_GCP_PROJECT)
    tenants_secrets = secret_conf.list_secrets_metadata_by_query(query=secret_conf.filter_label_is_set(SecretLabels.MACHINE))
    logging.info(f"Got {len(tenants_secrets)} tenant's API keys from GSM.")
    all_tenant_with_api_keys = {Path(s.name).name for s in tenants_secrets}
    keys_without_tenant = all_tenant_with_api_keys.difference(all_tenant_lcaas_id)
    logging.info(f"Found {len(keys_without_tenant)} tenants in GSM that don't exist in VISO, deleting those keys from GSM.")
    delete_dev_secrets(keys_without_tenant, secret_conf, AUTOMATION_GCP_PROJECT)
    return keys_without_tenant


def join_list_with_ellipsis(items: Iterable[str], max_items: int) -> str:
    items_list = list(items)
    return f"{', '.join(items_list[:max_items])}{' ...' if len(items_list) > max_items else ''}"


def extract_full_version(version_string: str) -> Version | None:
    # Extract version from "vA.B.C-D" pattern to A.B.C.D
    if match := re.search(r"v([\d.]+)-(\d+)", version_string):
        return Version(f"{match.group(1)}.{match.group(2)}")

    logging.error(f"{version_string} was not extracted properly as a valid version")
    return None


def generate_report(
    client: WebClient,
    without_viso: bool,
    without_missing_name_mapping: bool,
    name_mapping: dict,
    records: list,
    tenants: dict,
    tokens_count: int | None,
    keys_without_tenant: set[str] | None,
) -> tuple[list[str], dict[str, Any], list[dict]]:
    slack_msg_append: list[dict[Any, Any]] = []
    managers: list[Any] = name_mapping.get("managers", [])
    disabled_machines_count = set()
    non_connectable_machines_count = set()
    tenant_status_invalid_state_count = set()
    stop_status_invalid_state_count = set()
    ttl_expired_count = set()
    invalid_api_key_ttl_count = set()
    licenses_expired_count = set()
    owners_to_machines: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    platform_type_to_flow_type_to_server_versions: dict[str, dict[str, dict[str, int]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(int))
    )
    build_machines_requiring_an_agent = defaultdict(set)
    for record in records:
        machine_name = get_record_display(record, "machine_name")
        platform_type = get_record_display(record, "platform_type")
        flow_type = get_record_display(record, "flow_type")
        # checking the TTL, enabled and connectable only for build machines.
        if get_record_display(record, "build_machine", True):
            platform_type_to_flow_type_to_server_versions[platform_type][flow_type][get_record_display(record, "version")] += 1
            if not get_record_display(record, "enabled", True) and flow_type not in IGNORED_FLOW_TYPES:
                disabled_machines_count.add(machine_name)
            if not get_record_display(record, "connectable", True):
                non_connectable_machines_count.add(machine_name)
            if record.get("ttl", {}).get("expired"):
                ttl_expired_count.add(machine_name)
            if record.get("api_key_ttl", {}).get("invalid") or record.get("api_key_ttl", {}).get("expired"):
                invalid_api_key_ttl_count.add(machine_name)
            if record.get("tenant_status", {}).get("invalid"):
                tenant_status_invalid_state_count.add(machine_name)
            if record.get("stop_status", {}).get("invalid"):
                stop_status_invalid_state_count.add(machine_name)
            for value in record.values():
                if value.get("field_type") == "license" and value.get("expired"):
                    licenses_expired_count.add(machine_name)
            if (
                get_record_display(record, "agent_host_name", NOT_AVAILABLE) == NOT_AVAILABLE
                and platform_type in BUILD_MACHINES_FLOW_REQUIRING_AN_AGENT
                and flow_type in BUILD_MACHINES_FLOW_REQUIRING_AN_AGENT[platform_type]
            ):
                build_machines_requiring_an_agent[flow_type].add(machine_name)
        if not without_viso:
            # Count the number of machines per owner per machine type, only if they don't have a flow type.
            owner = get_record_display(record, "owner")
            flow_type = get_record_display(record, "flow_type")
            if owner != NOT_AVAILABLE and flow_type == NOT_AVAILABLE:
                owners_to_machines[owner][platform_type] += 1
    # Notify owners that have more than one machine per product type.
    owners_to_notify = set()
    for owner, product_types in owners_to_machines.items():
        for product_type, machines_count in product_types.items():
            if machines_count > 1:
                owners_to_notify.add(owner)
                break
    if owners_to_notify:
        owners_to_notify_str = join_list_with_ellipsis(map(lambda o: f"@{o}", owners_to_notify), MAX_OWNERS_TO_NOTIFY_DISPLAY)
        title = f"Owners with multiple machines: {owners_to_notify_str}"
        slack_msg_append.append(
            {
                "color": "warning",
                "title": title,
                "fallback": title,
            }
        )
    if non_connectable_machines_count:
        title = f"Build Machines - Non connectable:{len(non_connectable_machines_count)}"
        slack_msg_append.append(
            {
                "color": "danger",
                "title": title,
                "fallback": title,
                "fields": [
                    {
                        "title": f"Machine Name(s){'' if i == 0 else ' - Continued'}",
                        "value": chunk,
                        "short": False,
                    }
                    for i, chunk in enumerate(join_list_by_delimiter_in_chunks(non_connectable_machines_count))
                ],
            }
        )
    if disabled_machines_count:
        title = f"Build Machines - Disabled:{len(disabled_machines_count)}"
        slack_msg_append.append(
            {
                "color": "warning",
                "title": title,
                "fallback": title,
                "fields": [
                    {
                        "title": f"Machine Name(s){'' if i == 0 else ' - Continued'}",
                        "value": chunk,
                        "short": False,
                    }
                    for i, chunk in enumerate(join_list_by_delimiter_in_chunks(disabled_machines_count))
                ],
            }
        )
    if ttl_expired_count:
        title = f"Build Machines - With Expired TTL:{len(ttl_expired_count)}"
        slack_msg_append.append(
            {
                "color": "danger",
                "title": title,
                "fallback": title,
                "fields": [
                    {
                        "title": f"Machine Name(s){'' if i == 0 else ' - Continued'}",
                        "value": chunk,
                        "short": False,
                    }
                    for i, chunk in enumerate(join_list_by_delimiter_in_chunks(ttl_expired_count))
                ],
            }
        )
    if invalid_api_key_ttl_count:
        title = f"Build Machines - With Invalid/Expired API Key:{len(invalid_api_key_ttl_count)}"
        slack_msg_append.append(
            {
                "color": "danger",
                "title": title,
                "fallback": title,
                "fields": [
                    {
                        "title": f"Machine Name(s){'' if i == 0 else ' - Continued'}",
                        "value": chunk,
                        "short": False,
                    }
                    for i, chunk in enumerate(join_list_by_delimiter_in_chunks(invalid_api_key_ttl_count))
                ],
            }
        )

    if tenant_status_invalid_state_count:
        title = f"Build Machines - With Invalid Tenant Status:{len(tenant_status_invalid_state_count)}"
        slack_msg_append.append(
            {
                "color": "danger",
                "title": title,
                "fallback": title,
                "fields": [
                    {
                        "title": f"Machine Name(s){'' if i == 0 else ' - Continued'}",
                        "value": chunk,
                        "short": False,
                    }
                    for i, chunk in enumerate(join_list_by_delimiter_in_chunks(tenant_status_invalid_state_count))
                ],
            }
        )

    if stop_status_invalid_state_count:
        title = f"Build Machines - With Invalid Stop Status:{len(stop_status_invalid_state_count)}"
        slack_msg_append.append(
            {
                "color": "danger",
                "title": title,
                "fallback": title,
                "fields": [
                    {
                        "title": f"Machine Name(s){'' if i == 0 else ' - Continued'}",
                        "value": chunk,
                        "short": False,
                    }
                    for i, chunk in enumerate(join_list_by_delimiter_in_chunks(stop_status_invalid_state_count))
                ],
            }
        )

    if keys_without_tenant:
        title = f"Build Machines - API Keys Without Tenant:{len(keys_without_tenant)}"
        slack_msg_append.append(
            {
                "color": "warning",
                "title": title,
                "fallback": title,
                "fields": [
                    {
                        "title": f"Deleted API Key(s){'' if i == 0 else ' - Continued'}",
                        "value": chunk,
                        "short": False,
                    }
                    for i, chunk in enumerate(join_list_by_delimiter_in_chunks(keys_without_tenant))
                ],
            }
        )
    if licenses_expired_count:
        title = f"Build Machines - With Expired License:{len(licenses_expired_count)}"
        slack_msg_append.append(
            {
                "color": "danger",
                "title": title,
                "fallback": title,
                "fields": [
                    {
                        "title": f"Machine Name(s){'' if i == 0 else ' - Continued'}",
                        "value": chunk,
                        "short": False,
                    }
                    for i, chunk in enumerate(join_list_by_delimiter_in_chunks(licenses_expired_count))
                ],
            }
        )
    if build_machines_requiring_an_agent:
        build_machines_requiring_an_agent_count = 0
        fields = []
        for key, value in build_machines_requiring_an_agent.items():
            fields.append(
                {
                    "title": f"Flow Type - {key}",
                    "value": ", ".join(value),
                    "short": True,
                }
            )
            build_machines_requiring_an_agent_count += len(value)

        title = f"Build Machines - Requiring an Agent:{build_machines_requiring_an_agent_count}"
        slack_msg_append.append(
            {
                "color": "danger",
                "title": title,
                "fallback": title,
                "fields": fields,
            }
        )
    css_classes = {}
    if platform_type_to_flow_type_to_server_versions:
        platform_type_to_flow_type_to_server_versions_fields = []
        for platform_type, flow_type_to_server_versions in platform_type_to_flow_type_to_server_versions.items():
            for flow_type, server_versions in flow_type_to_server_versions.items():
                if flow_type in IGNORED_FLOW_TYPES:
                    continue

                versions_list = [
                    version for key in server_versions.keys() for version in [extract_full_version(key)] if version is not None
                ]

                if not versions_list:
                    title = f"Platform:{platform_type}, Flow type:{flow_type} - All tenants versions were not"
                    "parsed correctly for more information view the logs."
                    slack_msg_append.append(
                        {
                            "color": "danger",
                            "title": title,
                            "fallback": title,
                        }
                    )
                    css_class = generate_version_cell_css_class(NOT_AVAILABLE, platform_type, flow_type, with_prefix=True)
                    css_classes[css_class] = {"color": "red", "font_weight": "bold"}

                if len(server_versions) > 1:
                    platform_type_to_flow_type_to_server_versions_fields.append(
                        {
                            "title": f"Platform:{platform_type}, Flow type:{flow_type} Versions:{len(server_versions)}",
                            "value": join_list_with_ellipsis(server_versions, MAX_SERVER_VERSIONS_DISPLAY),
                            "short": True,
                        }
                    )
                # We assume here that the version with the highest version is the preferred version.
                for index, version in enumerate(sorted(versions_list, reverse=True)):
                    css_class = generate_version_cell_css_class(str(version), platform_type, flow_type, with_prefix=True)
                    css_classes[css_class] = {"color": "green" if index == 0 else "red", "font_weight": "bold"}

        if platform_type_to_flow_type_to_server_versions_fields:
            title = "Build Machines - Divergence in their versions"
            slack_msg_append.append(
                {
                    "color": "danger",
                    "title": title,
                    "fallback": title,
                    "fields": platform_type_to_flow_type_to_server_versions_fields,
                }
            )

    if tokens_count is not None:
        tokens_percentage = int((len(tenants) / tokens_count) * 100)
        title = f"Disposable Tenants Tokens - Total:{tokens_count}, Used:{len(tenants)}"
        if tokens_percentage >= TOKENS_COUNT_PERCENTAGE_THRESHOLD_ERROR:
            title += f", Usage >= {TOKENS_COUNT_PERCENTAGE_THRESHOLD_ERROR}%"
            color = "danger"
        elif tokens_percentage >= TOKENS_COUNT_PERCENTAGE_THRESHOLD_WARNING:
            title += f", Usage >= {TOKENS_COUNT_PERCENTAGE_THRESHOLD_WARNING}%"
            color = "warning"
        else:
            color = "good"
        slack_msg_append.append(
            {
                "color": color,
                "title": title,
                "fallback": title,
            }
        )

    if not without_missing_name_mapping and (missing_users_in_mapping := get_missing_users_in_mapping(client, name_mapping)):
        title = "Missing users in the name mapping"
        slack_msg_append.append(
            {
                "color": "warning",
                "title": title,
                "fallback": title,
                "fields": [
                    {
                        "title": "User(s)",
                        "value": ", ".join(map(lambda u: f"@{u}", missing_users_in_mapping)),
                        "short": True,
                    }
                ],
            }
        )
    return managers, css_classes, slack_msg_append


def filter_comment_field(record: dict) -> dict:
    return {k: v for k, v in record.items() if k != COMMENT_FIELD_NAME}


def get_missing_users_in_mapping(client: WebClient, name_mapping: dict) -> list[str]:
    try:
        members = get_conversations_members_slack(client, DMST_CONTENT_TEAM_ID)
        mapping_user_names = set(filter_comment_field(name_mapping.get("names", {})).values())
        ignored_user_names = set(filter_comment_field(name_mapping.get("ignored_names", {})).keys())
        slack_usernames = set(get_slack_usernames_from_ids(client, members).values())
        missing: list[str] = [name for name in (slack_usernames - mapping_user_names - ignored_user_names) if name is not None]
        logging.info(f"Missing users in the name mapping: {missing}")
        return missing
    except Exception:
        logging.exception("Failed to get slack members.")
    return []


def main() -> None:
    args = options_handler()
    output_path = Path(args.output_path)
    try:
        name_mapping: dict = load_json_file(args.name_mapping_path)  # type: ignore[assignment]
        logging.info("Successfully loaded name mapping.")
    except Exception:
        logging.exception("Failed to load name mapping.")
        name_mapping = {}

    client: WebClient = WebClient(token=SLACK_TOKEN)

    try:
        tenants, tokens_count, slack_msg_append, _ = get_viso_tenants_data(args.without_viso)
        tenant_token_map = generate_tenant_token_map(tenants_data=tenants)
        current_date = datetime.utcnow()  # noqa
        current_date_str = current_date.strftime("%Y-%m-%d")
        attachments_json = []
        wait_in_line_slack_messages: list = []
        keys_without_tenant = None

        if args.test_data:
            test_data_path = Path(args.test_data)
            records: list[dict] = load_json_file((test_data_path / RECORDS_FILE_NAME).as_posix())  # type: ignore[assignment]
            wait_in_line_slack_messages = load_json_file((test_data_path / WAIT_IN_LINE_SLACK_MESSAGES_FILE_NAME).as_posix())  # type: ignore[assignment]
        else:
            cloud_servers_path_json: dict = load_json_file(args.cloud_servers_path)  # type: ignore[assignment]
            records = generate_records(
                cloud_servers_path_json, Settings.xsoar_admin_user, tenants, args.without_viso, current_date, tenant_token_map
            )
            if not args.without_viso:
                keys_without_tenant = remove_keys_without_tenant(
                    {f"qa2-test-{tenant['lcaas_id']['display']}" for tenant in records}
                )
            # Save the records to a JSON file for future use and debugging.
            with open(output_path / RECORDS_FILE_NAME, "w") as f:
                json.dump(records, f, indent=4, default=str, sort_keys=True)

            if not args.without_statistics:
                wait_in_line_slack_messages = get_messages_from_slack(client, WAIT_IN_LINE_CHANNEL_ID)
                with open(output_path / WAIT_IN_LINE_SLACK_MESSAGES_FILE_NAME, "w") as f:
                    json.dump(
                        wait_in_line_slack_messages,
                        f,
                        indent=4,
                        default=str,
                        sort_keys=True,
                    )

        if args.without_statistics:
            logging.info("Skipping generating statistics.")
        else:
            logging.info("Generating statistics.")
            attachments_json = generate_graphs(output_path, wait_in_line_slack_messages)

        logging.info(f"Creating report for {current_date_str}")
        columns, columns_filterable = generate_columns(records, args.without_viso)

        managers, css_classes, slack_msg_append_report = generate_report(
            client,
            args.without_viso,
            args.without_missing_name_mapping,
            name_mapping,
            records,
            tenants,
            tokens_count,
            keys_without_tenant,
        )
        slack_msg_append.extend(slack_msg_append_report)

        report = create_report_html(current_date_str, records, columns, columns_filterable, managers, css_classes)
        report_file_name = f"Report_{current_date_str}.html"
        with open(output_path / report_file_name, "w") as report_file:
            report_file.write(report)

        with open(output_path / "index.html", "w") as index_html:
            index_html.write(report)

        with open(output_path / "slack_msg.txt", "w") as slack_msg_file:
            title = f"View report for {current_date_str}"
            report_url = f"{GITLAB_ARTIFACTS_URL}/{CI_JOB_ID}/artifacts/{ARTIFACTS_FOLDER}/{report_file_name}"
            json.dump(
                [
                    {
                        "color": "good",
                        "title": title,
                        "fallback": title,
                        "title_link": report_url,
                    }
                ]
                + slack_msg_append,
                slack_msg_file,
                indent=4,
                default=str,
                sort_keys=True,
            )

        with open(output_path / "slack_attachments.json", "w") as slack_attachments_file:
            slack_attachments_file.write(json.dumps(attachments_json, indent=4, default=str, sort_keys=True))

    except Exception as e:
        logging.exception(f"Failed to create report: {e}")
        with contextlib.suppress(Exception):
            with open(output_path / "slack_msg.txt", "w") as slack_msg_file:
                json.dump(
                    {
                        "title": "Build Machines Report Generation Failed",
                        "color": "danger",
                    },
                    slack_msg_file,
                    indent=4,
                    default=str,
                    sort_keys=True,
                )


def generate_graphs(output_path: Path, wait_in_line_slack_messages: list[str]) -> list[dict]:
    _, _, _, _, _, lock_duration_graph_file_name = create_lock_duration_graph(wait_in_line_slack_messages, output_path)
    _, _, _, _, _, available_machines_graph_file_name = create_available_machines_graph(wait_in_line_slack_messages, output_path)
    _, _, _, _, _, builds_waiting_in_queue_graph_file_name = create_builds_waiting_in_queue_graph(
        wait_in_line_slack_messages, output_path
    )
    attachments_json = [
        {
            "file": lock_duration_graph_file_name.as_posix(),
            "filename": lock_duration_graph_file_name.name,
            "title": LOCK_DURATION,
            "alt_txt": LOCK_DURATION,
        },
        {
            "file": available_machines_graph_file_name.as_posix(),
            "filename": available_machines_graph_file_name.name,
            "title": AVAILABLE_MACHINES,
            "alt_txt": AVAILABLE_MACHINES,
        },
        {
            "file": builds_waiting_in_queue_graph_file_name.as_posix(),
            "filename": builds_waiting_in_queue_graph_file_name.name,
            "title": BUILD_IN_QUEUE,
            "alt_txt": BUILD_IN_QUEUE,
        },
    ]
    return attachments_json


if __name__ == "__main__":
    logging.getLogger().setLevel(logging.INFO)
    logging.basicConfig(format="[%(levelname)-8s] [%(name)s] %(message)s")
    main()
