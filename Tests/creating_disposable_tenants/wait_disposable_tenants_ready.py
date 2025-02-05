import argparse
import contextlib
import json
import logging
import os
import sys
import time
from pathlib import Path

import humanize

from Tests.scripts.infra.resources.constants import COMMENT_FIELD_NAME
from Tests.scripts.infra.viso_api import VisoAPI
from Tests.scripts.utils.log_util import install_logging

STATUS_FIELD_NAME = "status"
READY_STATUS = "running"
ERROR_STATUS = ("provisioning_error", "updating_error", "expired", "deleting", "deleting_error", "deleted")
TIMEOUT = 60 * 120  # 2 hours
SLEEP_INTERVAL = 60 * 5  # 5 minutes


def load_json_file(file_path: Path) -> dict:
    with contextlib.suppress(Exception):
        return json.loads(file_path.read_text())
    logging.error(f"Error loading JSON file at: {file_path}")
    return {}


def options_handler() -> argparse.Namespace:
    install_logging("wait_disposable_tenants_ready.log", logger=logging)
    parser = argparse.ArgumentParser(description="Wait for disposable tenants to be ready.")
    parser.add_argument(
        "--tenates-file-path",
        required=True,
        type=Path,
        help="The path to the file containing the tenants info.",
    )

    return parser.parse_args()


def main() -> None:
    args = options_handler()
    try:
        CONTENT_TENANTS_GROUP_OWNER = os.environ["CONTENT_TENANTS_GROUP_OWNER"]
        VISO_API_URL = os.environ["VISO_API_URL"]
        VISO_API_KEY = os.environ["VISO_API_KEY"]
        viso_api = VisoAPI(base_url=VISO_API_URL, api_key=VISO_API_KEY)

        new_tenates_info = load_json_file(args.tenates_file_path)
        new_tenates_info.pop(COMMENT_FIELD_NAME, None)

        # initialize timer
        start_time: float = time.time()
        elapsed: float = 0

        ready_tenants: set = set()
        not_ready_tenants: set = set(new_tenates_info.keys())
        while elapsed < TIMEOUT:
            logging.info("Checking tenants status...")
            viso_tenants_info: dict = viso_api.get_all_tenants(
                group_owner=CONTENT_TENANTS_GROUP_OWNER, fields=[STATUS_FIELD_NAME]
            )
            all_tenants_info: dict = {item["lcaas_id"]: item for item in viso_tenants_info}
            is_error = False
            for tenant_id in not_ready_tenants.copy():
                lcaas_id = tenant_id.split("-")[-1]
                if lcaas_id in all_tenants_info:
                    tenant_status = all_tenants_info[lcaas_id][STATUS_FIELD_NAME]
                    if tenant_status == READY_STATUS:
                        ready_tenants.add(tenant_id)
                        not_ready_tenants.remove(tenant_id)
                        logging.debug(f"Tenant {tenant_id} is ready")
                    elif tenant_status in ERROR_STATUS:
                        logging.error(f"Tenant {tenant_id} is in `{tenant_status}` status.")
                        is_error = True
                    else:
                        logging.debug(f"Tenant {tenant_id} is not ready, current status: {tenant_status}")
                else:
                    logging.error(f"Tenant {tenant_id} not found in tenants info.")
                    is_error = True

            if not_ready_tenants:
                logging.warning(f"The following tenants are not ready: {', '.join(not_ready_tenants)}")
                if ready_tenants:
                    logging.info(f"The following tenants are ready: {', '.join(ready_tenants)}")
            elif ready_tenants:
                duration = humanize.naturaldelta(elapsed, minimum_unit="milliseconds")
                logging.info(f"All disposable tenants are ready after {duration}.")
                break
            if is_error:
                sys.exit(1)

            elapsed = time.time() - start_time
            if elapsed >= TIMEOUT:
                logging.critical("Timed out waiting for disposable tenants to be ready.")
                sys.exit(1)
            logging.info(f"Go to sleep for {SLEEP_INTERVAL//60} minutes and then check again.")
            time.sleep(SLEEP_INTERVAL)

    except Exception as e:
        logging.error(f"Error waiting for disposable tenants to be ready: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
