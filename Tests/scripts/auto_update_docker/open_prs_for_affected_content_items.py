import logging
import os
import re
import subprocess
import sys
import traceback
from datetime import datetime
from typing import Any

import typer
from dotenv import load_dotenv
from git import Git, Repo  # pip install GitPython
from github import Github, Repository  # pip install PyGithub
from tabulate import tabulate

from Tests.scripts.auto_update_docker.utils import (
    STATE_FILE_FIELD_NAMES,
    load_csv_file,
    load_json_file,
    save_csv_file,
    save_json_file,
)
from Tests.scripts.common import slack_link
from Tests.scripts.utils.log_util import install_logging

logging.basicConfig(level=logging.INFO)
load_dotenv()
app = typer.Typer(no_args_is_help=True)
ORG_NAME = "demisto"
REPO_NAME = "content"
BASE_BRANCH = "master"


def create_local_branch(git: Git, branch_name: str):
    """
    Create a new local branch from master or switch to it if it already exists.

    This function attempts to create a new branch from master.
    If the branch already exists, it switches to the existing branch instead.

    Args:
        git (Git): The Git object to perform operations on.
        branch_name (str): The name of the branch to create or switch to.

    Raises:
        git.GitCommandError: If there's an error during Git operations other than
                             the branch already existing.
    """
    try:
        # Try to create a new branch
        git.checkout("-b", branch_name, "master")
        logging.info(f"Branch created: {branch_name}")
    except git.GitCommandError as e:
        # If the branch already exists, check out the existing one
        if "already exists" in str(e):
            logging.info(f"Branch {branch_name} already exists, checking it out.")
            git.checkout(branch_name)
        else:
            raise e  # Re-raise the exception if it's a different error


def create_docker_image_table(docker_images_info: dict) -> str:
    """
    Generate a formatted table of Docker image information.

    This function takes a dictionary of Docker image information and creates
    a GitHub-flavored Markdown table representing the data.

    Args:
        docker_images_info (dict): A dictionary containing Docker image information.
            Each key is a Docker image name, and the value is a dictionary with
            'target_tag', 'next_batch_number', 'total_batches', and 'content_items' keys.

    Returns:
        str: A string containing the GitHub-flavored markdown table of Docker image information.

    Example:
        docker_images_info = {
            'image1': {'target_tag': 'v1.0', 'next_batch_number': 2, 'total_batches': 3, 'content_items': ['item1', 'item2']},
            'image2': {'target_tag': 'v2.0', 'next_batch_number': 1, 'total_batches': 2, 'content_items': ['item3']}
        }
        table = create_docker_image_table(docker_images_info)
    """
    table_data: list = []
    for i, (docker_image, info) in enumerate(docker_images_info.items(), 1):
        table_data.append(
            [i, docker_image, info["target_tag"], info["next_batch_number"], info["total_batches"], len(info["content_items"])]
        )

    headers = ["#", "Docker Image", "Target Tag", "Current Batch", "Total Batches", "Updated Items"]
    table = tabulate(table_data, headers=headers, tablefmt="github")

    return table


def create_pr_body(gitlab_pipeline_url: str, affected_content_items: dict[str, Any]) -> str:
    """
    Generate the body content for a pull request.

    This function creates a formatted pull request body that includes details about
    updated Docker images and affected content items. It provides a summary of changes
    with collapsible sections for each Docker image.

    Args:
        gitlab_pipeline_url (str): The URL of the GitLab pipeline associated with the changes.
        affected_content_items (dict[str, Any]): A dictionary containing information about
            affected content items for each Docker image.

    Returns:
        str: A formatted string representing the pull request body.

    The generated PR body includes:
    - A header indicating the purpose of the PR
    - A link to the associated GitLab pipeline
    - Collapsible sections for each Docker image, listing the files changed
    """
    body = f"## Auto updated docker images for the following content items\n " f"[GitLab pipline]({gitlab_pipeline_url})\n"

    for docker_image, content_item_info in affected_content_items.items():
        content_items = content_item_info["content_items"]
        if not content_items:
            continue

        changed_files = "\n- ".join(content_items)
        body += f"""<details>
<summary>{docker_image}</summary>

### Files Changed
- {changed_files}

</details>
"""
    return body


