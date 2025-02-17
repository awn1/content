import argparse
import contextlib
import json
import logging
import os
import re
import warnings
from collections import defaultdict
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import urllib3
from google.auth import _default
from jinja2 import Environment, FileSystemLoader
from lock_cloud_machines import generate_tenant_token_map
from packaging.version import Version
from slack_sdk import WebClient
from urllib3.exceptions import InsecureRequestWarning

from SecretActions.add_build_machine import BUILD_MACHINE_GSM_AUTH_ID
from SecretActions.google_secret_manager_handler import GoogleSecreteManagerModule, SecretLabels
from SecretActions.SecretsBuild.merge_and_delete_dev_secrets import delete_dev_secrets
from Tests.creating_disposable_tenants.create_disposable_tenants import AGENT_IP_DEFAULT_MESSAGE, AGENT_NAME_DEFAULT_MESSAGE
from Tests.scripts.common import join_list_by_delimiter_in_chunks, string_to_bool
from Tests.scripts.graph_lock_machine import (
    AVAILABLE_MACHINES,
    BUILD_IN_QUEUE,
    LOCK_DURATION,
    create_available_machines_graph,
    create_builds_waiting_in_queue_graph,
    create_lock_duration_graph,
)
from Tests.scripts.infra.resources.constants import AUTOMATION_GCP_PROJECT, COMMENT_FIELD_NAME, GSM_SERVICE_ACCOUNT
from Tests.scripts.utils.slack import get_conversations_members_slack, get_messages_from_slack, get_slack_usernames_from_ids

urllib3.disable_warnings(InsecureRequestWarning)
warnings.filterwarnings("ignore", _default._CLOUD_SDK_CREDENTIALS_WARNING)

from Tests.scripts.infra.settings import Settings, XSOARAdminUser  # noqa
from Tests.scripts.infra.viso_api import VisoAPI  # noqa
from Tests.scripts.infra.xsoar_api import XsoarClient, XsiamClient, SERVER_TYPE_TO_CLIENT_TYPE, InvalidAPIKey  # noqa

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
SLACK_WORKSPACE_NAME = os.getenv("SLACK_WORKSPACE_NAME", "")
SLACK_TOKEN = os.getenv("SLACK_TOKEN")
XDR_PERMISSIONS_DEV = os.environ["XDR_PERMISSIONS_DEV"]
XDR_UPGRADE_CHANNEL_DEV = os.environ["XDR_UPGRADE_CHANNEL_DEV"]
XDR_UPGRADE_CHANNEL_ID_DEV = os.environ["XDR_UPGRADE_CHANNEL_ID_DEV"]
DMST_CONTENT_TEAM_ID = os.environ["DMST_CONTENT_TEAM_ID"]
PERMISSION_ROLE = os.environ.get("PERMISSION_ROLE", "cortex-operator-data-access")
NOT_AVAILABLE = "N/A"
VISO_API_URL: str | None = os.getenv("VISO_API_URL")
VISO_API_KEY = os.getenv("VISO_API_KEY")
WITHOUT_VISO = os.getenv("WITHOUT_VISO")
WAIT_IN_LINE_CHANNEL_ID: str = os.environ["WAIT_IN_LINE_CHANNEL_ID"]
CONTENT_TENANTS_GROUP_OWNER = os.getenv("CONTENT_TENANTS_GROUP_OWNER")
TTL_EXPIRED_DAYS_DEFAULT = 5
TTL_EXPIRED_DAYS = timedelta(days=int(os.getenv("TTL_EXPIRED_DAYS", TTL_EXPIRED_DAYS_DEFAULT)))
LICENSE_EXPIRED_DAYS_DEFAULT = 5
LICENSE_EXPIRED_DAYS = timedelta(days=int(os.getenv("LICENSE_EXPIRED_DAYS", LICENSE_EXPIRED_DAYS_DEFAULT)))
LICENSE_DATE_FORMAT = "%Y %b %d"
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
PRODUCT_TYPE_TO_SERVER_TYPE: dict[str | None, str] = {
    XsoarClient.PRODUCT_TYPE: XsoarClient.SERVER_TYPE,
    XsiamClient.PRODUCT_TYPE: XsiamClient.SERVER_TYPE,
}
IGNORED_FLOW_TYPES = [
    "build-test-xsiam",  # Research team machines.
]


