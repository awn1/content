import argparse
import json
import os
import sys
import time
from pathlib import Path

from Tests.creating_disposable_tenants.create_disposable_tenants import send_slack_notification
from Tests.scripts.infra.viso_api import VisoAPI
from Tests.scripts.lock_cloud_machines import generate_tenant_token_map, validate_connection_for_machines
from Tests.scripts.utils import logging_wrapper as logging
from Tests.scripts.utils.log_util import install_logging

CONTENT_TENANTS_GROUP_OWNER: str = os.environ["CONTENT_TENANTS_GROUP_OWNER"]
VISO_API_URL: str = os.environ["VISO_API_URL"]
VISO_API_KEY: str = os.environ["VISO_API_KEY"]

TIMEOUT: int = 60 * 120  # 2 hours
SLEEP_INTERVAL: int = 60 * 5  # 5 minutes


def options_handler() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="")
    parser.add_argument(
        "--tenants-file-path",
        required=True,
        type=Path,
        help="The path to the file containing the tenants info.",
    )
    options = parser.parse_args()

    return options


def main() -> None:
    install_logging("tenants_health_check.log", logger=logging)
    try:
        args = options_handler()
        tenants_file_path: Path = args.tenants_file_path
        new_tenants_info: dict[str, dict[str, str | bool]] = json.loads(tenants_file_path.read_text())
        viso_api = VisoAPI(VISO_API_URL, VISO_API_KEY)
        tenants_list = viso_api.get_all_tenants(CONTENT_TENANTS_GROUP_OWNER)
        tenants = {tenant["lcaas_id"]: tenant for tenant in tenants_list}
        tenant_token_map = generate_tenant_token_map(tenants_data=tenants)

        tenants_to_check = list(new_tenants_info)
        healthy_tenants_id: list[str] = []

        start_time: float = time.time()
        elapsed: float = 0
        logging.info("Starting tenant health check")
        while elapsed < TIMEOUT:
            logging.info("Checking health of remaining tenants...")
            for tenant_id in tenants_to_check.copy():
                try:
                    logging.info(f"Validating connection for tenant: {tenant_id}")
                    validate_connection_for_machines([tenant_id], new_tenants_info, tenant_token_map)
                    tenants_to_check.remove(tenant_id)
                    healthy_tenants_id.append(tenant_id)
                    logging.success(f"Connection validated for tenant: {tenant_id}")
                except Exception as e:
                    logging.error(f"Failed to validate connection for tenant: {tenant_id}, error: {e}")
                elapsed = time.time() - start_time
            if not tenants_to_check:
                break
            elif elapsed >= TIMEOUT:
                logging.critical("Timed out while checking tenant health.")
                break
            logging.info(
                f"Some tenants are not healthy: {', '.join(tenants_to_check)}.\n"
                f"Go to sleep for {SLEEP_INTERVAL//60} minutes and try again."
            )
            time.sleep(SLEEP_INTERVAL)
        if healthy_tenants_id:
            logging.info(f"The following tenants are healthy: {', '.join(healthy_tenants_id)}")
        if tenants_to_check:
            logging.error(f"The following tenants are not healthy: {', '.join(tenants_to_check)}")
            send_slack_notification(
                "danger",
                "Tenants Health Check Failed",
                f"The following tenants are not healthy: {', '.join(tenants_to_check)}",
            )
            sys.exit(1)
        logging.success("All tenants are healthy")
        send_slack_notification("good", "Tenants Health Check Succeeded", "All tenants are healthy.")
    except Exception as e:
        logging.exception(f"An unexpected error occurred while validating connection for tenants: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
