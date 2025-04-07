import argparse
import sys
import time

import urllib3

from Tests.creating_disposable_tenants.create_disposable_tenants import send_slack_notification
from Tests.creating_disposable_tenants.create_mr_for_new_tenants import (
    GITLAB_CONTENT_TEST_CONF_PROJECT_ID,
    MR_NUMBER_FILE,
    get_gitlab_project,
)
from Tests.scripts.utils import logging_wrapper as logging
from Tests.scripts.utils.log_util import install_logging

# Disable insecure warnings
urllib3.disable_warnings()


SLEEP_TIMEOUT = 60 * 5  # 5 minutes
TIMEOUT = 60 * 60 * 6  # 6 hours


def options_handler() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Creates release pull request for demisto-sdk.")
    parser.add_argument("-c", "--ci-token", help="The token for gitlab", required=True)
    parser.add_argument("-mr", "--mr-number", help="The MR number to wait for", required=False)

    return parser.parse_args()


def main():
    install_logging("wait_for_new_tenants_mr.log", logger=logging)
    try:
        args = options_handler()
        ci_token = args.ci_token
        mr_number = int(args.mr_number or MR_NUMBER_FILE.read_text().strip())

        project = get_gitlab_project(ci_token, GITLAB_CONTENT_TEST_CONF_PROJECT_ID)
        # initialize timer
        start = time.time()
        elapsed: float = 0

        logging.info(f"Started waiting for MR #{mr_number} to be merged")
        # wait to mr to be closed
        while elapsed < TIMEOUT:
            mr = project.mergerequests.get(mr_number)

            mr_state = mr.state
            logging.info(f"The current state of the MR is: {mr_state}")

            if mr_state != "opened":
                break

            elapsed = time.time() - start

            if elapsed >= TIMEOUT:
                logging.error("Timeout reached while waiting for SDK and content pull requests to be merged")
                send_slack_notification("danger", "Timeout reached while waiting for new tenants MR to be merged")
                sys.exit(1)

            logging.info(f"Go to sleep for {SLEEP_TIMEOUT//60} minutes, and check again.")
            time.sleep(SLEEP_TIMEOUT)

        # check that the mr is merged
        if mr.state != "merged":
            raise Exception(f"The merge request #{mr_number} was closed but not merged. url: {mr.web_url}")

        send_slack_notification("good", "The new tenants MR has been merged successfully")
        logging.success(f"The merge request #{mr_number} has been merged successfully!")
    except Exception as e:
        logging.exception(e)
        send_slack_notification("danger", "The new tenants MR was not merged successfully", "See logs for more details.")
        sys.exit(1)


if __name__ == "__main__":
    main()
