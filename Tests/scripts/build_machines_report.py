import argparse
import contextlib
import json
import logging
import os
import warnings
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List
from google.auth import _default  # noqa

import urllib3
from jinja2 import Environment, FileSystemLoader
from slack_sdk import WebClient
from urllib3.exceptions import InsecureRequestWarning

import common
from Tests.scripts.infra.resources.constants import AUTOMATION_GCP_PROJECT
from Tests.scripts.graph_lock_machine import (
    create_lock_duration_graph,
    create_available_machines_graph,
    create_builds_waiting_in_queue_graph,
    LOCK_DURATION,
    AVAILABLE_MACHINES,
    BUILD_IN_QUEUE,
)
from Tests.scripts.utils.slack import get_messages_from_slack

urllib3.disable_warnings(InsecureRequestWarning)
warnings.filterwarnings("ignore", _default._CLOUD_SDK_CREDENTIALS_WARNING)  # noqa

from Tests.scripts.infra.settings import Settings, XSOARAdminUser  # noqa
from Tests.scripts.infra.viso_api import VisoAPI  # noqa
from Tests.scripts.infra.xsoar_api import XsoarClient, XsiamClient  # noqa

ARTIFACTS_FOLDER = os.environ["ARTIFACTS_FOLDER"]
GITLAB_ARTIFACTS_URL = os.environ["GITLAB_ARTIFACTS_URL"]
CI_JOB_ID = os.environ["CI_JOB_ID"]
SLACK_WORKSPACE_NAME = os.getenv("SLACK_WORKSPACE_NAME", "")
XDR_PERMISSIONS_DEV = os.environ["XDR_PERMISSIONS_DEV"]
XDR_UPGRADE_CHANNEL_DEV = os.environ["XDR_UPGRADE_CHANNEL_DEV"]
XDR_UPGRADE_CHANNEL_ID_DEV = os.environ["XDR_UPGRADE_CHANNEL_ID_DEV"]
PERMISSION_ROLE = os.environ.get("PERMISSION_ROLE", "cortex-operator-data-access")
NOT_AVAILABLE = "N/A"
VISO_API_URL: str | None = os.getenv("VISO_API_URL")
VISO_API_KEY = os.getenv("VISO_API_KEY")
WITHOUT_VISO = os.getenv("WITHOUT_VISO")
SLACK_TOKEN = os.getenv("SLACK_TOKEN")
WAIT_IN_LINE_CHANNEL_ID: str = os.environ["WAIT_IN_LINE_CHANNEL_ID"]
CONTENT_TENANTS_GROUP_OWNER = os.getenv("CONTENT_TENANTS_GROUP_OWNER")
TTL_EXPIRED_DAYS_DEFAULT = 5
TTL_EXPIRED_DAYS = timedelta(days=int(os.getenv("TTL_EXPIRED_DAYS", TTL_EXPIRED_DAYS_DEFAULT)))
TOKENS_COUNT_PERCENTAGE_THRESHOLD_DEFAULT = 80  # % of the disposable tenants tokens usage to raise a warning.
TOKENS_COUNT_PERCENTAGE_THRESHOLD = int(os.getenv("TOKENS_COUNT_PERCENTAGE_THRESHOLD", TOKENS_COUNT_PERCENTAGE_THRESHOLD_DEFAULT))
MAX_OWNERS_TO_NOTIFY_DISPLAY = 5
BUILD_MACHINES_FLOW_REQUIRING_AN_AGENT = {XsiamClient.PLATFORM_TYPE: ["build", "nightly"]}
COMMENT_FIELD_NAME = "__comment__"
RECORDS_FILE_NAME = "records.json"
WAIT_IN_LINE_SLACK_MESSAGES_FILE_NAME = "wait_in_line_slack_messages.json"


def create_column(
    tenants: bool, key: str, data: str, exportable: bool, visible: bool, add_class: bool, filterable: bool, **kwargs
) -> dict:
    return {
        "tenants": tenants,
        "key": key,
        "data": data,
        "exportable": exportable,
        "visible": visible,
        "add_class": add_class,
        "filterable": filterable,
        **kwargs,
    }


