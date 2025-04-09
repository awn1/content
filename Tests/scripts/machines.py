import logging
import os
import re
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from SecretActions.add_build_machine import BUILD_MACHINE_GSM_AUTH_ID
from Tests.creating_disposable_tenants.create_disposable_tenants import AGENT_IP_DEFAULT_MESSAGE, AGENT_NAME_DEFAULT_MESSAGE
from Tests.scripts.infra.resources.constants import AUTOMATION_GCP_PROJECT, COMMENT_FIELD_NAME
from Tests.scripts.infra.settings import XSOARAdminUser
from Tests.scripts.infra.viso_api import VisoAPI
from Tests.scripts.infra.xsoar_api import SERVER_TYPE_TO_CLIENT_TYPE, InvalidAPIKey, XsiamClient, XsoarClient
from Tests.scripts.utils.slack import tag_user

VISO_API_URL: str | None = os.getenv("VISO_API_URL")
VISO_API_KEY: str | None = os.getenv("VISO_API_KEY")
CONTENT_TENANTS_GROUP_OWNER: str | None = os.getenv("CONTENT_TENANTS_GROUP_OWNER")
SLACK_WORKSPACE_NAME: str | None = os.getenv("SLACK_WORKSPACE_NAME", "")
XDR_UPGRADE_CHANNEL_ID_DEV: str | None = os.getenv("XDR_UPGRADE_CHANNEL_ID_DEV")
SAM_PORTAL_URL: str | None = os.getenv("SAM_PORTAL_URL")
NOT_AVAILABLE: str = "N/A"
TTL_EXPIRED_DAYS_DEFAULT: int = (
    3  # since the max ttl for a disposable tenant is 144 hours, we want to warn 3 days before it expires
)
TTL_EXPIRED_DAYS: timedelta = timedelta(days=int(os.getenv("TTL_EXPIRED_DAYS", TTL_EXPIRED_DAYS_DEFAULT)))
LICENSE_EXPIRED_DAYS_DEFAULT: int = 5
LICENSE_EXPIRED_DAYS: timedelta = timedelta(days=int(os.getenv("LICENSE_EXPIRED_DAYS", LICENSE_EXPIRED_DAYS_DEFAULT)))
LICENSE_DATE_FORMAT: str = "%Y %b %d"
STOP_STATUS_STARTED: str = "started"
PRODUCT_TYPE_TO_SERVER_TYPE: dict[str | None, str] = {
    XsoarClient.PRODUCT_TYPE: XsoarClient.SERVER_TYPE,
    XsiamClient.PRODUCT_TYPE: XsiamClient.SERVER_TYPE,
}


def get_viso_tenants_data(without_viso: bool = False) -> tuple[dict, int | None, list[dict], VisoAPI | None]:
    slack_msg_append: list[dict[Any, Any]] = []
    tenants = {}
    tokens_count = None
    viso_api: VisoAPI | None = None
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
    return tenants, tokens_count, slack_msg_append, viso_api


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


def status_has_error(status: str) -> bool:
    return "error" in status.lower()


def generate_tenant_status_cell(status: str) -> dict:
    has_error = status_has_error(status)
    return generate_cell(status, status, "error" if has_error else "ok", invalid=has_error)


def stop_status_has_error(status: str) -> bool:
    return "error" in status.lower() or STOP_STATUS_STARTED != status.lower()


def generate_stop_status_status_cell(status: str) -> dict:
    has_error = stop_status_has_error(status)
    return generate_cell(status, status, "error" if has_error else "ok", invalid=has_error)


def get_record_for_tenant(tenant, current_date: datetime):
    return {
        "owner": generate_cell(tenant["owner"]),
        "disposable": generate_cell(tenant["disposable"]),
        "tenant_status": generate_tenant_status_cell(tenant["status"]),
        "stop_status": generate_stop_status_status_cell(tenant["stop_status"]),
        "viso_version": generate_cell(tenant["viso_version"]),
        "ttl": generate_ttl_cell(get_datetime_from_epoch(tenant["ttl"]), current_date),
    } | generate_slack_link(tenant)


