import argparse
import datetime
import os
import sys
from time import sleep
from typing import NamedTuple

from Tests.scripts.infra.viso_api import VisoAPI
from Tests.scripts.utils import logging_wrapper as logging
from Tests.scripts.utils.log_util import install_logging

# ------------- Constants ------------------------

VISO_API_URL = os.environ["VISO_API_URL"]
VISO_API_KEY = os.environ["VISO_API_KEY"]
GROUP_OWNER = os.environ["GROUP_OWNER"]
DEFAULT_TIMEOUT = 1200  # 20 minutes

# ------------- Tuple Report for each machine -----------


class TenantReport(NamedTuple):
    lcaas_id: str
    status: str
    stop_status: str
    success: bool

    def __str__(self):
        return (
            f"Tenant ID: {self.lcaas_id}\n"
            f"Status: {self.status}\n"
            f"Stop Status: {self.stop_status}\n"
            f"Success: {'✔️' if self.success else '❌'}"
        )


# ----------------- Code ------------------------


def check_final_report(final_report_list: list[TenantReport], action: str):
    """
    Checks if any tenants failed to start / stop.
    If there is a failure, exit with code 1 (failure).
    """
    if failed_tenants := [report for report in final_report_list if not report.success]:
        tenants_id = [tenant.lcaas_id for tenant in failed_tenants]
        logging.info(f"The following tenants: {','.join(tenants_id)} failed to {action}")
        sys.exit(1)
    sys.exit(0)


def get_all_tenants(viso: VisoAPI) -> dict[str, dict]:
    """
    Gets all tenants and wraps it with lcaas_id as keys and tenants as values.
    """
    all_tenants = viso.get_all_tenants(group_owner=GROUP_OWNER, fields=["status", "stop_status"])
    return {tenant["lcaas_id"]: tenant for tenant in all_tenants}


def create_tenant_report(tenant_details: dict, action: str) -> TenantReport:
    """
    Creates a report for each tenant.
    """
    finish_status = "started" if action == "start" else "stopped"
    is_success = tenant_details["status"] == "running" and tenant_details["stop_status"] == finish_status
    return TenantReport(
        lcaas_id=tenant_details["lcaas_id"],
        status=tenant_details["status"],
        stop_status=tenant_details["stop_status"],
        success=is_success,
    )


def execute_action(viso: VisoAPI, relevant_tenants_id: set, action: str) -> None:
    """
    Executes the given action (start / stop) on the given tenants.
    """
    if action == "start":
        viso.start_tenants(lcaas_ids=list(relevant_tenants_id))
    elif action == "stop":
        viso.stop_tenants(lcaas_ids=list(relevant_tenants_id))
    else:
        logging.error(f"{action=} is invalid. There are two valid actions: start or stop.")
        sys.exit(1)


def start_stop_machines(
    viso: VisoAPI, relevant_tenants_id: set, action: str, timeout: int = DEFAULT_TIMEOUT
) -> list[TenantReport]:
    """Starts / Stops machines with a timeout mechanism."""

    start_time = datetime.datetime.now()
    execute_action(viso=viso, relevant_tenants_id=relevant_tenants_id, action=action)
    elapsed, final_report_list = 0, []

    while elapsed < timeout:
        if not relevant_tenants_id:  # All tenants are finished
            break

        finished_tenants_id = set()
        tenants: dict[str, dict] = get_all_tenants(viso)

        for tenant_id in relevant_tenants_id:
            finish_status = "started" if action == "start" else "stopped"
            tenant_details = tenants[tenant_id]

            if (
                tenant_details["stop_status"] == finish_status
                or "error" in tenant_details["stop_status"].lower()
                or "error" in tenant_details["status"].lower()
            ):
                # in this case the tenant is finished or failed so need to be removed and reported
                final_report_list.append(create_tenant_report(tenant_details=tenant_details, action=action))
                finished_tenants_id.add(tenant_id)

            logging.debug(f"{finished_tenants_id=} in this cycle")

        relevant_tenants_id = relevant_tenants_id - finished_tenants_id  # remove finished tenants
        logging.debug(f"{relevant_tenants_id=} which are still in progress")
        logging.info("stop_status is still not started / stopped in some tenants, sleeping for 60 seconds")
        sleep(60)
        elapsed = int((datetime.datetime.now() - start_time).total_seconds())

    else:
        logging.info("Timeout reached while starting / stopping the given tenants")
        tenants = get_all_tenants(viso)

        final_report_list.extend(
            create_tenant_report(tenant_details=tenants[tenant_id], action=action) for tenant_id in relevant_tenants_id
        )

    logging.info(f"Finish running in {(datetime.datetime.now() - start_time).total_seconds() / 60:.2f} minutes")
    return final_report_list


