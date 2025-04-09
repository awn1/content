import argparse
import contextlib
import json
import logging
import time
import warnings
from collections.abc import Iterable
from datetime import datetime
from distutils.util import strtobool
from pathlib import Path

import humanize
import tabulate
import urllib3
from google.auth import _default  # noqa
from urllib3.exceptions import InsecureRequestWarning

urllib3.disable_warnings(InsecureRequestWarning)
warnings.filterwarnings("ignore", _default._CLOUD_SDK_CREDENTIALS_WARNING)  # noqa

from Tests.creating_disposable_tenants.wait_disposable_tenants_ready import (  # noqa
    ERROR_STATUS,
    READY_STATUS,
    STATUS_FIELD_NAME,
    STOP_STATUS_FIELD_NAME,
    STOP_STATUS_STARTED,
)
from Tests.scripts.common import load_json_file  # noqa
from Tests.scripts.utils.log_util import install_logging  # noqa

from Tests.scripts.common import slack_link  # noqa
from Tests.scripts.gitlab_slack_notifier import DEVOPS_CORTEX_TOOLING_CHANNEL_ID  # noqa

from Tests.scripts.infra.settings import Settings, XSOARAdminUser  # noqa
from Tests.scripts.infra.viso_api import VisoAPI  # noqa
from Tests.scripts.infra.xsoar_api import SERVER_TYPE_TO_CLIENT_TYPE, InvalidAPIKey, XsiamClient, XsoarClient  # noqa
from Tests.scripts.machines import (  # noqa
    CONTENT_TENANTS_GROUP_OWNER,
    generate_records,
    get_record_by_key,
    get_record_display,
    get_viso_tenants_data,
    status_has_error,
    generate_columns,
    SAM_PORTAL_URL,
)

"""
This script is in charge of a daily routine to stop/start disposable tenants, that are non-build related.
In order to run the script locally authenticate to gcloud with `gcloud auth application-default login`.

Running this script without the correct configuration may delete stop or start disposable tenants that are in use.
Consider using dry run argument --dry-run=true.
"""


def options_handler() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Script perform daily routine on tenants.")
    parser.add_argument("--cloud_servers_path", help="Path to secret cloud server metadata file.")
    parser.add_argument("-a", "--action", help="Which action to perform: start/stop", required=False)
    parser.add_argument("-o", "--output-path", required=True, help="The path to save the report to.")
    parser.add_argument(
        "-dr",
        "--dry-run",
        type=strtobool,
        help="Whether the tenant will be actually stopped or started, or only dry-run",
        default="true",
    )
    return parser.parse_args()


def start_machines(
    lcaas_ids: list[str],
    viso_api: VisoAPI,
    timeout: int = 900,  # 15 minutes
    sleep_interval: int = 60,  # 1 minute
) -> tuple[Iterable[str], Iterable[str]]:
    # initialize timer
    start_time: float = time.time()
    elapsed: float = 0

    ready_tenants: set[str] = set()
    not_ready_tenants: set[str] = set(lcaas_ids)
    while elapsed < timeout:
        logging.info("Checking tenants status...")
        viso_tenants_info: dict = viso_api.get_all_tenants(
            group_owner=CONTENT_TENANTS_GROUP_OWNER, fields=[STATUS_FIELD_NAME, STOP_STATUS_FIELD_NAME]
        )
        all_tenants_info: dict = {item["lcaas_id"]: item for item in viso_tenants_info}
        for tenant_id in not_ready_tenants.copy():
            lcaas_id = tenant_id.split("-")[-1]
            if lcaas_id in all_tenants_info:
                tenant_status = all_tenants_info[lcaas_id][STATUS_FIELD_NAME]
                stop_status = all_tenants_info[lcaas_id][STOP_STATUS_FIELD_NAME]
                if tenant_status == READY_STATUS and stop_status == STOP_STATUS_STARTED:
                    ready_tenants.add(tenant_id)
                    not_ready_tenants.remove(tenant_id)
                    logging.debug(f"Tenant {tenant_id} is ready")
                elif tenant_status in ERROR_STATUS or status_has_error(stop_status):
                    logging.error(f"Tenant {tenant_id} is in `{tenant_status}` status.")
                else:
                    logging.debug(f"Tenant {tenant_id} is not ready, current status: {tenant_status}")
            else:
                logging.error(f"Tenant {tenant_id} not found in tenants info.")

        if not_ready_tenants:
            logging.warning(f"The following tenants are not ready: {', '.join(not_ready_tenants)}")
            if ready_tenants:
                logging.info(f"The following tenants are ready: {', '.join(ready_tenants)}")
        elif ready_tenants:
            duration = humanize.naturaldelta(elapsed, minimum_unit="milliseconds")
            logging.info(f"All disposable tenants are ready after {duration}.")
            break

        elapsed = time.time() - start_time
        if elapsed >= timeout:
            logging.critical("Timed out waiting for disposable tenants to be ready.")
            return ready_tenants, not_ready_tenants
        logging.info(f"Go to sleep for {sleep_interval//60} minutes and then check again.")
        time.sleep(sleep_interval)
        return ready_tenants, not_ready_tenants
    return ready_tenants, not_ready_tenants


def start_build_machine(lcaas_ids: list[str], viso_api: VisoAPI):
    viso_api.start_tenants(lcaas_ids)
    start_machines(lcaas_ids, viso_api)


def stop_build_machine(lcaas_ids: list[str], viso_api: VisoAPI):
    viso_api.stop_tenants(lcaas_ids)


