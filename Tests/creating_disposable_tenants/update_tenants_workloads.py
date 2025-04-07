import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from Tests.creating_disposable_tenants.create_disposable_tenants import send_slack_notification
from Tests.scripts.infra.resources.constants import COMMENT_FIELD_NAME
from Tests.scripts.infra.xsoar_api import XsiamClient
from Tests.scripts.utils import logging_wrapper as logging
from Tests.scripts.utils.log_util import install_logging

COMMAND_TIMEOUT = 60  # seconds
KUBECTL_SET_RESOURCES = (
    "kubectl set resources deployment xdr-st-{lcaas_id}-{pod} "
    "--limits=cpu={cpu_limit},memory={memory_limit} "
    "--requests=cpu={cpu_request},memory={memory_request} "
    "--namespace={namespace}"
)
NAMESPACE = "xdr-st"
CONTETN_LIMITS = {
    "cpu_limit": 4,
    "memory_limit": "16Gi",
    "cpu_request": 1,
    "memory_request": "4Gi",
    "namespace": NAMESPACE,
}
API_LIMITS = {
    "cpu_limit": 2,
    "memory_limit": "6Gi",
    "cpu_request": 2,
    "memory_request": "6Gi",
    "namespace": NAMESPACE,
}


def run_command(command: str) -> tuple[str, bool]:
    """
    Run a shell command and handle errors.

    Args:
        command (str): The shell command to execute.

    Returns:
        tuple[str, bool]: A tuple containing the command output (str) and a success flag (bool).
        If the command succeeds, returns (output, True). If it fails, returns ("", False).
    """
    try:
        logging.debug(f"Running command: {command}")
        result = subprocess.run(command, shell=True, check=True, capture_output=True, text=True, timeout=COMMAND_TIMEOUT)
        return result.stdout.strip(), True
    except subprocess.CalledProcessError as e:
        logging.error(f"Error running command: {command}\n{e.stderr.strip()}")
        return "", False


def options_handler() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Wait for disposable tenants to be ready.")
    parser.add_argument(
        "--tenants-file-path",
        required=True,
        type=Path,
        help="The path to the file containing the tenants info.",
    )

    return parser.parse_args()


def main() -> None:
    install_logging("update_tenants_workloads.log", logger=logging)
    try:
        args = options_handler()
        new_tenants_info = json.loads(args.tenants_file_path.read_text())
        new_tenants_info.pop(COMMENT_FIELD_NAME, None)
        successfully_tenants = []
        error_tenants = []
        for tenant, details in new_tenants_info.items():
            lcaas_id = tenant.split("-")[-1]
            server_type = details.get("server_type")

            logging.info(f"Processing tenant {tenant} with server type {server_type}...")

            # Fetch cluster information
            cluster_info, _ = run_command(f"gcloud container clusters list --project {tenant} --format json")
            if not cluster_info:
                error_tenants.append(tenant)
                continue

            # Extract cluster name and zone
            try:
                cluster_data = json.loads(cluster_info)[0]
                cluster_name = cluster_data["name"]
                cluster_zone = cluster_data["zone"]
            except (IndexError, KeyError, json.JSONDecodeError):
                logging.error(f"Error extracting cluster details for project {tenant}. Skipping...")
                error_tenants.append(tenant)
                continue

            # Get Kubernetes credentials
            _, success = run_command(
                f"gcloud container clusters get-credentials {cluster_name} --zone {cluster_zone} --project {tenant}"
            )
            if not success:
                error_tenants.append(tenant)
                continue

            # Set resource limits and requests for the primary deployment
            _, success = run_command(KUBECTL_SET_RESOURCES.format(**CONTETN_LIMITS, lcaas_id=lcaas_id, pod="xsoar-content"))
            if not success:
                error_tenants.append(tenant)
                continue

            # Additional command for XSIAM server type
            if server_type == XsiamClient.SERVER_TYPE:
                _, success = run_command(KUBECTL_SET_RESOURCES.format(**API_LIMITS, lcaas_id=lcaas_id, pod="api"))
                if not success:
                    error_tenants.append(tenant)
                    continue
                logging.debug("Additional resources set for XSIAM server type.")

            successfully_tenants.append(tenant)
            logging.success(f"Completed processing for project {tenant}.")

        if successfully_tenants:
            logging.success(
                f"Successfully processed for the following tenants:{os.linesep}{os.linesep.join(successfully_tenants)}"
            )

        if error_tenants:
            logging.error(f"The following tenants could not be processed:{os.linesep}{os.linesep.join(error_tenants)}")
            send_slack_notification(
                "danger",
                f"Failed to update workloads for {len(error_tenants)} tenants",
                f"The following tenants failed to update their workloads:\n"
                f"{os.linesep.join(map(lambda tenant: f'• {tenant}', error_tenants))}",
            )
            sys.exit(1)
        send_slack_notification(
            "good",
            "Successfully updated workloads for all tenants",
            f"Updated workloads for {len(successfully_tenants)} tenants.",
        )

    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}")
        send_slack_notification("danger", "Error occurred while updating tenants workloads", "See logs for more details.")
        sys.exit(1)


if __name__ == "__main__":
    main()