def is_action_needed(tenant: dict, action: str) -> bool:
    """
    Checks if the given action need to be executed on the given tenant.
    """

    if tenant["status"] == "running":
        if action == "start" and tenant["stop_status"] == "stopped":
            return True
        if action == "stop" and tenant["stop_status"] == "started":
            return True

    logging.info(
        f"Tenant's details: status = {tenant['status']} and stop_status = {tenant['stop_status']},"
        f" and the given action is {action}. Nothing needs to be done in this case."
    )
    return False


def filter_relevant_tenants_id(action: str, tenants_id: set, tenants: dict[str, dict]) -> set:
    """
    Filters which tenants id are relevant for start / stop (by the given action)
    """

    relevant_tenants_id = set()

    for tenant_id in tenants_id:
        if tenant_id not in tenants:
            logging.debug(f"{tenant_id=} does not exist")

        elif is_action_needed(tenants[tenant_id], action):
            relevant_tenants_id.add(tenant_id)

    logging.debug(f"They are the {relevant_tenants_id=}")
    return relevant_tenants_id


def create_report_when_action_no_needed(action: str, tenants_id: set, tenants: dict[str, dict]) -> list[TenantReport]:
    """
    Creates a report of success tenants.
    We should return a success tenant when an action is given, such as 'strat', and the tenant is already running.
    """
    return [
        create_tenant_report(tenants[tenant_id], action)
        for tenant_id in tenants_id
        if tenant_id in tenants and not is_action_needed(tenants[tenant_id], action)
    ]


def process_tenants(viso: VisoAPI, tenants_id: set, action: str, all_tenants: list[dict]) -> list[TenantReport]:
    """
    Filters the only relevant tenants, for executing on them the given action.
    Anyway, returns the ready / broken tenants.
    """
    tenants: dict[str, dict] = {tenant["lcaas_id"]: tenant for tenant in all_tenants}
    if relevant_tenants_id := filter_relevant_tenants_id(action, tenants_id, tenants):
        not_relevant_tenants_id = tenants_id - relevant_tenants_id
        partial_report = create_report_when_action_no_needed(action, not_relevant_tenants_id, tenants)
        return start_stop_machines(viso=viso, relevant_tenants_id=relevant_tenants_id, action=action) + partial_report
    logging.info(f"No relevant tenants were found to execute the {action=} on.")
    return create_report_when_action_no_needed(action, tenants_id, tenants)


def start_stop_mechanism(tenants_id: set, action: str) -> list[TenantReport] | None:
    """
    Tha main function for the start stop mechanism.
    """
    try:
        viso = VisoAPI(base_url=VISO_API_URL, api_key=VISO_API_KEY)
        all_tenants: list[dict] = viso.get_all_tenants(group_owner=GROUP_OWNER, fields=["status", "stop_status"])
    except Exception as e:
        logging.error(f"Failed to create VisoAPI  object or to retrieve tenants: {e}")
        return None
    return process_tenants(viso, tenants_id, action, all_tenants)


if __name__ == "__main__":
    install_logging(log_file_name="start_stop_mechanism.log", logger=logging)

    parser = argparse.ArgumentParser(description="Start or stop tenants.")
    parser.add_argument("--tenants", type=str, required=True, help="Comma-separated list of tenant IDs.")
    parser.add_argument("--action", type=str, choices=["start", "stop"], required=True, help="Action to perform: start or stop.")

    args = parser.parse_args()
    tenant_list = args.tenants.split(",")
    logging.info(f"start stop mechanism strat running with these arguments: {tenant_list=}, {args.action=}")

    # in case of any failure, the script
    if final_report := start_stop_mechanism(set(tenant_list), args.action):
        check_final_report(final_report_list=final_report, action=args.action)