def perform_tenants_routine(records: list[dict], action: str, dry_run: bool, viso_api: VisoAPI) -> list[dict]:
    report = []
    lcaas_ids: list[str] = []
    for record in records:
        if not get_record_display(record, "build_machine", True):
            machine_name = get_record_display(record, "machine_name")
            platform_type = get_record_display(record, "platform_type")
            flow_type = get_record_display(record, "flow_type")
            tenant_status = get_record_display(record, "tenant_status")
            if status_has_error(tenant_status):
                logging.error(
                    f"Machine {machine_name} with platform type {platform_type} and flow type {flow_type} has "
                    f"tenant status error: {tenant_status}"
                )
                continue
            if get_record_by_key(record, "stop_status", "invalid"):
                logging.error(
                    f"Machine {machine_name} with platform type {platform_type} and flow type {flow_type} has invalid "
                    f"stop status error: {get_record_display(record,'stop_status')}"
                )
                continue
            lcaas_ids.append(get_record_display(record, "lcaas_id"))
            report.append(record)

    if dry_run:
        logging.info(f"Dry run, skipping the actual {action} of tenants: {', '.join(lcaas_ids)}")
    else:
        logging.info(f"Actual {action} of tenants: {', '.join(lcaas_ids)}")
        if action == "start":
            start_build_machine(lcaas_ids, viso_api)
        elif action == "stop":
            stop_build_machine(lcaas_ids, viso_api)
    return report


def main() -> None:
    install_logging("machines_daily_routine.log")
    args = options_handler()
    output_path = Path(args.output_path)
    try:
        slack_msg = []
        attachments_json = []
        slack_thread = []
        tenants, _, slack_msg_append, viso_api = get_viso_tenants_data()
        if viso_api is not None:
            current_date = datetime.now()
            current_date_str = current_date.strftime("%Y-%m-%d %H:%M:%S")
            cloud_servers_path_json: dict = load_json_file(args.cloud_servers_path)  # type: ignore[assignment]

            records = generate_records(cloud_servers_path_json, None, tenants, False, current_date, None, False)
            columns, _ = generate_columns(records, False)

            report = perform_tenants_routine(records, args.action, args.dry_run, viso_api)
            routine_columns = [column for column in columns if column["routine"]]
            tabulate_data_columns = [column["display"] for column in routine_columns]
            tabulate_data = sorted(
                [[get_record_display(record, column["key"]) for column in routine_columns] for record in report],
                key=lambda row: row[0],
            )

            table = tabulate.tabulate(
                tabulate_data, headers=tabulate_data_columns, tablefmt="pretty", colalign=("left",) * len(routine_columns)
            )
            daily_routine_tenants_report = Path(output_path / "report.txt")
            daily_routine_tenants_report.write_text(table)

            attachments_json.append(
                {
                    "file": daily_routine_tenants_report.as_posix(),
                    "filename": daily_routine_tenants_report.name,
                    "title": f"{args.action}-tenants",
                },
            )
            dry_run_message = "(Dry Run)" if args.dry_run else ""
            title = f"Machines daily routine - Action:{args.action} {current_date_str} {dry_run_message}"
            slack_msg.append(
                {
                    "color": "good",
                    "title": title,
                    "fallback": title,
                },
            )
            if SAM_PORTAL_URL:
                sam_portal_title = "To stop/start your tenants go to the tenants management portal (SAM)"
                slack_msg.append(
                    {"fallback": sam_portal_title, "color": "good", "title": sam_portal_title, "title_link": SAM_PORTAL_URL}
                )
            if DEVOPS_CORTEX_TOOLING_CHANNEL_ID:
                cortex_tooling_link = slack_link(DEVOPS_CORTEX_TOOLING_CHANNEL_ID, "cortex-tooling")
                slack_thread_title = f"""
    Columns:
    *Flow Type* - To which team or individual this tenant belongs to.
    *Platform Type* - The type of instance: XSIAM, XSOAR NG, CLOUD (Prisma), Platform.
    *LCAAS ID* - The tenant unique ID.
    *Owner* - The tenant owner who created the tenant.
    *Tenant Status* - Indication on the provisioning status of the tenant.
    *Stop Status* - Indication if the tenant is in stop/start status, *before* the daily routine was performed.


    You have Questions? or Tenant won't start, please reach out to: `@cortex-tooling-team` in {cortex_tooling_link}
    """
                slack_thread.append(
                    {
                        "fallback": "Important :exclamation:",
                        "title": "Important :exclamation:",
                        "color": "good",
                        "fields": [
                            {
                                "title": "Please read below",
                                "value": slack_thread_title,
                                "short": False,
                                "mrkdwn": True,
                            }
                        ],
                    }
                )

        with open(output_path / "slack_msg.txt", "w") as slack_msg_file:
            json.dump(
                slack_msg + slack_msg_append,
                slack_msg_file,
                indent=4,
                default=str,
                sort_keys=True,
            )

        with open(output_path / "slack_attachments.json", "w") as slack_attachments_file:
            slack_attachments_file.write(json.dumps(attachments_json, indent=4, default=str, sort_keys=True))

        with open(output_path / "slack_thread.json", "w") as slack_thread_file:
            slack_thread_file.write(json.dumps(slack_thread, indent=4, default=str, sort_keys=True))

    except Exception as e:
        logging.exception(f"Failed to create report: {e}")
        with contextlib.suppress(Exception):
            with open(output_path / "slack_msg.txt", "w") as slack_msg_file:
                json.dump(
                    {
                        "title": "Machines Daily Routine Failed",
                        "color": "danger",
                    },
                    slack_msg_file,
                    indent=4,
                    default=str,
                    sort_keys=True,
                )


if __name__ == "__main__":
    main()