def generate_columns(without_viso: bool) -> list[dict]:
    columns = [
        create_column(False, "", "", False, True, False, False, className="dt-control", orderable="false", defaultContent=""),
        create_column(False, "host", "Host", True, True, False, False),
        create_column(False, "machine_name", "Machine Name", True, True, False, False),
        create_column(False, "enabled", "Enabled", True, True, True, True),
        create_column(False, "flow_type", "Flow Type", True, True, True, True),
        create_column(False, "platform_type", "Platform Type", True, True, True, True),
        create_column(False, "version", "Server Version", True, True, True, True),
        create_column(False, "lcaas_id", "LCAAS ID", True, True, True, False),
        create_column(True, "ttl", "TTL", True, True, True, False),
        create_column(True, "owner", "Owner", True, False, True, True),
        create_column(True, "tenant_status", "Tenant Status", True, False, True, True),
        create_column(False, "build_machine", "Build Machine", True, False, True, True),
        create_column(False, "comment", "Comment", True, False, False, False),
        create_column(True, "disposable", "Disposable", True, False, True, True),
        create_column(False, "connectable", "Connectable", False, False, False, True),
        create_column(False, "agent_host_name", "Agent Host Name", True, False, True, False),
        create_column(False, "agent_host_ip", "Agent IP", True, False, True, False),
    ]
    if without_viso:
        return list(filter(lambda c: c["tenants"] is False, columns))
    return columns


def create_report_html(
    current_date: str, records: list[dict], columns: list[dict], columns_filterable: list[int], managers: list[str]
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
        xdr_permissions_dev=XDR_PERMISSIONS_DEV,
        xdr_upgrade_channel_dev=XDR_UPGRADE_CHANNEL_DEV,
        permission_role=PERMISSION_ROLE,
    )
    logging.info("Successfully rendered report.")
    return content


def options_handler() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Script to generate a report for the build machines.")
    parser.add_argument("--xsiam-json", type=str, action="store", required=True, help="Tenant json for xsiam tenants")
    parser.add_argument("--xsoar-ng-json", type=str, action="store", required=True, help="Tenant files for xsoar-ng tenants")
    parser.add_argument("-o", "--output-path", required=True, help="The path to save the report to.")
    parser.add_argument("-n", "--name-mapping_path", help="Path to name mapping file.", required=False)
    parser.add_argument("-t", "--test-data", help="Use test data and don't connect to the servers.", required=False)
    parser.add_argument(
        "-wv",
        "--without-viso",
        type=common.string_to_bool,
        default=WITHOUT_VISO,
        help="Don't connect to Viso to get tenants data.",
        required=False,
    )
    return parser.parse_args()


def generate_html_link(text: str, url: str) -> str:
    return f'<a href="{url}" target="_blank">{text}</a>'


def generate_cell(display: Any, sort: Any | None = None, column_class: str | None = None) -> dict:
    data = {
        "display": display,
        "sort": sort if sort is not None else display,
    }
    if column_class:
        data["column_class"] = column_class
    return data


def get_message_p_from_ts(ts: str) -> str:
    return f"p{ts.replace('.', '')}"


def build_link_to_channel(channel_id: str) -> str:
    return f"https://{SLACK_WORKSPACE_NAME}.slack.com/archives/{channel_id}" if SLACK_WORKSPACE_NAME else ""


def build_link_to_message(channel_id: str, message_ts: str) -> str:
    return f"{build_link_to_channel(channel_id)}/{message_ts}" if SLACK_WORKSPACE_NAME else ""


def get_datetime_from_epoch(epoch: str) -> datetime:
    return datetime.fromtimestamp(float(epoch))


def generate_ttl_class(expired: bool | None = None):
    return "expired" if expired else "ok" if expired is not None else "na"


def generate_ttl_cell(ttl: str, current_date: datetime) -> dict:
    ttl_date = get_datetime_from_epoch(ttl)
    expired = ttl_date <= current_date + TTL_EXPIRED_DAYS
    return generate_cell(ttl_date.strftime("%Y-%m-%dT%H-%M"), ttl_date.strftime("%Y-%m-%d"), generate_ttl_class(expired))


