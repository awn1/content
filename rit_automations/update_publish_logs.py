import argparse
import csv
import json
import logging
import os
import subprocess
from datetime import datetime
from distutils.util import strtobool
from pathlib import Path

from gitlab import Gitlab

from Tests.Marketplace.marketplace_services import init_storage_client
from Tests.scripts.gitlab_client import GitlabMergeRequest
from Tests.scripts.utils.log_util import install_logging

# GitLab Configuration
GITLAB_PROJECT_ID = os.getenv("CI_PROJECT_ID", 2149)  # Default: prisma-collectors repo ID
GITLAB_SERVER_URL = os.getenv("CI_SERVER_URL", "https://gitlab.xdr.pan.local")
GITLAB_USER_NAME = os.getenv("GITLAB_USER_NAME")
GITLAB_USER_LOGIN = os.getenv("GITLAB_USER_LOGIN")  # Used for Slack mentions

# Slack Notification Files
ARTIFACTS_FOLDER = os.getenv("ARTIFACTS_FOLDER", "")
SLACK_OPENED_MR_FILE = "publish_logs_opened_mr.txt"
SLACK_PUBLISH_FILE = "slack_publish_file.txt"
SLACK_MR_NOTIFICATION_TEMPLATE = (
    f"Hi <@{GITLAB_USER_LOGIN}>, Please check if the following opened MRs should be merged before publishing your version:\n• "
)

# Publish Flags
TODAY_TIMESTAMP = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
IS_PUBLISH = strtobool(os.getenv("PUBLISH", "False"))
PUBLISH_LOGS_FILE_NAME = os.getenv("PUBLISH_LOGS_FILE_NAME", "publish_logs.csv")
PUBLISH_LOG_FILE_PATH = f"platform-rits-content/{PUBLISH_LOGS_FILE_NAME}"

# Cloud Storage Paths
PATH_SRC_BUCKET = os.getenv("PATH_SRC_BUCKET", "")
DEST_BUCKET = os.getenv("DEST_BUCKET", "")
PLATFORM_VERSION = os.getenv("PLATFORM_VERSION", "")
INTERNAL_DEV_BUCKET_NAME = os.getenv("INTERNAL_DEV_BUCKET_NAME", "marketplace-cortex-content-build")

# CSV File Headers for Publish Logs
PUBLISH_LOG_FILE_HEADER = [
    "timestamp",
    "platform_version",
    "destination_bucket",
    "tenant/default",
    "file_name",
    "branch",
    "merge_request_number",
    "triggered_by",
    "source_path",
    "destination_path",
    "merge_request_link",
    "is_merged",
]


def generate_publish_slack_message(tenant_ids: list[str], dest_bucket_name: str, file_name: str) -> None:
    """
    Generates a Slack message summarizing the file upload process and saves it.

    Args:
        tenant_ids (list[str]): A list of tenant IDs for which the file is being uploaded.
        dest_bucket_name (str): The name of the destination bucket.
        file_name (str): The name of the file being uploaded.
    """
    slack_message = f"*Publish {PLATFORM_VERSION} ({TODAY_TIMESTAMP})*\nTriggered by @{GITLAB_USER_LOGIN}\n"
    slack_message += f"Published from <{PATH_SRC_BUCKET}|{Path(PATH_SRC_BUCKET).name}>\n"
    slack_message += f"Published to *{DEST_BUCKET}* bucket:\n"
    for tenant_id in tenant_ids:
        dest_url = (
            f"https://console.cloud.google.com/storage/browser/{dest_bucket_name}/{PLATFORM_VERSION}/{tenant_id}/{file_name}"
        )
        slack_message += f"• <{dest_url}|{tenant_id}>\n"

    with open(Path(ARTIFACTS_FOLDER, SLACK_PUBLISH_FILE), "w") as slack_publish_file:
        json.dump([{"color": "good", "text": slack_message}], slack_publish_file)


def parse_published_file() -> tuple[str, str]:
    """
    Parse the file name to extract platform version and commit hash.

    Returns:
        tuple: (file_name, commit_hash) if successful, or (None, None) if an error occurs.
    """
    file_name = Path(PATH_SRC_BUCKET).name

    if not file_name.startswith(PLATFORM_VERSION):
        file_name = f"{PLATFORM_VERSION}_{file_name}"

    commit_hash = file_name.split("_")[2]  # Assuming commit hash is at this position
    return file_name, commit_hash


def get_mr_and_branch(gitlab_token: str, commit_hash: str) -> tuple[str, str, str]:
    """
    Retrieve the merge request or branch name for a given commit hash.

    Args:
        gitlab_token (str): GitLab private token to authenticate with the GitLab API.
        commit_hash (str): The commit hash to look up.

    Returns:
        tuple: A tuple containing the branch name, merge request number, and merge request link.
            If no MR is found, the MR number and link will be empty strings.
            Example: ("branch_name", "mr_number", "mr_link")
    """
    try:
        subprocess.run(["git", "fetch", "--all"], capture_output=True, text=True, check=True)
        result = subprocess.run(["git", "branch", "-r", "--contains", commit_hash], capture_output=True, text=True, check=True)

        branch_name = result.stdout.splitlines()[0].strip().replace("origin/", "") if result.stdout else "Unknown"

        # If there is an open merge request, return the MR link, otherwise return the branch
        merge_request = GitlabMergeRequest(gitlab_token, branch=branch_name)
        if mr_data := merge_request.data:
            return branch_name, mr_data["iid"], mr_data["web_url"]
        return branch_name, "", ""

    except subprocess.CalledProcessError as e:
        logging.error(f"Error fetching branch: {e}")
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
    return "Unknown", "", ""


