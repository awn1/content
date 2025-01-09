import argparse
import logging
import os
import re
import sys

import requests
import urllib3
from gitlab import GitlabGetError

from Tests.scripts.common import get_slack_user_name
from Tests.scripts.utils.log_util import install_logging
from Tests.sdk_release.update_sdk_v_in_infra import get_gitlab_project

# Disable insecure warnings
urllib3.disable_warnings()

# regex to validate that the version format is correct e.g: <2.1.3>
VERSION_FORMAT_REGEX = "\d{1,3}\.\d{1,3}\.\d{1,3}"

GITHUB_USER_URL = "https://api.github.com/users/{username}"
GITHUB_BRANCH_URL = "https://api.github.com/repos/demisto/demisto-sdk/branches/{branch_name}"
GITLAB_PROJECT_ID = int(os.getenv("CI_PROJECT_ID", 1701))


def options_handler():
    parser = argparse.ArgumentParser(description="Triggers update-demisto-sdk-version workflow")

    parser.add_argument("-t", "--github_token", help="Github access token", required=True)
    parser.add_argument("-v", "--release_version", help="The release version", required=True)
    parser.add_argument("-r", "--reviewer", help="The reviewer of the pull request", required=True)
    parser.add_argument(
        "-b",
        "--sdk_branch_name",
        help="From which branch in demisto-sdk we want to create the release",
        required=True,
    )
    parser.add_argument("-n", "--name-mapping_path", help="Path to name mapping file.", required=True)
    parser.add_argument("-c", "--ci_token", help="The token for circleci/gitlab", required=True)
    options = parser.parse_args()
    return options


def main():
    install_logging("pre_validations.log")
    options = options_handler()
    github_token = options.github_token
    release_version = options.release_version
    reviewer = options.reviewer
    sdk_branch_name = options.sdk_branch_name
    ci_token = options.ci_token
    errors = []

    # validate version format
    if not re.match(VERSION_FORMAT_REGEX, release_version):
        errors.append(
            f"The SDK release version {release_version} is not according to the expected format."
            f" The format of version should be in x.y.z format, e.g: <2.1.3>"
        )

    # validate if github user exists
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {github_token}",
    }
    url = GITHUB_USER_URL.format(username=reviewer)
    response = requests.request("GET", url, headers=headers, verify=False)
    if response.status_code != requests.codes.ok:
        errors.append(f"Failed to retrieve the user {reviewer} from github,\nerror: {response.text}")

    # validate if branch exists
    url = GITHUB_BRANCH_URL.format(branch_name=sdk_branch_name)
    response = requests.request("GET", url, headers=headers, verify=False)
    if response.status_code != requests.codes.ok:
        errors.append(f"Failed to retrieve the branch {sdk_branch_name} from demisto-sdk repo,\nerror: {response.text}")

    # validate if the user exists in name_mapping.json file
    slack_user_name = get_slack_user_name(reviewer, None, options.name_mapping_path)
    if slack_user_name is None:
        errors.append(f"The user {reviewer} not exists in the name_mapping.json file")

    # validate that the infra future release branch doesn't exist
    project = get_gitlab_project(ci_token, GITLAB_PROJECT_ID)
    infra_branch_name = f"update_infra_with_sdk_{release_version}"
    try:
        existing_branch = project.branches.get(infra_branch_name)
        if existing_branch:
            errors.append(
                f"The infra branch that should be used for the release {infra_branch_name} already exist in Infra repo."
            )
    except GitlabGetError:
        logging.debug(f"The branch {infra_branch_name} doesn't exist in Infra repo")

    if errors:
        logging.error("\n".join(errors))
        sys.exit(1)


if __name__ == "__main__":
    main()
