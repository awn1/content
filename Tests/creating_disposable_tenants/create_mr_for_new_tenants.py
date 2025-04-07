import argparse
import base64
import json
import os
import sys
import time
import uuid
from collections import OrderedDict
from distutils.util import strtobool
from pathlib import Path

import gitlab
import urllib3
from gitlab.v4.objects import Project
from tabulate import tabulate

from Tests.creating_disposable_tenants.create_disposable_tenants import send_slack_notification
from Tests.scripts.infra.resources.constants import COMMENT_FIELD_NAME
from Tests.scripts.utils import logging_wrapper as logging
from Tests.scripts.utils.log_util import install_logging
from Tests.scripts.utils.slack import tag_user

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# the id of the project where the MR will be created (content-test-conf repo in xdr.pan.local)
GITLAB_CONTENT_TEST_CONF_PROJECT_ID = "1709"
SAAS_SERVERS_FOLDER = "config"
SAAS_SERVERS_FILE = "saas_servers.json"

GITLAB_SERVER_URL = os.getenv("CI_SERVER_URL", "https://gitlab.xdr.pan.local")
ARTIFACT_PATH: Path = Path(os.getenv("ARTIFACT_PATH", "."))
MR_NUMBER_FILE: Path = ARTIFACT_PATH / "MR_NUMBER.txt"
GITLAB_SSL_VERIFY = bool(strtobool(os.getenv("GITLAB_SSL_VERIFY", "true")))
SLEEP_INTERVAL = 5  # seconds
ATTEMPTS_NUMBER = 4


def get_mr_content(new_tenants_info: list[dict]) -> tuple[str, str]:
    """Get the title and description for a merge request.

    This function generates a merge request title and description based on the
    provided new tenants information.

    Args:
        new_tenants_info (list[dict]): A list of dictionaries containing new tenants' information.

    Returns:
        tuple[str, str]: A tuple containing:
            - The generated merge request title.
            - The generated merge request description.
    """
    server_type = set(tenant["server_type"] for tenant in new_tenants_info)
    flow_type = set(tenant["flow_type"] for tenant in new_tenants_info if tenant["flow_type"])
    mr_title = (
        f"Update saas_servers.json with {len(new_tenants_info)} new tenants "
        f"of server_type {', '.join(server_type)} and flow_type {', '.join(flow_type)}"
    )
    mr_description = (
        "## Update [saas_servers.json](config/saas_servers.json) with the "
        f"following new tenants:\n{tabulate(new_tenants_info, headers='keys', tablefmt='pipe')}"
    )
    return mr_title, mr_description


def update_saas_servers_with_new(project: Project, new_tenants_path: Path) -> tuple[dict, list[dict]]:
    """Updates the SaaS servers information with new tenants' data.

    This function reads SaaS servers and new tenants information from JSON files,
    merges them, and sorts the result based on server_type and flow_type.

    Args:
        saas_servers_path (Path): Path to the JSON file containing SaaS servers information.
        new_tenants_path (Path): Path to the JSON file containing new tenants information.

    Returns:
        tuple[dict, list]: A tuple containing:
            - An OrderedDict with the merged and sorted server information.
            - A list of dictionaries containing the new tenants' information.
    """
    config_files = project.repository_tree(SAAS_SERVERS_FOLDER)
    saas_servers_id = next((file["id"] for file in config_files if file["name"] == SAAS_SERVERS_FILE), None)
    saas_servers_info_file = project.repository_blob(saas_servers_id)

    saas_servers_info = json.loads(base64.b64decode(saas_servers_info_file["content"]))
    new_tenants_info = json.loads(new_tenants_path.read_text())
    merged_info: dict = saas_servers_info | new_tenants_info

    sorted_output_data = OrderedDict(
        sorted(
            merged_info.items(),
            key=lambda item: (item[0] != COMMENT_FIELD_NAME, item[1]["server_type"], item[1]["flow_type"]),
        )
    )
    new_tenants = [
        {"tenant_id": tenant_id, "server_type": tenant_details["server_type"], "flow_type": tenant_details["flow_type"]}
        for tenant_id, tenant_details in new_tenants_info.items()
    ]
    return sorted_output_data, new_tenants