def create_column(
    tenants: bool,
    key: str,
    data: str,
    exportable: bool,
    visible: bool,
    add_class: bool,
    filterable: bool,
    **kwargs,
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
        create_column(
            False,
            "",
            "",
            False,
            True,
            False,
            False,
            className="dt-control",
            orderable="false",
            defaultContent="",
        ),
        create_column(False, "host", "Host", True, True, False, False),
        create_column(False, "machine_name", "Machine Name", True, True, False, False),
        create_column(False, "enabled", "Enabled", True, True, True, True),
        create_column(False, "flow_type", "Flow Type", True, True, True, True),
        create_column(False, "platform_type", "Platform Type", True, True, True, True),
        create_column(False, "version", "Server Version", True, True, True, True),
        create_column(False, "lcaas_id", "LCAAS ID", True, True, True, False),
        create_column(True, "ttl", "TTL", True, True, True, False),
        create_column(False, "license", "License", True, False, True, False),
        create_column(False, "api_key_ttl", "API Key TTL", True, False, True, False),
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
        default=False,
        help="Don't generate statistics.",
        required=False,
    )
    return parser.parse_args()


def generate_html_link(text: str, url: str) -> str:
    return f'<a href="{url}" target="_blank">{text}</a>'


def generate_cell(display: Any, sort: Any | None = None, column_class: str | None = None, **kwargs) -> dict:
    data = {
        "display": display,
        "sort": sort if sort is not None else display,
    }
    if column_class:
        data["column_class"] = column_class
    return data | kwargs


def sanitize_css(css_class: str) -> str:
    return re.sub(r"[^\w-]", "-", css_class).lower().strip("-")


def get_message_p_from_ts(ts: str) -> str:
    return f"p{ts.replace('.', '')}"


def generate_version_cell(version: str, platform_type: str | None = None, flow_type: str | None = None, **_) -> dict:
    return generate_cell(version, column_class=generate_version_cell_css_class(version, platform_type, flow_type))


def generate_version_cell_css_class(
    version: str,
    platform_type: str | None = None,
    flow_type: str | None = None,
    *,
    with_prefix: bool = False,
) -> str:
    column_class = version
    if flow_type is not None:
        column_class = f"{flow_type}-{column_class}"
    if platform_type is not None:
        column_class = f"{platform_type}-{column_class}"
    if with_prefix:
        column_class = f"class-version-{column_class}"
    return sanitize_css(column_class)


def build_link_to_channel(channel_id: str) -> str:
    return f"https://{SLACK_WORKSPACE_NAME}.slack.com/archives/{channel_id}" if SLACK_WORKSPACE_NAME else ""


def build_link_to_message(channel_id: str, message_ts: str) -> str:
    return f"{build_link_to_channel(channel_id)}/{message_ts}" if SLACK_WORKSPACE_NAME else ""


def get_datetime_from_epoch(epoch: str) -> datetime:
    return datetime.fromtimestamp(float(epoch))


def generate_expired_class(expired: bool | None = None):
    return "expired" if expired else "ok" if expired is not None else "na"


def generate_ttl_cell(ttl_date: datetime, current_date: datetime, **kwargs) -> dict:
    expired = ttl_date <= current_date + TTL_EXPIRED_DAYS
    return generate_cell(
        ttl_date.strftime("%Y-%m-%dT%H-%M"),
        ttl_date.strftime("%Y-%m-%d"),
        generate_expired_class(expired),
        expired=expired,
        **kwargs,
    )