def tenant_status_has_error(status: str) -> bool:
    return "error" in status.lower()


def generate_tenant_status_cell(status: str) -> dict:
    return generate_cell(status, status, "error" if tenant_status_has_error(status) else "ok")


def get_record_for_tenant(tenant, current_date: datetime):
    if "thread_ts" in tenant:
        slack_link = build_link_to_message(XDR_UPGRADE_CHANNEL_ID_DEV, get_message_p_from_ts(tenant["thread_ts"]))
        slack_link_cell = generate_cell(generate_html_link("Slack thread", slack_link), tenant["thread_ts"])
    else:
        slack_link = build_link_to_channel(XDR_UPGRADE_CHANNEL_ID_DEV)
        slack_link_cell = generate_cell(generate_html_link("Upgrade Channel", slack_link), XDR_UPGRADE_CHANNEL_ID_DEV)
    return {
        "owner": generate_cell(tenant["owner"]),
        "disposable": generate_cell(tenant["disposable"]),
        "tenant_status": generate_tenant_status_cell(tenant["status"]),
        "viso_version": generate_cell(tenant["viso_version"]),
        "ttl": generate_ttl_cell(tenant["ttl"], current_date),
        "slack_link": slack_link_cell,
    }


def get_version_from(
    xsoar_admin_user: XSOARAdminUser, client_type: type[XsoarClient], host: str, key: str, project_id: str
) -> dict | None:
    try:
        client = client_type(
            xsoar_host=host,
            xsoar_user=xsoar_admin_user.username,
            xsoar_pass=xsoar_admin_user.password,
            tenant_name=key,
            project_id=project_id,
        )
        client.login_auth(force_login=True)
        return client.get_version_info()
    except Exception as e:
        logging.error(f"Failed to get data for {key}: {e}")
    return None


def generate_cell_dict_key(record: dict, key: str, default_value: Any = NOT_AVAILABLE) -> dict:
    value = record.get(key)
    if value is not None:
        return generate_cell(value, value)
    return generate_cell(default_value, "")