def generate_slack_link(tenant):
    if XDR_UPGRADE_CHANNEL_ID_DEV:
        if "thread_ts" in tenant:
            slack_link = build_link_to_message(XDR_UPGRADE_CHANNEL_ID_DEV, get_message_p_from_ts(tenant["thread_ts"]))
            slack_link_cell = generate_cell(generate_html_link("Slack thread", slack_link), tenant["thread_ts"])
        else:
            slack_link = build_link_to_channel(XDR_UPGRADE_CHANNEL_ID_DEV)
            slack_link_cell = generate_cell(
                generate_html_link("Upgrade Channel", slack_link),
                XDR_UPGRADE_CHANNEL_ID_DEV,
            )
        return {"slack_link": slack_link_cell}
    return {}


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


def generate_records(
    cloud_servers_path_json: dict,
    xsoar_admin_user: XSOARAdminUser | None,
    tenants: dict,
    without_viso: bool,
    current_date: datetime,
    token_map: dict | None = None,
    check_connectivity: bool = True,
) -> list[dict]:
    records = []
    token_map = token_map or {}
    lcaas_ids = set()
    client_type: type[XsoarClient] | None
    for key, value in cloud_servers_path_json.items():
        if key == COMMENT_FIELD_NAME:
            logging.debug("Skipping comment field.")
            continue
        logging.info(f"Processing tenant: {key} from the configuration")
        # ui_url is in the format of https://<host>/ we need just the host.
        host = value.get("ui_url").replace("https://", "").replace("/", "")
        client_type = SERVER_TYPE_TO_CLIENT_TYPE.get(value.get("server_type"))
        lcaas_id = key.split("-")[-1]
        lcaas_ids.add(lcaas_id)
        record = {
            "host": generate_cell(generate_html_link(host, value.get("ui_url")), value.get("ui_url")),
            "ui_url": generate_cell_dict_key(value, "ui_url"),
            "machine_name": generate_cell(key),
            "enabled": generate_cell_dict_key(value, "enabled"),
            "flow_type": generate_cell_dict_key(value, "flow_type"),
            "platform_type": generate_cell(client_type.PLATFORM_TYPE if client_type is not None else NOT_AVAILABLE),
            "lcaas_id": generate_cell(lcaas_id),
            "version": generate_cell_dict_key(value, "version"),
            # Assume any machine in the JSON config is a build machine.
            "build_machine": generate_cell_dict_key(value, "build_machine", True),
            "agent_host_name": generate_agent_cell_dict_key(value, "agent_host_name"),
            "agent_host_ip": generate_agent_cell_dict_key(value, "agent_host_ip"),
            "comment": generate_cell_dict_key(value, "comment", ""),
            # The connectable field is populated after trying to connect to the machine.
            "connectable": generate_cell(False),
        }
        if not without_viso:
            # The below fields are populated from the tenants' data from Viso, we populate empty data for them.
            record |= {
                "owner": generate_cell(NOT_AVAILABLE),
                "disposable": generate_cell(NOT_AVAILABLE),
                "tenant_status": generate_cell(NOT_AVAILABLE),
                "stop_status": generate_cell(NOT_AVAILABLE),
                "viso_version": generate_cell(NOT_AVAILABLE),
                "ttl": generate_cell(NOT_AVAILABLE, "", generate_expired_class()),
            }
            if XDR_UPGRADE_CHANNEL_ID_DEV:
                record["slack_link"] = generate_cell(build_link_to_channel(XDR_UPGRADE_CHANNEL_ID_DEV))
        if not without_viso and (tenant := tenants.get(lcaas_id)):
            record |= get_record_for_tenant(tenant, current_date)
            record["flow_type"] = generate_cell(value.get("flow_type", tag_user(tenant["owner"])))

        stop_status = get_record_display(record, "stop_status")
        if (
            check_connectivity
            and stop_status == STOP_STATUS_STARTED
            and client_type is not None
            and xsoar_admin_user is not None
            and (client := get_client(xsoar_admin_user, client_type, host, key, AUTOMATION_GCP_PROJECT))
        ):
            if (versions := get_version_info(client)) is not None:
                record |= generate_record_from_version_info(
                    versions,
                    flow_type=get_record_display(record, "flow_type"),  # flow type and platform type are passed for CSS styling.
                    platform_type=client_type.PLATFORM_TYPE,
                )
            record |= get_licenses_cells(client, current_date)
            record["api_key_ttl"] = get_api_key_ttl_cell(client, current_date, token_map)
        records.append(record)

    # Going over machines which aren't listed within the infra configuration files.
    for tenant in tenants.values():
        if tenant["lcaas_id"] in lcaas_ids:
            continue
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
            "flow_type": generate_cell(tag_user(tenant["owner"])),
            "platform_type": generate_cell(platform_type),
            "lcaas_id": generate_cell(tenant["lcaas_id"]),
            "version": generate_cell(NOT_AVAILABLE, ""),
            "agent_host_name": generate_cell(NOT_AVAILABLE, ""),
            "agent_host_ip": generate_cell(NOT_AVAILABLE, ""),
            "connectable": generate_cell(False),
            "build_machine": generate_cell(False),
            "comment": generate_cell(""),
        }
        record |= get_record_for_tenant(tenant, current_date)
        if check_connectivity and tenant["stop_status"] == STOP_STATUS_STARTED and xsoar_admin_user is not None:
            if client_type is not None and (
                client := get_client(
                    xsoar_admin_user, client_type, host_url, f"qa2-test-{tenant['lcaas_id']}", AUTOMATION_GCP_PROJECT
                )
            ):
                if (versions := get_version_info(client)) is not None:
                    record |= generate_record_from_version_info(versions, platform_type=client_type.PLATFORM_TYPE)
                record |= get_licenses_cells(client, current_date)
                record["api_key_ttl"] = get_api_key_ttl_cell(client, current_date, token_map)
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
                # Aggregate the licenses' expiration dates to a single cell.
                records["license"] = generate_expired_cell(min_date, current_date, LICENSE_EXPIRED_DAYS, field_type="license")
                return records

    return {"license": generate_cell(NOT_AVAILABLE)}