def generate_expired_cell(
    expire_date: datetime, current_date: datetime, notice_days: timedelta, sort: Any | None = None, **kwargs
) -> dict:
    expired = expire_date <= current_date + notice_days
    return generate_cell(
        expire_date.strftime("%Y-%m-%dT%H-%M"),
        sort,
        generate_expired_class(expired),
        expired=expired,
        **kwargs,
    )


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
        slack_link_cell = generate_cell(
            generate_html_link("Upgrade Channel", slack_link),
            XDR_UPGRADE_CHANNEL_ID_DEV,
        )
    return {
        "owner": generate_cell(tenant["owner"]),
        "disposable": generate_cell(tenant["disposable"]),
        "tenant_status": generate_tenant_status_cell(tenant["status"]),
        "viso_version": generate_cell(tenant["viso_version"]),
        "ttl": generate_ttl_cell(get_datetime_from_epoch(tenant["ttl"]), current_date),
        "slack_link": slack_link_cell,
    }


def get_client(
    xsoar_admin_user: XSOARAdminUser,
    client_type: type[XsoarClient],
    host: str,
    key: str,
    project_id: str,
) -> XsoarClient | None:
    try:
        client = client_type(
            xsoar_host=host,
            xsoar_user=xsoar_admin_user.username,
            xsoar_pass=xsoar_admin_user.password,
            tenant_name=key,
            project_id=project_id,
        )
        client.login_auth(force_login=True)
        return client
    except Exception:
        logging.exception(f"Failed connect to server:{host}")
    return None


def get_version_info(client: XsoarClient) -> dict | None:
    try:
        return client.get_version_info()
    except Exception:
        logging.exception("Failed to get versions from server")
    return None


def get_get_configuration(client: XsoarClient) -> dict | None:
    try:
        return client.get_configuration()
    except Exception:
        logging.exception("Failed to get configuration from server")
    return None


def get_licenses_data(configurations: dict) -> dict:
    licenses = configurations.get("reply", {}).get("license", {}).get("licenses", {})
    licenses_data = {}
    for license_main_type, license_main_data in licenses.items():
        if license_main_data:
            # XSIAM license data
            if license_main_data.get("enable", False):
                if expiration_data_int := license_main_data.get("expiration_date"):
                    expiration_date = get_datetime_from_epoch(str(expiration_data_int))
                    licenses_data[f"license_{license_main_type}"] = expiration_date
            # XSOAR license data SOAR/TIM
            for license_sub_type, license_sub_data in license_main_data.get("license", {}).items():
                licenses_data[f"license_{license_main_type}_{license_sub_type}"] = datetime.strptime(
                    license_sub_data["validTil"], LICENSE_DATE_FORMAT
                )
    return licenses_data


def generate_cell_dict_key(record: dict, key: str, default_value: Any = NOT_AVAILABLE) -> dict:
    value = record.get(key)
    if value is not None:
        return generate_cell(value, value)
    return generate_cell(default_value, "")


def generate_agent_cell_dict_key(record: dict, key: str) -> dict:
    if value := record.get(key) in (None, AGENT_NAME_DEFAULT_MESSAGE, AGENT_IP_DEFAULT_MESSAGE):
        return generate_cell(NOT_AVAILABLE, "")
    return generate_cell(value, value)


def get_api_key_ttl_cell(client, current_date, token_map):
    try:
        client_token = token_map.get(client.tenant_name)
        cloud_machine_details, secret_version = client.login_using_gsm(client_token)

        auth_id = cloud_machine_details[BUILD_MACHINE_GSM_AUTH_ID]
        api_keys = client.search_api_keys()
        if api_key := next((key for key in api_keys if key.id == auth_id), None):
            logging.info(
                f"API key for machine {client.tenant_name} (from secret version {secret_version}) "
                f"is on API keys list in the machine."
            )
            return generate_ttl_cell(api_key.expiration, current_date) if api_key.expiration else generate_cell(NOT_AVAILABLE)
        raise InvalidAPIKey(
            client.tenant_name,
            f"Could not find generated API key (from secret version {secret_version}) on API keys list in the machine.",
        )
    except Exception as e:
        logging.error(f"Failed to get API Key for machine: {client.tenant_name}. {e}")
        return generate_cell(NOT_AVAILABLE, invalid=True)


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