def generate_records(
    configuration_file_json_records: dict,
    xsoar_admin_user: XSOARAdminUser,
    client_type: type[XsoarClient],
    tenants: dict,
    without_viso: bool,
    current_date: datetime,
) -> list[dict]:
    records = []
    lcaas_ids = set()
    for key, value in configuration_file_json_records.items():
        if key == COMMENT_FIELD_NAME:
            logging.debug("Skipping comment field.")
            continue
        logging.info(f"Processing machine: {key}")
        # ui_url is in the format of https://<host>/ we need just the host.
        host = value.get("ui_url").replace("https://", "").replace("/", "")
        record = {
            "host": generate_cell(generate_html_link(host, value.get("ui_url")), value.get("ui_url")),
            "ui_url": generate_cell_dict_key(value, "ui_url"),
            "machine_name": generate_cell(key),
            "enabled": generate_cell_dict_key(value, "enabled"),
            "flow_type": generate_cell_dict_key(value, "flow_type"),
            "platform_type": generate_cell(client_type.PLATFORM_TYPE),
            "lcaas_id": generate_cell_dict_key(value, "lcaas_id"),
            "version": generate_cell_dict_key(value, "version"),
            # Assume any machine in the json config is a build machine.
            "build_machine": generate_cell_dict_key(value, "build_machine", True),
            "agent_host_name": generate_cell_dict_key(value, "agent_host_name", NOT_AVAILABLE),
            "agent_host_ip": generate_cell_dict_key(value, "agent_host_ip", NOT_AVAILABLE),
            "comment": generate_cell_dict_key(value, "comment", ""),
            # The connectable field is populated after trying to connect to the machine.
            "connectable": generate_cell(False),
        }
        if not without_viso:
            # The below fields are populated from the tenants data from Viso, we populate empty data for them.
            record |= {
                "owner": generate_cell(NOT_AVAILABLE),
                "disposable": generate_cell(NOT_AVAILABLE),
                "tenant_status": generate_cell(NOT_AVAILABLE),
                "viso_version": generate_cell(NOT_AVAILABLE),
                "ttl": generate_cell(NOT_AVAILABLE, "", generate_ttl_class()),
                "slack_link": generate_cell(build_link_to_channel(XDR_UPGRADE_CHANNEL_ID_DEV)),
            }
        versions = get_version_from(xsoar_admin_user, client_type, host, key, AUTOMATION_GCP_PROJECT)
        if versions is not None:
            record |= {key: generate_cell(value) for key, value in versions.items()}
            record["connectable"] = generate_cell(True)
            lcaas_id = versions["lcaas_id"]
            lcaas_ids.add(lcaas_id)
            if not without_viso:
                tenant = tenants.get(lcaas_id)
                if tenant:
                    record |= get_record_for_tenant(tenant, current_date)
        records.append(record)

    # Going over machines which aren't listed within the infra configuration files.
    for tenant in tenants.values():
        if tenant["product_type"] != client_type.PRODUCT_TYPE:
            continue
        if tenant["lcaas_id"] not in lcaas_ids:
            logging.info(f"Processing tenant: {tenant['lcaas_id']}")
            host_url = tenant.get("fqdn")
            ui_url = f"https://{host_url}"
            record = {
                "host": generate_cell(generate_html_link(host_url, ui_url), host_url),
                "ui_url": generate_cell(ui_url),
                "machine_name": generate_cell(tenant["subdomain"]),
                "enabled": generate_cell(False),
                "flow_type": generate_cell(NOT_AVAILABLE, ""),
                "platform_type": generate_cell(client_type.PLATFORM_TYPE),
                "lcaas_id": generate_cell(tenant["lcaas_id"]),
                "version": generate_cell(NOT_AVAILABLE, ""),
                "agent_host_name": generate_cell(NOT_AVAILABLE, ""),
                "agent_host_ip": generate_cell(NOT_AVAILABLE, ""),
                "connectable": generate_cell(False),
                "build_machine": generate_cell(False),
                "comment": generate_cell(""),
            }
            versions = get_version_from(xsoar_admin_user, client_type, host_url, host_url, AUTOMATION_GCP_PROJECT)
            if versions is not None:
                record |= {key: generate_cell(value) for key, value in versions.items()}
                record["connectable"] = generate_cell(True)
                tenant = tenants.get(tenant["lcaas_id"])
                if tenant:
                    record |= get_record_for_tenant(tenant, current_date)

            record |= get_record_for_tenant(tenant, current_date)
            records.append(record)

    return records


def load_json_file(file_path: str) -> dict | list:
    with contextlib.suppress(Exception):
        with open(file_path) as f:
            return json.load(f)
    return {}