def get_record_display(record: dict, field: str, default: Any = None) -> str:
    return record.get(field, {}).get("display", default)


def get_record_by_key(record: dict, field: str, key: str, default: Any = None) -> str:
    return record.get(field, {}).get(key, default)


def create_column(
    tenants: bool,
    key: str,
    display: str,
    exportable: bool,
    visible: bool,
    add_class: bool,
    filterable: bool,
    routine: bool,
    **kwargs,
) -> dict:
    return {
        "tenants": tenants,
        "key": key,
        "display": display,
        "exportable": exportable,
        "visible": visible,
        "add_class": add_class,
        "filterable": filterable,
        "routine": routine,
        **kwargs,
    }


def generate_columns(records: list[dict], without_viso: bool) -> tuple[list[dict], list[int]]:
    columns = [
        create_column(
            False,
            "",
            "",
            False,
            True,
            False,
            False,
            False,
            className="dt-control",
            orderable="false",
            defaultContent="",
        ),
        create_column(False, "host", "Host", True, True, False, False, False),
        create_column(False, "machine_name", "Machine Name", True, True, False, False, False),
        create_column(False, "enabled", "Enabled", True, True, True, True, False),
        create_column(False, "flow_type", "Flow Type", True, True, True, True, True),
        create_column(False, "platform_type", "Platform Type", True, True, True, True, True),
        create_column(False, "version", "Server Version", True, True, True, True, False),
        create_column(False, "lcaas_id", "LCAAS ID", True, True, True, False, True),
        create_column(True, "ttl", "TTL", True, True, True, False, False),
        create_column(False, "license", "License", True, False, True, False, False),
        create_column(False, "api_key_ttl", "API Key TTL", True, False, True, False, False),
        create_column(True, "owner", "Owner", True, False, True, True, True),
        create_column(True, "tenant_status", "Tenant Status", True, False, True, True, True),
        create_column(True, "stop_status", "Stop Status", True, False, True, True, True),
        create_column(False, "build_machine", "Build Machine", True, False, True, True, False),
        create_column(False, "comment", "Comment", True, False, False, False, False),
        create_column(True, "disposable", "Disposable", True, False, True, True, False),
        create_column(False, "connectable", "Connectable", False, False, False, True, False),
        create_column(False, "agent_host_name", "Agent Host Name", True, False, True, False, False),
        create_column(False, "agent_host_ip", "Agent IP", True, False, True, False, False),
    ]
    if without_viso:
        columns = list(filter(lambda c: c["tenants"] is False, columns))

    static_columns = {column["key"] for column in columns if column["key"]}
    dynamic_columns = list({key for record in records for key in record.keys() if key not in static_columns})
    columns.extend([create_column(False, key, key, False, False, False, False, False) for key in dynamic_columns])
    columns_filterable = [i for i, c in enumerate(columns) if c["filterable"]]

    return columns, columns_filterable