def create_remote_pr(
    gitlab_pipeline_url: str,
    output_table_path: str,
    affected_content_items: dict[str, dict[str, Any]],
    head_branch: str,
    remote_content_repo: Repository.Repository,
    pr_reviewer: str,
    pr_assignee: str,
) -> str:
    """Create the PR with the changes in the docker tag on the remote repo.

    Args:
        gitlab_pipeline_url (str): A link to the Gitlab pipeline.
        output_table_path (str): The path of the output table file.
        affected_content_items (dict[str, dict[str, Any]]): A dict of docker-image and affected content items.
        head_branch (str): The head branch, that has the committed changes.
        remote_content_repo (Repository.Repository): Remote repository.
        pr_reviewer (str): PR reviewer.
        pr_assignee (str): PR assignee.

    Returns:
        The PR URL link.
    """
    pipeline_id = gitlab_pipeline_url.split("/")[-1]
    title = f"Auto Updated Docker PR from {datetime.now().strftime('%Y-%m-%d')} GitLab Pipeline ID {pipeline_id}"
    body = create_pr_body(gitlab_pipeline_url, affected_content_items)
    pr = remote_content_repo.create_pull(
        title=title,
        body=body,
        base=BASE_BRANCH,
        head=head_branch,
    )

    if pr_reviewer:
        pr.create_review_request(reviewers=[pr_reviewer])
        logging.info(f"Requested review from {pr_reviewer}")

    if pr_assignee:
        pr.add_to_assignees(pr_assignee)
        logging.info(f"Assigned to {pr_assignee}")

    pr_labels = ["auto-update-docker", "docs-approved"]
    pr.set_labels(*pr_labels)
    logging.info(f'Set labels to {",".join(sorted(pr_labels))}')

    sum_batches_done = sum(item["next_batch_number"] for item in affected_content_items.values())
    sum_batches_in_progress = (
        sum(item["total_batches"] for item in affected_content_items.values() if item["next_batch_number"] > 0) - sum_batches_done
    )
    comment = "# Batches distribution\n"
    comment += """```mermaid
%%{init: {"pie": {"textPosition": 0.75}}%%
"""
    comment += f"""pie showData
    "Done" : {sum_batches_done}
    "In progress" : {sum_batches_in_progress}
```
\n
---
# Batches summary
\n
"""
    with open(output_table_path) as f:
        comment += f.read()
    pr.create_issue_comment(comment)
    logging.info("Added comment to the PR")

    return pr.html_url


def update_content_items_docker_images(
    docker_image: str,
    target_tag: str,
    content_items: list[str],
) -> list:
    """Updates the content items' docker tags.

    Args:
        docker_image (str): The docker image.
        target_tag (str): Target tag of docker image.
        content_items (list[str]): Content items to update their docker images.

    Returns:
        list[str]: The updated content items.
    """
    updated_content_items: list[str] = []
    new_docker_image = f"{docker_image}:{target_tag}"
    for content_item in content_items:
        with open(content_item) as file:
            content = file.read()

        # Update `docker-image` value, allowing for an optional space after the colon in the original
        new_content = re.sub(
            r"(dockerimage:\s*)([^\s]+)",  # Matches `docker-image:` with or without space after the colon
            rf"\1{new_docker_image}",  # Replaces it with the new Docker image (with a space)
            content,
        )
        logging.info(f"Updating docker image of {content_item} to {new_docker_image}")

        # Write the modified content back to the file
        with open(content_item, "w") as file:
            file.write(new_content)
        updated_content_items.append(content_item)

    return updated_content_items


def update_docker_state(state: dict[str, Any], affected_content_items: dict[str, Any], pr_number: str | None) -> dict[str, Any]:
    """
    Update the Docker state with new batch number and PR information.

    This function iterates through the affected content items and updates the state dictionary for each Docker image.
    It sets the new batch number and if there are content items updates the last PR number.

    Args:
        state (dict[str, Any]): The current state of Docker images.
        affected_content_items (dict[str, Any]): A dictionary of affected content items,
        pr_number (str | None): The number of the current pull request.

    Returns:
        dict[str, Any]: The updated state dictionary.

    Example:
        >>> state = {'image1': {'batch_number': 1, 'last_pr_number': '100'}}
        >>> affected_items = {'image1': {'content_items': ['item1'], 'next_batch_number': 2}}
        >>> update_docker_state(state, affected_items, '101')
        {'image1': {'batch_number': 2, 'last_pr_number': '101'}}
    """
    for docker_image, content_item_info in affected_content_items.items():
        state[docker_image]["batch_number"] = content_item_info["next_batch_number"]
        if content_item_info["content_items"] and int(content_item_info["next_batch_number"]) > 0:
            state[docker_image]["last_pr_number"] = pr_number
        else:
            state[docker_image]["last_pr_number"] = None

    # Remove docker images with batch number 0 from the state file
    return dict(filter(lambda item: int(item[1]["batch_number"]) > 0, state.items()))