def is_merge_request_ready(project: Project, mr_id: int) -> bool:
    """Check if the merge request is ready to be merged.

    Args:
        project (Project): The GitLab project object.
        mr_id (int): The ID of the merge request.

    Returns:
        bool: True if the merge request is ready to be merged, False otherwise.
    """
    logging.info("Waiting for the merge request to be ready for merge.")
    for i in range(1, ATTEMPTS_NUMBER + 1):
        logging.debug(f"Checking merge status for attempt {i}/{ATTEMPTS_NUMBER}.")
        mr = project.mergerequests.get(mr_id)
        merge_status = mr.merge_status
        if merge_status != "checking":
            break
        logging.debug(f"Current merge status: {merge_status}, sleeping for {SLEEP_INTERVAL} seconds...")
        time.sleep(SLEEP_INTERVAL)

    logging.info(f"Final merge status: {mr.merge_status}")
    return mr.merge_status == "can_be_merged"


def get_gitlab_project(ci_token: str, project_id: str) -> Project:
    """Connects to Gitlab and returns the relevant project information.
    Args:
        ci_token (int): The ci token to connect to gitlab.
        project_id (str): The id of the relevant Gitlab project.
    Returns:
        A Gitlab project.
    """
    gitlab_client = gitlab.Gitlab(GITLAB_SERVER_URL, private_token=ci_token, ssl_verify=GITLAB_SSL_VERIFY)
    return gitlab_client.projects.get(project_id)


def options_handler() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create MRs for new tenants")
    parser.add_argument("-c", "--ci-token", help="The token for circleci/gitlab", required=True)
    parser.add_argument("-r", "--reviewer", help="The gitlab username of the reviewer", required=True)
    parser.add_argument(
        "--tenants-file-path",
        required=True,
        type=Path,
        help="The path to the file containing the tenants info.",
    )
    options = parser.parse_args()

    return options


def main():
    install_logging("create_mr_for_new_tenants.log", logger=logging)
    try:
        args = options_handler()
        ci_token: str = args.ci_token
        reviewer: str = args.reviewer

        logging.info("Connecting to gitlab.")
        project = get_gitlab_project(ci_token, GITLAB_CONTENT_TEST_CONF_PROJECT_ID)
        updated_saas_servers, new_tenants_info = update_saas_servers_with_new(project, args.tenants_file_path)
        mr_title, mr_description = get_mr_content(new_tenants_info)
        reviewer_id = project.users.list(search=reviewer)[0].id
        branch_name = f"update_saas_servers_with_new_tenants_{uuid.uuid4().hex[:8]}"
        branch = project.branches.create({"branch": branch_name, "ref": "master"})
        logging.info(f"Created the branch {branch.name}")
        logging.debug(f"All branch details:\n{branch.to_json()}")

        commit_data = {
            "branch": branch_name,
            "commit_message": mr_title,
            "actions": [
                {
                    "action": "update",
                    "file_path": "config/saas_servers.json",
                    "content": json.dumps(updated_saas_servers, indent=2),
                },
            ],
        }
        commit = project.commits.create(commit_data)
        logging.info(f"Created the commit {commit.short_id}")
        logging.debug(f"All commit details:\n{commit.to_json()}")
        mr = project.mergerequests.create(
            {
                "source_branch": branch_name,
                "target_branch": "master",
                "title": mr_title,
                "description": mr_description,
                "reviewer_ids": [reviewer_id],
                "remove_source_branch": True,
            }
        )
        mr_id = mr.get_id()
        logging.info(f"Merge request created with ID {mr_id}, url: {mr.web_url}")
        logging.debug(f"All merge request details:\n{mr.to_json()}")
        if is_merge_request_ready(project, mr_id):
            logging.info("Merge request is ready to be merged.")
            mr.merge(merge_when_pipeline_succeeds=True)
        else:
            logging.warning("Merge request is not ready to be merged, it should be manually merged.")

        # Write the merge request number to a file
        MR_NUMBER_FILE.write_text(str(mr.iid))
        logging.info(f"Merge request number written to {MR_NUMBER_FILE.as_posix()}")
        send_slack_notification(
            "good",
            "Merge request created successfully",
            f"Merge request with ID {mr.iid} has been created and is available at {mr.web_url}.\n"
            f"{tag_user(reviewer)} please review the changes.",
        )
    except Exception as e:
        logging.exception(f"Error occurred: {e}")
        send_slack_notification(
            "danger",
            "Error creating merge request",
            "An error occurred while creating the merge request.\nSee logs for more details.",
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