def update_merge_status(existing_rows: list[dict], gitlab_client: Gitlab) -> None:
    """
    Update the 'is_merged' status for existing rows by checking their merge request status.

    Args:
        existing_rows (list[dict]): List of existing log entries to update.
        gitlab_client (Gitlab): GitLab client instance to interact with GitLab API.
    """
    pending_mrs: set[str] = set()

    for row in existing_rows:
        mr_id = row.get("merge_request_number", "").strip()
        if mr_id and not strtobool(row.get("is_merged") or "no"):
            try:
                mr = gitlab_client.projects.get(GITLAB_PROJECT_ID).mergerequests.get(int(mr_id))
                row["is_merged"] = "yes" if mr.state in {"merged", "closed"} else "no"
            except Exception as e:
                logging.warning(f"Failed to check MR-{mr_id} status: {e}")
                row["is_merged"] = "no"
            if row["is_merged"] == "no" and row.get("merge_request_link"):
                pending_mrs.add(row["merge_request_link"])

    if pending_mrs:
        with open(Path(ARTIFACTS_FOLDER, SLACK_OPENED_MR_FILE), "w") as slack_msg_file:
            json.dump(
                [{"color": "bad", "text": SLACK_MR_NOTIFICATION_TEMPLATE + "\n• ".join(pending_mrs)}],
                slack_msg_file,
                indent=4,
                default=str,
                sort_keys=True,
            )


def update_publish_logs(gitlab_token: str, log_entries: list[dict] = []) -> None:
    """
    Update the publish logs in a Google Cloud Storage bucket in CSV format.

    Args:
        gitlab_token (str): GitLab private token for authentication.
        log_entries (list[dict]): A list of log entries to append to the existing logs.
    """
    storage_client = init_storage_client()
    storage_bucket = storage_client.bucket(INTERNAL_DEV_BUCKET_NAME)
    blob = storage_bucket.blob(PUBLISH_LOG_FILE_PATH)
    gitlab_client = Gitlab(GITLAB_SERVER_URL, private_token=gitlab_token)

    try:
        existing_rows = list(csv.DictReader(blob.download_as_text().splitlines())) if blob.exists() else []
        update_merge_status(existing_rows, gitlab_client)

        with blob.open("w") as log_file:
            writer = csv.DictWriter(log_file, fieldnames=PUBLISH_LOG_FILE_HEADER)
            writer.writeheader()
            writer.writerows(existing_rows + log_entries if log_entries else existing_rows)

        logging.info(f"Updated publish logs in GCS: {INTERNAL_DEV_BUCKET_NAME}/{PUBLISH_LOG_FILE_PATH}")
    except Exception as e:
        logging.exception(f"Failed to update publish logs in GCS: {e}")


def options_handler() -> argparse.Namespace:
    """
    Parse command-line arguments.

    Returns:
        argparse.Namespace: Parsed arguments object containing user inputs.
    """
    parser = argparse.ArgumentParser(description="Generate changelog and push a new tag.")
    parser.add_argument("--tenants", nargs="+", default=[], required=False, help="List of tenant IDs.")
    parser.add_argument("--gitlab-token", default=os.getenv("GITLAB_STATUS_TOKEN"), help="GitLab private token for API access.")
    parser.add_argument("--dest-bucket-name", required=False, help="The destination bucket name.")
    return parser.parse_args()


def main():
    """
    Main function to parse arguments, get commit data, and update publish logs.
    """
    install_logging("update_publish_logs.log")
    options = options_handler()
    log_entries = []
    options.tenants = list(filter(str.strip, options.tenants))
    if IS_PUBLISH:
        file_name, commit_hash = parse_published_file()
        branch, mr_number, mr_link = get_mr_and_branch(options.gitlab_token, commit_hash)
        log_entries = [
            {
                "timestamp": TODAY_TIMESTAMP,
                "platform_version": PLATFORM_VERSION,
                "destination_bucket": options.dest_bucket_name,
                "tenant/default": tenant,
                "file_name": file_name,
                "branch": branch,
                "merge_request_number": mr_number,
                "triggered_by": GITLAB_USER_NAME,
                "source_path": PATH_SRC_BUCKET,
                "destination_path": f"gs://{options.dest_bucket_name}/{PLATFORM_VERSION}/{tenant}/{file_name}",
                "merge_request_link": mr_link,
                "is_merged": "",  # Assuming this will be updated later
            }
            for tenant in options.tenants
        ]
        generate_publish_slack_message(options.tenants, options.dest_bucket_name, file_name)

    update_publish_logs(options.gitlab_token, log_entries)


if __name__ == "__main__":
    main()