def generate_records(
    cloud_servers_path_json: dict,
    xsoar_admin_user: XSOARAdminUser,
    tenants: dict,
    without_viso: bool,
    current_date: datetime,
    token_map: dict,
) -> list[dict]:
    records = []
    lcaas_ids = set()
    client_type: type[XsoarClient] | None
    for key, value in cloud_servers_path_json.items():
        if key == COMMENT_FIELD_NAME:
            logging.debug("Skipping comment field.")
            continue
        logging.info(f"Processing tenant: {key} from the configuration")
        # ui_url is in the format of https://<host>/ we need just the host.
        host = value.get("ui_url").replace("https://", "").replace("/", "")
        client_type = SERVER_TYPE_TO_CLIENT_TYPE[value["server_type"]]
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
            "agent_host_name": generate_agent_cell_dict_key(value, "agent_host_name"),
            "agent_host_ip": generate_agent_cell_dict_key(value, "agent_host_ip"),
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
                "ttl": generate_cell(NOT_AVAILABLE, "", generate_expired_class()),
                "slack_link": generate_cell(build_link_to_channel(XDR_UPGRADE_CHANNEL_ID_DEV)),
            }
        lcaas_ids.add(key.split("-")[-1])
        if client := get_client(xsoar_admin_user, client_type, host, key, AUTOMATION_GCP_PROJECT):
            if (versions := get_version_info(client)) is not None:
                record |= generate_record_from_version_info(
                    versions, flow_type=get_record_display(record, "flow_type"), platform_type=client_type.PLATFORM_TYPE
                )
                lcaas_id = versions["lcaas_id"]
                lcaas_ids.add(lcaas_id)
                if not without_viso:
                    tenant = tenants.get(lcaas_id)
                    if tenant:
                        record |= get_record_for_tenant(tenant, current_date)
            record |= get_licenses_cells(client, current_date)
            record["api_key_ttl"] = get_api_key_ttl_cell(client, current_date, token_map)

        records.append(record)

    # Going over machines which aren't listed within the infra configuration files.
    for tenant in tenants.values():
        if tenant["lcaas_id"] not in lcaas_ids:
            logging.info(f"Processing tenant: {tenant['lcaas_id']} which isn't in the configuration")
            host_url = tenant.get("fqdn")
            ui_url = f"https://{host_url}"
            client_type = SERVER_TYPE_TO_CLIENT_TYPE.get(PRODUCT_TYPE_TO_SERVER_TYPE.get(tenant["product_type"]))
            platform_type = client_type.PLATFORM_TYPE if client_type is not None else tenant["product_type"]
            record = {
                "host": generate_cell(generate_html_link(host_url, ui_url), host_url),
                "ui_url": generate_cell(ui_url),
                "machine_name": generate_cell(tenant["lcaas_id"]),
                "enabled": generate_cell(False),
                "flow_type": generate_cell(NOT_AVAILABLE, ""),
                "platform_type": generate_cell(platform_type),
                "lcaas_id": generate_cell(tenant["lcaas_id"]),
                "version": generate_cell(NOT_AVAILABLE, ""),
                "agent_host_name": generate_cell(NOT_AVAILABLE, ""),
                "agent_host_ip": generate_cell(NOT_AVAILABLE, ""),
                "connectable": generate_cell(False),
                "build_machine": generate_cell(False),
                "comment": generate_cell(""),
            }
            if client_type is not None and (
                client := get_client(
                    xsoar_admin_user, client_type, host_url, f"qa2-test-{tenant['lcaas_id']}", AUTOMATION_GCP_PROJECT
                )
            ):
                if (versions := get_version_info(client)) is not None:
                    record |= generate_record_from_version_info(versions, platform_type=client_type.PLATFORM_TYPE)
                    if tenant := tenants.get(tenant["lcaas_id"]):
                        record |= get_record_for_tenant(tenant, current_date)
                record |= get_licenses_cells(client, current_date)
                record["api_key_ttl"] = get_api_key_ttl_cell(client, current_date, token_map)
            record |= get_record_for_tenant(tenant, current_date)
            records.append(record)

    return records


