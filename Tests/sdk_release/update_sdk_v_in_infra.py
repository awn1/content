import argparse
import json
import os
import subprocess
import sys
from distutils.util import strtobool
from pathlib import Path

import gitlab
from gitlab.v4.objects import Project

from Tests.scripts.common import get_slack_user_name
from Tests.scripts.utils import logging_wrapper as logging
from Tests.scripts.utils.log_util import install_logging
from Tests.sdk_release.create_content_pr import SLACK_MERGE_PRS_FILE
from Tests.sdk_release.create_release import compile_changelog, fetch_changelog

# the default is the id of infra repo in xdr.pan.local
GITLAB_PROJECT_ID = os.getenv("CI_PROJECT_ID", 1701)
# disable-secrets-detection
GITLAB_SERVER_URL = os.getenv("CI_SERVER_URL", "https://gitlab.xdr.pan.local")
INFRA_MR_NUMBER_FILE = "INFRA_PR.txt"


def options_handler():
    """Validates and parses script arguments.

    Returns:
        Namespace: Parsed arguments object.

    """
    parser = argparse.ArgumentParser(description="Parser for slack_notifier args")
    parser.add_argument("-c", "--ci_token", help="The token for circleci/gitlab", required=True)
    parser.add_argument("-rv", "--release_version", help="The sdk release version", required=True)
    parser.add_argument("-r", "--reviewer", help="The github username of the reviewer", required=True)
    parser.add_argument("-n", "--name-mapping_path", help="Path to name mapping file.", required=True)
    parser.add_argument("-d", "--is_draft", help="Is draft pull request", default="FALSE")
    parser.add_argument(
        "-gp",
        "--gitlab_project_id",
        help="The gitlab project id",
        default=GITLAB_PROJECT_ID,
    )
    options = parser.parse_args()

    return options


def create_changelog_file(release_version: str) -> str:
    """Create a new changelog file for the MR.
    Args:
        release_version(str)
    Returns:
        The path to the new changelog file.
    """
    changelog_directory_path = ".changelogs"
    changelog_file_name = f"+sdk_{release_version.replace('.', '_')}.feature.md"
    subprocess.run(
        ["towncrier", "create", changelog_file_name, "-c", f"Updated the demisto-sdk version {release_version} in Infra."]
    )
    changelog_file_path = os.path.join(changelog_directory_path, changelog_file_name)
    logging.info(f"The newly created changelog file path is {changelog_file_path}")
    return changelog_file_path


def prepare_mr(name_mapping_path: str, release_version: str, reviewer: str, project: Project, is_draft: str) -> tuple:
    """Prepare the arguments for the creation of the MR.
    Args:
        name_mapping_path (str): the path to the name mapping file in content-test-conf.
        release_version (str)
        reviewer (str): the GitHub username of the reviewer.
        project (Project): the infra gitlab project.
        is_draft (str): if true - the MR should be a draft MR.
    Returns:
        A tuple of
        1. the content of the sdk version changelog.
        2. the gitlab id of the reviewer.
        3. the title of the MR.
    """
    changelog_file_text = fetch_changelog(release_version)
    relevant_sdk_changelog_text = compile_changelog(changelog_file_text)
    reviewer_gitlab_user_name = get_slack_user_name(reviewer, None, name_mapping_path)
    reviewer_id = project.users.list(search=reviewer_gitlab_user_name)[0].id
    logging.info(f"The reviewer info {reviewer_gitlab_user_name=}, {reviewer_id=}.")
    mr_title = (
        f"Draft: Update Demisto-SDK version {release_version} in Infra"
        if strtobool(is_draft)
        else f"Update Demisto-SDK version {release_version} in Infra"
    )
    return relevant_sdk_changelog_text, reviewer_id, mr_title


def create_slack_message(artifacts_folder: str, infra_mr_number: int, infra_mr_link: str):
    """Create the Slack message.
    Args:
        artifacts_folder (str): the path to the artifacts folder.
        infra_mr_number (int): the number of the infra MR.
        infra_mr_link (str): the link to the infra MR.
    """
    logging.info(f"The parameters to the slack message are {infra_mr_number=} {infra_mr_link=}")

    # write the infra mr number to file
    infra_mr_file = Path(artifacts_folder, INFRA_MR_NUMBER_FILE)
    infra_mr_file.write_text(str(infra_mr_number))

    slack_merge_prs_file = Path(artifacts_folder, SLACK_MERGE_PRS_FILE)
    current_content_of_slack_message = slack_merge_prs_file.read_text()
    current_content_of_slack_message_split = current_content_of_slack_message.split("\n")
    slack_merge_prs_file.write_text(
        f"Please merge the demisto-sdk and content pull requests as well as the Infra merge"
        f" request:\n{current_content_of_slack_message_split[1]}\n"
        f"{current_content_of_slack_message_split[2]}\n{infra_mr_link}"
    )

    logging.success(f"The files {INFRA_MR_NUMBER_FILE}, {SLACK_MERGE_PRS_FILE} created and updated successfully")


def get_gitlab_project(ci_token: str, project_id: int) -> Project:
    """Connects to Gitlab and returns the relevant project information.
    Args:
        ci_token (int): The ci token to connect to gitlab.
        project_id (str): The id of the relevant Gitlab project.
    Returns:
        A Gitlab project.
    """
    gitlab_client = gitlab.Gitlab(GITLAB_SERVER_URL, private_token=ci_token)
    return gitlab_client.projects.get(project_id)


def main():
    install_logging("update_sdk_v_in_infra.log", logger=logging)
    options = options_handler()
    ci_token = options.ci_token
    project_id = options.gitlab_project_id
    release_version = options.release_version
    reviewer = options.reviewer
    is_draft = options.is_draft
    name_mapping_path = options.name_mapping_path
    artifacts_folder = os.getenv("ARTIFACTS_FOLDER") or ""

    logging.info("connecting to gitlab.")
    project = get_gitlab_project(ci_token, project_id)
    branch_name = f"update_infra_with_demisto_sdk_{release_version}"

    branch = project.branches.create({"branch": branch_name, "ref": "master"})
    logging.info(f"created the branch {branch}")

    try:  # make the poetry updates
        subprocess.run(["poetry", "add", f"demisto-sdk@{release_version}"])
        subprocess.run(["poetry", "lock", "--no-update"])
    except Exception as e:
        logging.exception(f"The poetry subprocesses failed {e!s}")
        sys.exit(1)

    changelog_file_path = create_changelog_file(release_version)

    commit_data = {
        "branch": branch_name,
        "commit_message": "create a changelog and poetry updates",
        "actions": [
            {"action": "create", "file_path": changelog_file_path, "content": open(changelog_file_path).read()},
            {"action": "update", "file_path": "pyproject.toml", "content": open("pyproject.toml").read()},
            {"action": "update", "file_path": "poetry.lock", "content": open("poetry.lock").read()},
        ],
    }
    commit = project.commits.create(commit_data)
    logging.info(f"Committed the changes {commit}")

    sdk_changelog_file_text, reviewer_id, mr_title = prepare_mr(name_mapping_path, release_version, reviewer, project, is_draft)

    mr = project.mergerequests.create(
        {
            "source_branch": branch_name,
            "target_branch": "master",
            "title": mr_title,
            "description": sdk_changelog_file_text,
            "reviewer_ids": [reviewer_id],
        }
    )
    logging.info(f"opened the merge request {mr}")

    mr_json = json.loads(mr.to_json())
    logging.info(f"The {mr_json=}")
    create_slack_message(artifacts_folder, mr.iid, mr.web_url)


if __name__ == "__main__":
    main()
