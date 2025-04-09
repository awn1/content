import logging
import os
from argparse import ArgumentParser, Namespace
from pathlib import Path

import requests
import urllib3

from Tests.scripts.utils.log_util import install_logging

urllib3.disable_warnings()  # Disable insecure warnings

ARTIFACTS_FOLDER = os.getenv("ARTIFACTS_FOLDER")


def options_handler() -> Namespace:
    parser = ArgumentParser(
        description="A trigger for the pipeline run by the DevOps team to sync the prod us bucket with all other buckets."
    )
    parser.add_argument("--url", help="The Jenkins job URL.", required=True)
    parser.add_argument("--username", help="Jenkins username.", required=True)
    parser.add_argument("--token", help="Jenkins API token.", required=True)
    parser.add_argument(
        "--root_folder",
        help="Optional: if provided, only this root_folder will be synced. If omitted, the entire bucket will be synced.",
        required=False,
    )
    return parser.parse_args()


def main():
    args = options_handler()
    install_logging("trigger_sync_all_buckets.log")

    status_code: str | int = "Some Error"
    payload = {}

    if args.root_folder:
        payload["root_folder"] = args.root_folder
        logging.info(f"Using root_folder: {args.root_folder}")
    else:
        logging.info("No root_folder provided. Full sync will be triggered.")

    try:
        res = requests.post(args.url, verify=False, auth=(args.username, args.token), params=payload)
        res.raise_for_status()
        status_code = res.status_code
        logging.info(f"Jenkins job triggered successfully. Status code: {status_code}")
    except requests.HTTPError as e:
        logging.debug(e.response.content)
        status_code = e.response.status_code
        logging.info(f"Triggered Sync all buckets failed, Status code: {status_code}")
    except Exception as e:
        logging.info(f"Triggered Sync all buckets failed, Error: {e}")
    finally:
        Path(f"{ARTIFACTS_FOLDER}/logs/trigger_sync_all_buckets_status_code.log").write_text(str(status_code))


if __name__ == "__main__":
    main()
