import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import gitlab

from Tests.scripts.gitlab_client import GitlabMergeRequest
from Tests.scripts.utils.log_util import install_logging

GITLAB_PROJECT_ID = os.getenv("CI_PROJECT_ID", 2149)  # Default: prisma-collectors repo ID
GITLAB_SERVER_URL = os.getenv("CI_SERVER_URL", "https://gitlab.xdr.pan.local")
CI_COMMIT_REF_NAME = os.getenv("CI_COMMIT_REF_NAME", "master")
ARTIFACTS_FOLDER = os.getenv("ARTIFACTS_FOLDER") or ""
CI_COMMIT_SHA = os.getenv("CI_COMMIT_SHA") or ""
SLACK_CHANGELOG_FILE = "slack_changelog.txt"
GCS_DEST_PATH = Path(ARTIFACTS_FOLDER, "gcs_destination_path.txt")


def get_branches_from_git() -> list[str]:
    """
    Retrieve a list of branch names from merge commits in the Git log.
    When release from hotfix starting from the first branch's commit
    When release from master starting from the previous tag (v*)
    Returns:
        List[str]: A list of branch names merged after the given commit SHA.
        If no branches are found, returns an empty list.
    Raises:
        SystemExit: If the Git commands fail, the function logs the exception and exits.
    """
    try:
        if CI_COMMIT_REF_NAME == "master":
            command = (
                f"git fetch origin {CI_COMMIT_REF_NAME} --depth=1000 && "  # Fetch the remote branch explicitly
                f"latest_tag=$(git tag -l 'v*' --sort=-creatordate | head -n 1) && "  # from the latest tag
                f"git rev-list $latest_tag..{CI_COMMIT_SHA} --merges --pretty=format:'%s' | "
                f"grep -E \"Merge branch '.*' into '(master|dev)'\" | "
                f"sed -E \"s/Merge branch '([^']+)' into '(master|dev)'/\\1/\""
            )
        else:  # hotfix
            command = (
                f"git fetch origin {CI_COMMIT_REF_NAME} --depth=1000 && "
                f"git fetch origin master --depth=1000 && "
                f"first_commit=$(git rev-list origin/master..origin/{CI_COMMIT_REF_NAME} | tail -n 1) && "
                f"git rev-list $first_commit..{CI_COMMIT_SHA} --merges --pretty=format:'%s' | "
                f"grep -E \"Merge branch '.*' into '{CI_COMMIT_REF_NAME}'\" | "
                f"sed -E \"s/Merge branch '([^']+)' into '{CI_COMMIT_REF_NAME}'/\\1/\""
            )

        result = subprocess.check_output(command, shell=True, text=True)
        branches = result.strip().split("\n") if result.strip() else []
        return list(set(branches))
    except subprocess.CalledProcessError as e:
        logging.exception(f"Error while fetching branches using git rev-list: {e}")
        sys.exit(1)


def generate_changelog(branches: list[str], platform_version: str, gitlab_token: str) -> tuple[str, str]:
    """
    Generate changelogs in Markdown and Slack-compatible formats based on the provided branches and GitLab merge request data.

    Args:
        branches (list[str]): A list of branch names to fetch merge requests from.
        platform_version (str): The platform version for the release (e.g., '1.0.0').
        gitlab_token (str): GitLab personal access token for API authentication.

    Returns:
        Tuple[str, str]: A tuple containing two strings: the first is the Markdown-formatted changelog
                         and the second is the Slack-compatible changelog.
    """
    markdown_lines = []
    slack_lines = []

    for branch in branches:
        merge_request = GitlabMergeRequest(gitlab_token, branch=branch, state="merged")
        if mr_data := merge_request.data:
            mr_title = mr_data.get("title") or branch
            author = mr_data.get("author", {}).get("username", "Unknown Author")
            mr_link = mr_data.get("web_url")

            markdown_lines.append(f"- [{mr_title}]({mr_link}) by @{author}")

            slack_lines.append(f"• <{mr_link}|{mr_title}> by @{author}")

    today = datetime.now().strftime("%Y-%m-%d-%H-%M")
    changelog_header = f"# Release {platform_version} ({today})"
    markdown_changelog = f"{changelog_header}\n" + "\n".join(markdown_lines)

    slack_header = f"*Release {platform_version} ({today})*"
    slack_changelog = f"{slack_header}\n" + "\n".join(slack_lines)

    return markdown_changelog, slack_changelog


def push_new_tag(platform_version: str, changelog: str, gitlab_token: str):
    """
    Create and push a new Git tag using the GitLab API.

    Args:
        platform_version (str): The platform_version of the tag to be created.
        changelog (str): The changelog message to associate with the tag.
        gitlab_token (str): The GitLab token for authenticating the API requests.
    """
    today = datetime.now().strftime("%Y%m%d%H%M%S")
    tag = f"v{platform_version}_{today}" if CI_COMMIT_REF_NAME == "master" else f"hf{platform_version}_{today}"
    try:
        gl = gitlab.Gitlab(GITLAB_SERVER_URL, private_token=gitlab_token)
        project = gl.projects.get(GITLAB_PROJECT_ID)
        logging.info(f"Creating a new tag: {tag}")
        project.tags.create(
            {
                "tag_name": tag,
                "ref": os.getenv("CI_COMMIT_SHA"),
            }
        )
        logging.info(f"Creating a release for tag: {tag}")
        project.releases.create(
            {
                "name": f"Release {tag}",
                "tag_name": tag,
                "description": changelog,
            }
        )
        logging.info(f"Tag '{tag}' created successfully in GitLab!")
    except gitlab.exceptions.GitlabCreateError as e:
        logging.exception(f"Failed to create tag '{tag}' in GitLab: {e}")
        sys.exit(1)


def save_slack_changelog(slack_changelog_content: str) -> None:
    """
    Generate a changelog in Slack-compatible format and save it to a file.

    Args:
        slack_changelog_content (str): The Slack changelog content.
    """
    with open(GCS_DEST_PATH) as gcs_dest_file:
        gcs_dest_content = json.load(gcs_dest_file)

    with open(Path(ARTIFACTS_FOLDER, SLACK_CHANGELOG_FILE), "w") as slack_msg_file:
        json.dump(
            [{"color": "good", "text": slack_changelog_content}] + gcs_dest_content,
            slack_msg_file,
            indent=4,
            default=str,
            sort_keys=True,
        )

    logging.info(f"The file {SLACK_CHANGELOG_FILE} created successfully")


def options_handler() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate changelog and push a new tag.")
    parser.add_argument("--tag", default=os.getenv("PLATFORM_VERSION"), help="The new tag to create.")
    parser.add_argument("--gitlab-token", default=os.getenv("GITLAB_STATUS_TOKEN"), help="GitLab private token for API access.")
    return parser.parse_args()


def main():
    install_logging("generate_tag_and_changelog.log")
    options = options_handler()

    if not options.tag or not options.gitlab_token:
        logging.error("Missing required arguments or environment variables.")
        sys.exit(1)
    branches = get_branches_from_git()
    if not branches:
        logging.warning("No branches found from git rev-list. Proceeding without a changelog.")
        markdown_changelog = slack_changelog = "No changelog available for this release."
    else:
        logging.info(f"Branches found from git rev-list: {branches}")
        markdown_changelog, slack_changelog = generate_changelog(branches, options.tag, options.gitlab_token)
        logging.debug(f"Generated Changelog: {markdown_changelog}")
    push_new_tag(options.tag, markdown_changelog, options.gitlab_token)
    save_slack_changelog(slack_changelog)


if __name__ == "__main__":
    main()