def generate_report(args, records, tenants, tokens_count) -> tuple[list[dict], list[int], list[str], list[dict]]:
    slack_msg_append: List[Dict[Any, Any]] = []
    managers: list[Any] = []
    if args.name_mapping_path:
        name_mapping: dict = load_json_file(args.name_mapping_path)  # type: ignore[assignment]
        managers.extend(name_mapping.get("managers", []))
    columns = generate_columns(args.without_viso)
    static_columns = {column["key"] for column in columns if column["key"]}
    dynamic_columns = list({key for record in records for key in record.keys() if key not in static_columns})
    columns.extend([create_column(False, key, key, False, False, False, False) for key in dynamic_columns])
    columns_filterable = [i for i, c in enumerate(columns) if c["filterable"]]
    disabled_machines_count = set()
    non_connectable_machines_count = set()
    ttl_expired_count = set()
    owners_to_machines: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    build_machines_requiring_an_agent = defaultdict(set)
    for record in records:
        machine_name = record.get("machine_name", {}).get("display")
        platform_type = record.get("platform_type", {}).get("display")
        flow_type = record.get("flow_type", {}).get("display")
        # checking the TTL, enabled and connectable only for build machines.
        if record.get("build_machine", {}).get("display", True):
            if not record.get("enabled", {}).get("display", True):
                disabled_machines_count.add(machine_name)
            if not record.get("connectable", {}).get("display", True):
                non_connectable_machines_count.add(machine_name)
            if record.get("ttl", {}).get("column_class") == generate_ttl_class(True):
                ttl_expired_count.add(machine_name)
            if (
                record.get("agent_host_name", {}).get("display") == NOT_AVAILABLE
                and platform_type in BUILD_MACHINES_FLOW_REQUIRING_AN_AGENT
                and flow_type in BUILD_MACHINES_FLOW_REQUIRING_AN_AGENT[platform_type]
            ):
                build_machines_requiring_an_agent[flow_type].add(machine_name)
        if not args.without_viso:
            # Count the number of machines per owner per machine type, only if they don't have a flow type.
            owner = record.get("owner", {}).get("display")
            flow_type = record.get("flow_type", {}).get("display")
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
        owners_to_notify_list = list(owners_to_notify)
        owners_to_notify_str = (
            f"{','.join(map(lambda o: f'@{o}', owners_to_notify_list[:MAX_OWNERS_TO_NOTIFY_DISPLAY]))}"
            f"{' ...' if len(owners_to_notify_list) > MAX_OWNERS_TO_NOTIFY_DISPLAY else ''}"
        )
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
                "fields": [{"title": "Machine Name(s)", "value": ", ".join(non_connectable_machines_count), "short": True}],
            }
        )
    if disabled_machines_count:
        title = f"Build Machines - Disabled:{len(disabled_machines_count)}"
        slack_msg_append.append(
            {
                "color": "warning",
                "title": title,
                "fallback": title,
                "fields": [{"title": "Machine Name(s)", "value": ", ".join(disabled_machines_count), "short": True}],
            }
        )
    if ttl_expired_count:
        title = f"Build Machines - With Expired TTL:{len(ttl_expired_count)}"
        slack_msg_append.append(
            {
                "color": "danger",
                "title": title,
                "fallback": title,
                "fields": [{"title": "Machine Name(s)", "value": ", ".join(ttl_expired_count), "short": True}],
            }
        )
    if build_machines_requiring_an_agent:
        title = f"Build Machines - Requiring an Agent:{len(build_machines_requiring_an_agent)}"
        slack_msg_append.append(
            {
                "color": "danger",
                "title": title,
                "fallback": title,
                "fields": [
                    {"title": f"Flow Type - {key}", "value": ", ".join(value), "short": True}
                    for key, value in build_machines_requiring_an_agent.items()
                ],
            }
        )
    if tokens_count is not None:
        tokens_percentage = int((len(tenants) / tokens_count) * 100)
        title = f"Disposable Tenants Tokens - Total:{tokens_count}, Used:{len(tenants)}"
        if tokens_percentage >= TOKENS_COUNT_PERCENTAGE_THRESHOLD:
            title += f", Usage > {TOKENS_COUNT_PERCENTAGE_THRESHOLD}%"
            color = "danger"
        else:
            color = "good"
        slack_msg_append.append(
            {
                "color": color,
                "title": title,
                "fallback": title,
            }
        )
    return columns, columns_filterable, managers, slack_msg_append


