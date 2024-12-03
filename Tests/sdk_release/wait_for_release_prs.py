import argparse
import os
import sys
import time
from pathlib import Path

import requests
import urllib3
from create_content_pr import CONTENT_PR_NUMBER_FILE
from create_sdk_pr import SDK_PR_NUMBER_FILE
from gitlab.v4.objects import ProjectMergeRequest

from Tests.scripts.utils import logging_wrapper as logging
from Tests.scripts.utils.log_util import install_logging
from Tests.sdk_release.update_sdk_v_in_infra import INFRA_MR_NUMBER_FILE, get_gitlab_project

# Disable insecure warnings
urllib3.disable_warnings()

PR_BY_ID_TEMPLATE = "https://api.github.com/repos/demisto/{repo}/pulls/{pr_id}"
# the default is the id of infra repo in xdr.pan.local
GITLAB_PROJECT_ID = int(os.getenv("CI_PROJECT_ID", 1701))
# disable-secrets-detection

TIMEOUT = 60 * 60 * 6  # 6 hours


def get_pr_by_id(repository, pr_id, access_token):
    url = PR_BY_ID_TEMPLATE.format(repo=repository, pr_id=pr_id)
    res = requests.get(url, headers={"Authorization": f"Bearer {access_token}"}, verify=False)
    if res.status_code != requests.codes.ok:
        logging.error(f"Failed to retrieve pull request with id {pr_id}")
        logging.error(res.text)
        sys.exit(1)

    return res.json()


def get_mr_by_id(ci_token: str, project_id: int, mr_id: int) -> ProjectMergeRequest:
    """Retrieve the MR info from Gitlab.
    Args:
        ci_token (str): the gitlab token.
        project_id (int): The project id of the repo from which to retrieve the MR info.
        mr_id (int): The iid of the MR.
    Returns:
        A ProjectMergeRequest object containing the info of the requested MR.
        A link to the documentation: https://docs.gitlab.com/ee/api/commits.html#get-a-single-commit
    """
    project = get_gitlab_project(ci_token, project_id)
    return project.mergerequests.get(mr_id)


def options_handler():
    parser = argparse.ArgumentParser(description="Creates release pull request for demisto-sdk.")

    parser.add_argument("-t", "--access_token", help="Github access token", required=True)
    parser.add_argument("-b", "--release_branch_name", help="The name of the release branch", required=True)
    parser.add_argument("--artifacts-folder", help="Artifacts folder to get the content and sdk pr id files", required=True)
    parser.add_argument("-c", "--ci_token", help="The token for circleci/gitlab", required=True)

    options = parser.parse_args()
    return options


def main():
    install_logging("wait_for_release_prs.log", logger=logging)

    options = options_handler()
    access_token = options.access_token
    artifacts_folder = options.artifacts_folder
    ci_token = options.ci_token
    errors = []

    # get the content pr id from the file
    try:
        content_pr_id = Path(artifacts_folder, CONTENT_PR_NUMBER_FILE).read_text()
    except Exception as e:
        logging.error(f"Failed to read the file {CONTENT_PR_NUMBER_FILE}, error: {e!s}")
        sys.exit(1)

    # get the sdk pr id from the file
    try:
        sdk_pr_id = Path(artifacts_folder, SDK_PR_NUMBER_FILE).read_text()
    except Exception as e:
        logging.error(f"Failed to read the file {SDK_PR_NUMBER_FILE}, error: {e!s}")
        sys.exit(1)

    # get the infra pr id from the file
    try:
        infra_mr_id = Path(artifacts_folder, INFRA_MR_NUMBER_FILE).read_text()
    except Exception as e:
        logging.error(f"Failed to read the file {INFRA_MR_NUMBER_FILE}, error: {e!s}")
        sys.exit(1)

    content_pr = get_pr_by_id("content", content_pr_id, access_token)
    sdk_pr = get_pr_by_id("demisto-sdk", sdk_pr_id, access_token)
    infra_mr = get_mr_by_id(ci_token, GITLAB_PROJECT_ID, int(infra_mr_id))

    # initialize timer
    start = time.time()
    elapsed: float = 0

    # wait to content pr and sdk pr to be closed
    while elapsed < TIMEOUT:
        content_pr = get_pr_by_id("content", content_pr_id, access_token)
        sdk_pr = get_pr_by_id("demisto-sdk", sdk_pr_id, access_token)
        infra_mr = get_mr_by_id(ci_token, GITLAB_PROJECT_ID, int(infra_mr_id))

        content_pr_state = content_pr.get("state")
        sdk_pr_state = sdk_pr.get("state")
        infra_mr_state = infra_mr.state

        logging.info(f"content pr state is {content_pr_state}")
        logging.info(f"sdk pr state is {sdk_pr_state}")
        logging.info(f"infra mr state is {infra_mr_state}")

        if sdk_pr_state != "open" and content_pr_state != "open" and infra_mr_state != "opened":
            break

        time.sleep(300)  # 5 minutes
        elapsed = time.time() - start

        if elapsed >= TIMEOUT:
            errors.append("Timeout reached while waiting for SDK and content pull requests to be merged")

    # check that content pr is merged
    if not content_pr.get("merged"):
        errors.append(f'content pull request not merged yet {content_pr.get("html_url")}')

    # check that sdk pr is merged
    if not sdk_pr.get("merged"):
        errors.append(f'demisto-sdk pull request not merged yet {sdk_pr.get("html_url")}')

    # check that infra mr is merged
    if infra_mr.state != "merged":
        errors.append(f'Infra merge request not merged yet {infra_mr.get("web_url")}')

    if errors:
        logging.error("\n".join(errors))
        sys.exit(1)

    logging.success("SDK and content pull requests merged successfully!")


if __name__ == "__main__":
    main()