@app.command()
def open_prs_for_content_items(
    affected_content_items_path: str = typer.Option(
        default="affected_content_items.json",
        help="The affected content items file path",
    ),
    state_path: str = typer.Option(
        default="state.csv",
        help="Teh docker state file path",
    ),
    docker_table_path: str = typer.Option(
        default="docker_table.txt",
        help="The path of the output table file",
    ),
    slack_attachment_path: str = typer.Option(
        default="slack_attachments.json",
        help="The path of the slack attachment file",
    ),
    slack_msg_path: str = typer.Option(
        default="msg.txt",
        help="The path of the slack message file",
    ),
    github_token: str = typer.Option(
        help="The GitHub token to use for the GitHub API calls",
        envvar="GITHUB_TOKEN",
    ),
    gitlab_pipeline_url: str = typer.Option(
        help="The URL of the GitLab pipeline that triggers this script",
        envvar="CI_PIPELINE_URL",
    ),
):
    try:
        install_logging("Auto_Update_Docker.log")

        # Setup git
        repo = Repo(".")
        git = repo.git
        origin = repo.remotes.origin
        logging.info(f"origin: {origin}")

        # Create the local branch
        pipeline_id = gitlab_pipeline_url.split("/")[-1]
        new_branch_name = f"AUD-demisto/{datetime.now().strftime('%Y-%m-%d')}/gitlab-pipeline-{pipeline_id}"
        create_local_branch(git, new_branch_name)

        # Update the content items
        affected_content_items = load_json_file(affected_content_items_path)
        for docker_image, image_config in affected_content_items.items():
            if content_items := image_config["content_items"]:
                update_content_items = update_content_items_docker_images(
                    docker_image=docker_image,
                    target_tag=image_config["target_tag"],
                    content_items=content_items,
                )
                affected_content_items[docker_image]["content_items"] = update_content_items

        # Git commit
        git.add("Packs")
        if git.status("--porcelain"):
            git.commit(
                "-m",
                "Updated Docker Images.",
            )

            # Update release notes
            logging.info("starting to update release notes...")
            command = "demisto-sdk update-release-notes -g"
            subprocess.run(command, shell=True, check=True, capture_output=True)

            # Git commit
            git.add("Packs")
            if git.status("--porcelain"):
                git.commit(
                    "-m",
                    "Updated Release Notes.",
                )
            else:
                logging.info("No changes to commit in Packs directory.")

            # Push the local changes to the remote branch.
            origin.push(f"+refs/heads/{new_branch_name}:refs/heads/{new_branch_name}")
            logging.info(f"Pushed branch {new_branch_name} to remote repository")

            # Create and save the output table file
            table_text = create_docker_image_table(affected_content_items)
            with open(docker_table_path, "w") as f:
                f.write(table_text)

            # Setup GitHub client
            github_client = Github(github_token, verify=False)
            remote_content_repo = github_client.get_repo(f"{ORG_NAME}/{REPO_NAME}")

            # Create the remote PR.
            content_roles = load_json_file(".github/content_roles.json")
            pr_reviewer = pr_assignee = content_roles["AUTO_UPDATE_DOCKER_REVIEWER"]
            pr_link = create_remote_pr(
                gitlab_pipeline_url=gitlab_pipeline_url,
                output_table_path=docker_table_path,
                affected_content_items=affected_content_items,
                head_branch=new_branch_name,
                remote_content_repo=remote_content_repo,
                pr_reviewer=pr_reviewer,
                pr_assignee=pr_assignee,
            )

            pr_number = pr_link.split("/")[-1]
            slack_msg_file_content = [
                {
                    "title": "",
                    "color": "good",
                    "text": f"Some content items were updated in PR #{slack_link(pr_link, pr_number)}.",
                }
            ]
            logging.info(f"PR {pr_link} was created.")

            sum_finished_batches = sum(item["next_batch_number"] for item in affected_content_items.values())
            sum_all_batches = sum(
                item["total_batches"] for item in affected_content_items.values() if item["next_batch_number"] > 0
            )
            finished_batches_in_percent = (sum_finished_batches / sum_all_batches) * 100 if sum_all_batches > 0 else 100
            docker_table_file_content = [
                {
                    "file": docker_table_path,
                    "filename": os.path.basename(docker_table_path),
                    "title": "Docker batches state",
                    "initial_comment": f"{finished_batches_in_percent:.2f} % of all batches have been completed.",
                }
            ]
        else:
            slack_msg_file_content = [
                {
                    "title": "",
                    "color": "good",
                    "text": "There are no Docker images to update. No new PR have been opened.",
                }
            ]
            docker_table_file_content = []
            pr_number = None
            logging.info("No Docker images to update. No new PR have been opened.")

        # Save the Slack msg file
        save_json_file(slack_msg_path, slack_msg_file_content)

        # Save the Slack attachments file content
        save_json_file(slack_attachment_path, docker_table_file_content)

        # Update the batch number and the PR number in the docker state file
        docker_state = load_csv_file(state_path, "docker_image")
        updated_docker_state = update_docker_state(docker_state, affected_content_items, pr_number)
        updated_state_path = os.path.join(os.path.dirname(state_path), "updated_state.csv")
        save_csv_file(updated_state_path, updated_docker_state, "docker_image", STATE_FILE_FIELD_NAMES)

    except Exception as e:
        logging.error(f"Got error when opening PRs {e}")
        logging.error(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    app()