def get_viso_tenants_data(without_viso: bool) -> tuple[dict, int | None, list[dict]]:
    slack_msg_append: List[Dict[Any, Any]] = []
    tenants = {}
    tokens_count = None
    if without_viso:
        logging.info("Not connecting to Viso.")
    elif not VISO_API_URL or not VISO_API_KEY:
        logging.error("VISO_API_URL or VISO_API_KEY env vars are not set.")
        slack_msg_append.append(
            {
                "color": "danger",
                "title": "VISO_API_URL or VISO_API_KEY env vars are not set",
                "fallback": "VISO_API_URL or VISO_API_KEY env vars are not set",
            }
        )
    else:
        logging.info(f"Connecting to Viso - Endpoint:{VISO_API_URL}")
        viso_api = VisoAPI(VISO_API_URL, VISO_API_KEY)
        try:
            tenants_list = viso_api.get_all_tenants(CONTENT_TENANTS_GROUP_OWNER)
            tenants = {tenant["lcaas_id"]: tenant for tenant in tenants_list}
            logging.info(f"Got {len(tenants)} tenants for group owner:{CONTENT_TENANTS_GROUP_OWNER}")
        except Exception as e:
            logging.debug(f"Failed to get tenants: {e}")
            logging.error("Failed to get tenants")
            tenants = {}
            slack_msg_append.append(
                {
                    "color": "danger",
                    "title": "Failed to get tenants",
                    "fallback": "Failed to get tenants",
                }
            )
        try:
            tokens_count = viso_api.get_disposable_token_count(CONTENT_TENANTS_GROUP_OWNER)
            logging.info(f"Got disposable tenants tokens count:{tokens_count} for group owner:{CONTENT_TENANTS_GROUP_OWNER}")
        except Exception as e:
            logging.debug(f"Failed to get disposable tenants tokens count: {e}")
            logging.error("Failed to get disposable tenants tokens count")
            tokens_count = None
            slack_msg_append.append(
                {
                    "color": "danger",
                    "title": "Failed to get disposable tenants tokens count",
                    "fallback": "Failed to get disposable tenants tokens count",
                }
            )
    return tenants, tokens_count, slack_msg_append


def main() -> None:
    args = options_handler()
    output_path = Path(args.output_path)
    try:
        tenants, tokens_count, slack_msg_append = get_viso_tenants_data(args.without_viso)

        current_date = datetime.utcnow()
        current_date_str = current_date.strftime("%Y-%m-%d")

        if args.test_data:
            test_data_path = Path(args.test_data)
            records: list[dict] = load_json_file((test_data_path / RECORDS_FILE_NAME).as_posix())  # type: ignore[assignment]
            wait_in_line_slack_messages: list = load_json_file(
                (test_data_path / WAIT_IN_LINE_SLACK_MESSAGES_FILE_NAME).as_posix()
            )  # type: ignore[assignment]
        else:
            admin_user = Settings.xsoar_admin_user
            xsiam_json: dict = load_json_file(args.xsiam_json)  # type: ignore[assignment]
            xsoar_ng_json: dict = load_json_file(args.xsoar_ng_json)  # type: ignore[assignment]
            records_xsoar_ng = generate_records(xsoar_ng_json, admin_user, XsoarClient, tenants, args.without_viso, current_date)
            records_xsiam = generate_records(xsiam_json, admin_user, XsiamClient, tenants, args.without_viso, current_date)
            records = records_xsoar_ng + records_xsiam
            client = WebClient(token=SLACK_TOKEN)
            wait_in_line_slack_messages = get_messages_from_slack(client, WAIT_IN_LINE_CHANNEL_ID)

            # Save the records to a json file for future use and debugging.
            with open(output_path / RECORDS_FILE_NAME, "w") as f:
                json.dump(records, f, indent=4, default=str, sort_keys=True)

            with open(output_path / WAIT_IN_LINE_SLACK_MESSAGES_FILE_NAME, "w") as f:
                json.dump(wait_in_line_slack_messages, f, indent=4, default=str, sort_keys=True)

        logging.info(f"Creating report for {current_date_str}")
        columns, columns_filterable, managers, slack_msg_append_report = generate_report(args, records, tenants, tokens_count)
        slack_msg_append.extend(slack_msg_append_report)

        attachments_json = generate_graphs(output_path, wait_in_line_slack_messages)

        report = create_report_html(current_date_str, records, columns, columns_filterable, managers)
        report_file_name = f"Report_{current_date_str}.html"
        with open(output_path / report_file_name, "w") as report_file:
            report_file.write(report)

        with open(output_path / "slack_msg.txt", "w") as slack_msg_file:
            report_url = f"{GITLAB_ARTIFACTS_URL}/{CI_JOB_ID}/artifacts/{ARTIFACTS_FOLDER}/{report_file_name}"
            title = f"Build machines report - {current_date_str} was created"
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