VERSION_GENERATE_CELL: dict[str, Callable] = {
    "version": generate_version_cell,
}


def generate_cell_by_type(key, value, **kwargs):
    generate = VERSION_GENERATE_CELL.get(key, generate_cell)
    return generate(value, **kwargs)


def generate_record_from_version_info(versions: dict, **kwargs) -> dict:
    record = {key: generate_cell_by_type(key, value, **kwargs) for key, value in versions.items()}
    record["connectable"] = generate_cell(True)
    return record


def get_licenses_cells(client: XsoarClient, current_date: datetime) -> dict:
    if (configuration := get_get_configuration(client)) is not None:
        if licenses := get_licenses_data(configuration):
            records = {}
            min_date = None
            for key, value in licenses.items():
                cell = generate_expired_cell(value, current_date, LICENSE_EXPIRED_DAYS)
                records[key] = cell
                if min_date is None or value < min_date:
                    min_date = value

            if min_date is not None:
                # Aggregate the licenses expiration dates to a single cell.
                records["license"] = generate_expired_cell(min_date, current_date, LICENSE_EXPIRED_DAYS, field_type="license")
                return records

    return {"license": generate_cell(NOT_AVAILABLE)}


def load_json_file(file_path: str) -> dict | list:
    with contextlib.suppress(Exception):
        with open(file_path) as f:
            return json.load(f)
    return {}


def get_record_display(record: dict, field: str, default: Any = None) -> str:
    return record.get(field, {}).get("display", default)


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
    name_mapping: dict,
    records: list,
    tenants: dict,
    tokens_count: int | None,
    keys_without_tenant: set[str] | None,
) -> tuple[list[dict], list[int], list[str], dict[str, Any], list[dict]]:
    slack_msg_append: list[dict[Any, Any]] = []
    managers: list[Any] = name_mapping.get("managers", [])
    columns = generate_columns(without_viso)
    static_columns = {column["key"] for column in columns if column["key"]}
    dynamic_columns = list({key for record in records for key in record.keys() if key not in static_columns})
    columns.extend([create_column(False, key, key, False, False, False, False) for key in dynamic_columns])
    columns_filterable = [i for i, c in enumerate(columns) if c["filterable"]]
    disabled_machines_count = set()
    non_connectable_machines_count = set()
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
                        "title": "Machine Name(s)",
                        "value": ", ".join(non_connectable_machines_count),
                        "short": True,
                    }
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
                        "title": "Machine Name(s)",
                        "value": ", ".join(disabled_machines_count),
                        "short": True,
                    }
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
                        "title": "Machine Name(s)",
                        "value": ", ".join(ttl_expired_count),
                        "short": True,
                    }
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
                        "title": "Machine Name(s)",
                        "value": ", ".join(licenses_expired_count),
                        "short": True,
                    }
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
                    css_class = generate_version_cell_css_class(version, platform_type, flow_type, with_prefix=True)
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

    if missing_users_in_mapping := get_missing_users_in_mapping(client, name_mapping):
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
    return columns, columns_filterable, managers, css_classes, slack_msg_append


def get_viso_tenants_data(without_viso: bool) -> tuple[dict, int | None, list[dict]]:
    slack_msg_append: list[dict[Any, Any]] = []
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
        tenants, tokens_count, slack_msg_append = get_viso_tenants_data(args.without_viso)
        tenant_token_map = generate_tenant_token_map(tenants_data=tenants)
        current_date = datetime.utcnow()
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
            # Save the records to a json file for future use and debugging.
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
        columns, columns_filterable, managers, css_classes, slack_msg_append_report = generate_report(
            client, args.without_viso, name_mapping, records, tenants, tokens_count, keys_without_tenant
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
