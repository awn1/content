import logging
import os
import sys
import traceback
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import typer
from demisto_sdk.commands.common.handlers import DEFAULT_JSON_HANDLER as json
from demisto_sdk.commands.content_graph.interface.neo4j.neo4j_graph import (
    Neo4jContentGraphInterface as ContentGraphInterface,
)
from github import Github
from neo4j import Record, Transaction
from packaging.version import Version

from Tests.scripts.auto_update_docker.utils import load_csv_file, load_json_file, save_json_file
from Tests.scripts.utils.log_util import install_logging

logging.basicConfig(level=logging.INFO)
app = typer.Typer(no_args_is_help=True)
CWD = os.getcwd()
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
ORG_NAME = "demisto"
REPO_NAME = "content"
PRS_PREFIX = "https://github.com/demisto/content/pull"


def get_pr_status(pr_number: int) -> dict[str, Any]:
    """
    Retrieve the current status of a pull request.

    This function uses the GitHub API to fetch the status of a specified pull request,
    including whether it's open, closed, or merged, and how long ago it was last updated.

    Args:
        pr_number (int): The number of the pull request to check.

    Returns:
        dict[str, Any]: A dictionary containing:
            - 'status': The current state of the PR ('open', 'closed', or 'merged').
            - 'hours_passed': The number of hours since the PR was last updated.

    Raises:
        Any exceptions raised by the GitHub API will be propagated.

    Note:
        This function requires a valid GITHUB_TOKEN environment variable to be set.
    """
    github_client = Github(GITHUB_TOKEN)
    remote_content_repo = github_client.get_repo(f"{ORG_NAME}/{REPO_NAME}")
    pr = remote_content_repo.get_pull(pr_number)

    if pr.state == "closed":
        if pr.merged:
            state = "merged"
            state_time = pr.merged_at
        else:
            state = "closed"
            state_time = pr.closed_at
    else:
        state = "open"
        state_time = pr.created_at

    state_time_utc = state_time.replace(tzinfo=timezone.utc)
    current_time_utc = datetime.now(timezone.utc)
    time_passed = current_time_utc - state_time_utc
    time_passed_in_hours = int(time_passed.total_seconds() / 3600)

    logging.info(f"PR {pr_number} is on status {state} was updated {time_passed_in_hours} hours ago.")
    return {"status": state, "hours_passed": time_passed_in_hours}


def get_content_item_to_add(
    only_nightly: bool,
    nightly_packs: list[str],
    content_item_pack_path: str,
    content_item_path: Path,
    target_tag: str,
    content_item_docker_image_tag: str,
    support_levels: list[str],
    content_item_support: str,
    min_cov: int,
    content_item_cov: float,
) -> str | None:
    """Returns the content item if it complies with the batch configuration.

    Args:
        only_nightly (bool): If to run on nightly packs.
        nightly_packs (list[str]): List of nightly packs.
        content_item_pack_path (str): The content item's pack's path.
        content_item_path (Path): The content item's path
        target_tag (str): The docker image tag we want to update to.
        content_item_docker_image_tag (str): The docker image tag of the content item.
        support_levels (list[str]): The support levels of the batch.
            If empty, this means all support levels should be considered.
        content_item_support (str): The support level of the content item.
        min_cov (int): Minimum coverage included in this batch.
        content_item_cov (float): The coverage of the content item.

    Returns:
        str | None: The path of the content item if it complies with the batch configuration, otherwise None.
    """
    if only_nightly and content_item_pack_path not in nightly_packs:
        logging.info(f"Pack path {content_item_pack_path} for {content_item_path} is not in nightly, skipping.")
        return None

    if Version(content_item_docker_image_tag) >= Version(target_tag):
        # If content item's docker tag is larger than or equal to the target docker tag, then we
        # don't need to update the content item, skipping
        logging.info(f"{content_item_path} tag {content_item_docker_image_tag} >= {target_tag = }, skipping.")
        return None

    if support_levels and content_item_support not in support_levels:
        # If support levels is not empty, and the content item's support level is not in the allowed support levels,
        # then we skip it.
        logging.info(f"{content_item_path} - {content_item_support=} Is not in {support_levels=}, skipping")
        return None

    if min_cov <= content_item_cov:
        # We check the coverage of the content item
        # Since the content item that we get will be a python file, and we want to
        # return a YML
        logging.info(f"{content_item_path = } {content_item_cov = }")
        return str(content_item_path.with_suffix(".yml"))

    logging.info(f"{content_item_path} with coverage {content_item_cov} is not within the required {min_cov} coverage, skipping")
    return None


def filter_content_items_to_run_on(
    batch_config: dict[str, Any],
    content_items_coverage: dict[str, float],
    content_items_by_docker_image: list[dict[str, Any]],
    target_tag: str,
    nightly_packs: list[str],
) -> list[str]:
    """Collect the content items with respect to the batch config.

    Args:
        batch_config (dict[str, Any]): The batch config.
        content_items_coverage (dict[str, float]): Coverage of content items.
        content_items_by_docker_image (list[dict[str, Any]]): A list of content items per docker image to check if they
            fit into the current batch.
        target_tag (str): The target docker tag.
        nightly_packs (list[str]): The nightly packs.

    Returns:
        list[str]: The list of content items that should be updated in the current batch.
    """
    affected_content_items: list[str] = []
    only_nightly: bool = batch_config.get("only_nightly", False)
    min_cov: int = int(batch_config.get("min_coverage", 0))
    support_levels: list[str] = batch_config.get("support", [])
    logging.info(
        f"Running on content items with the following conditions: {min_cov = } - {support_levels = } - {only_nightly = }"
    )

    for content_item in content_items_by_docker_image:
        content_item_path = Path(content_item["content_item"])
        content_item_pack_path = content_item["pack_path"]
        content_item_support = content_item["support_level"]
        content_item_docker_image_tag = content_item["docker_image_tag"]

        content_item_to_add = get_content_item_to_add(
            only_nightly=only_nightly,
            nightly_packs=nightly_packs,
            content_item_pack_path=content_item_pack_path,
            content_item_path=content_item_path,
            target_tag=target_tag,
            content_item_docker_image_tag=content_item_docker_image_tag,
            support_levels=support_levels,
            content_item_support=content_item_support,
            min_cov=min_cov,
            # If a content item is not in the coverage report, then we consider it's coverage to be 0
            content_item_cov=content_items_coverage.get(str(content_item_path), 0.0),
        )
        if content_item_to_add:
            affected_content_items.append(content_item_to_add)

    return affected_content_items


def increase_batch_number(current_batch: int, total_batches: int) -> int:
    """
    Increment the batch number or reset it to 0 if the maximum is reached.

    This function is used to manage batch progression in a circular manner.
    When the current batch number reaches the total number of batches,
    it resets to 0, otherwise it increments by 1.

    Args:
        current_batch (int): The current batch number.
        total_batches (int): The total number of batches available.

    Returns:
        int: The next batch number (incremented or reset to 0).

    Example:
        >>> increase_batch_number(2, 3)
        3
        >>> increase_batch_number(3, 3)
        0
    """
    if current_batch == total_batches:
        logging.info(f"{current_batch = } is equal to {total_batches = } setting batch number to 0")
        return 0
    else:
        logging.info(f"{current_batch = } is less than {total_batches = } setting batch number to {current_batch + 1}")
        return current_batch + 1


def get_affected_content_items_by_docker_image(
    content_items_coverage: dict[str, float],
    docker_state: dict[str, Any],
    prs_state: dict[str, Any],
    content_items_by_docker_image: dict[str, list[dict[str, Any]]],
    nightly_packs: list[str],
) -> dict[str, dict[str, Any]]:
    """Returns the affected content items with respect to the configurations of the current batch.
        and returns the updated docker state.

    Args:
        content_items_coverage (dict[str, float]): Coverage of content items.
        docker_state (dict[str, Any]): The current docker state.
        prs_state (dict[str, Any]): The current PR state.
        content_items_by_docker_image (dict[str, list[dict[str, Any]]]): A dictionary that holds docker images as keys,
            and the value will be a list containing data about the content items and respective pack.
        nightly_packs (list[str]): The nightly packs.

    Returns:
        tuple[dict[str, dict[str, Any]], list[str]]: A dictionary where the keys are docker images,
        and their values are data containing the affected content items, pr tags, and target tag of each docker image.
        And a list of PRs they are still opened.
    """
    affected_content_items_by_docker_image: dict[str, Any] = {}
    for docker_image, docker_info in docker_state.items():
        target_tag: str = docker_info["docker_tag"]
        current_batch_number: int = int(docker_info["batch_number"])
        batches_config: dict[str, Any] = json.loads(docker_info["batches_config"])
        all_batches: list[dict[str, Any]] = batches_config["batches"]
        current_batch: dict[str, Any] = all_batches[current_batch_number - 1]
        cadence: dict[str, Any] = batches_config["cadence"]
        logging.info(
            f"{docker_image = } - {target_tag = } - with {current_batch = } "
            f"{current_batch_number = } out of {len(all_batches)} batches - {cadence = }"
        )

        affected_content_items = {
            "next_batch_number": current_batch_number,
            "total_batches": len(all_batches),
            "target_tag": target_tag,
            "content_items": [],
        }

        # Check if batch number is 0 continuing
        if current_batch_number == 0:
            logging.info(f"Skipping {docker_image} as {current_batch_number = }.")
            continue

        if last_pr_number := docker_info.get("last_pr_number"):
            status, hours_passed = prs_state[last_pr_number].values()
            if status == "open":
                logging.info(f"Skipping updating {docker_image = } as {last_pr_number = } is still open.")
                continue
            elif status == "closed":
                logging.info(f"Setting {docker_image = } batch state to 0 as the {last_pr_number = } closed.")
                affected_content_items["next_batch_number"] = 0
            elif status == "merged":
                if cadence.get("from") == "merged":
                    cadence_hours = int(cadence.get("hours", 0))
                    if hours_passed < cadence_hours:
                        logging.info(f"Skipping {docker_image} as {hours_passed = } < {cadence_hours = }.")
                        continue
                    else:
                        affected_content_items["next_batch_number"] = increase_batch_number(
                            current_batch_number, len(all_batches)
                        )
                        logging.info(
                            f"Updating {docker_image} as {hours_passed = } >= {cadence_hours = } "
                            f"with updated batch number {affected_content_items['next_batch_number'] }."
                        )

        if affected_content_items["next_batch_number"] == 0:
            logging.info(f"Skipping updating {docker_image = } as batch number == 0")
            affected_content_items["last_pr_number"] = None
            affected_content_items_by_docker_image[docker_image] = affected_content_items
            continue

        # Get affected content items for the current docker image
        affected_content_items["content_items"] = filter_content_items_to_run_on(
            batch_config=current_batch,
            content_items_coverage=content_items_coverage,
            content_items_by_docker_image=content_items_by_docker_image[docker_image],
            target_tag=target_tag,
            nightly_packs=nightly_packs,
        )
        if not affected_content_items.get("content_items"):
            next_batch_number = increase_batch_number(current_batch_number, len(all_batches))
            affected_content_items["next_batch_number"] = next_batch_number
            affected_content_items["last_pr_number"] = None
            logging.info(
                f"{docker_image = } does not have any content items to update, "
                f"increasing the batch number to {next_batch_number = }."
            )

        affected_content_items_by_docker_image[docker_image] = affected_content_items

    return affected_content_items_by_docker_image


def query_used_dockers_per_content_item(
    tx: Transaction,
) -> list[Record]:
    """
    Queries the content graph for the following data:
        1. Docker image.
        2. Path of the content items.
        3. Item type (python, pwsh).
        4. Pack path.
        5. Pack support
    With the following conditions:
        1. The pack is not an API module pack.
        2. The pack is not hidden.
        3. The item is not deprecated.
        4. The item is not a JavaScript integration.
        5. The item has a docker_image field and auto_update_docker_image is set to True.
    """
    return list(
        tx.run(
            """
            MATCH (pack:Pack) <-[:IN_PACK] - (item)
            WHERE item.content_type IN ["Integration", "Script"]
                AND NOT pack.object_id = 'ApiModules'
                AND NOT pack.hidden
                AND NOT item.deprecated
                AND NOT item.type = 'javascript'
                AND item.auto_update_docker_image
                AND item.docker_image IS NOT NULL
            Return item.docker_image, item.path, item.type, pack.path, pack.support
            """
        )
    )


def return_content_item_with_suffix(content_item_yml: str, content_item_type: str) -> Path:
    """
    Returns the content item path with the appropriate file suffix based on its type.

    Args:
        content_item_yml (str): The path to the YAML file of the content item.
        content_item_type (str): The type of the content item ('python' or 'powershell').

    Returns:
        Path: The path to the content item with the correct file extension (.py or .ps1).

    Raises:
        Exception: If an unknown content_item_type is provided.
    """
    if content_item_type == "python":
        return Path(content_item_yml).with_suffix(".py")
    elif content_item_type == "powershell":
        return Path(content_item_yml).with_suffix(".ps1")
    else:
        raise Exception(f"Unknown {content_item_type=}")


def get_content_items_by_docker_image() -> dict[str, list[dict[str, Any]]]:
    """Return all content items of type 'integration' and 'script', with their respective
    docker images, support level, and pack path.

    Returns:
        dict[str, list[dict[str, Any]]]: The key will be the docker image, and the value will be a list
        containing data about the content items and respective pack and support level.
    """
    content_images: dict[str, list[dict[str, Any]]] = defaultdict(list)
    with ContentGraphInterface() as graph, graph.driver.session() as session:
        content_items_info = session.execute_read(query_used_dockers_per_content_item)
        # content_item_type holds the type of the script that runs the integration or script, either ps1 or python
        for (
            docker_image,
            content_item_yml,
            content_item_type,
            full_pack_path,
            support_level,
        ) in content_items_info:
            content_item = return_content_item_with_suffix(content_item_yml, content_item_type)
            pack_path = full_pack_path.split("/")[1]
            # Since the docker image returned will include the tag, we only need the image
            docker_image_split = docker_image.split(":")
            docker_image_without_tag = docker_image_split[0]
            docker_image_tag = docker_image_split[1]
            content_images[docker_image_without_tag].append(
                {
                    "content_item": content_item,
                    "support_level": support_level,
                    "pack_path": pack_path,
                    "docker_image_tag": docker_image_tag,
                }
            )
    return content_images


def generate_slack_thread_msg(prs_state: dict[str, Any]) -> list[Any]:
    """
    Generate a Slack thread message for open pull requests.

    This function creates a formatted message for Slack, listing all open pull requests that are awaiting review.
    It uses the GitHub pull request URLs and formats them as clickable links in the Slack message.

    Args:
        prs_state (dict[str, Any]): A dictionary containing the state of pull requests.
            Each key is a PR number, and the value is a dictionary containing at least
            a 'status' key.

    Returns:
        list[Any]: A list containing a single dictionary with Slack message formatting
        if there are open PRs, or an empty list if no open PRs are found.

    The returned Slack message includes:
    - A title (empty in this case)
    - A fallback text for notifications
    - A color indicator (set to "warning")
    - A pretext introducing the list
    - The main text content with enumerated PR links

    If no open PRs are found, the function logs this information and returns an empty list.
    """
    if open_prs_number := list(filter(lambda x: prs_state[x]["status"] == "open", prs_state)):
        pr_link_prefix = "https://github.com/demisto/content/pull"
        pr_links = [f"{i}. <{pr_link_prefix}/{pr_number} | PR #{pr_number}" for i, pr_number in enumerate(open_prs_number)]
        file_data = [
            {
                "title": "",
                "fallback": "List of PRs awaiting review.",
                "color": "warning",
                "pretext": "List of PRs awaiting review:",
                "text": "\n".join(pr_links),
            }
        ]
        logging.info(f"There are {len(open_prs_number)} open PRs awaiting review.")
        return file_data

    logging.info("No open PRs found. Skipping generating slack thread msg.")
    return []


@app.command()
def get_affected_content_items(
    state_path: str = typer.Option(
        help="The path to the state file that holds all the docker images state info (batch-number, last-tag, etc.)",
    ),
    coverage_report_path: str = typer.Option(
        help="The coverage report from last nightly",
    ),
    affected_content_items_path: str = typer.Option(
        help="The path to the affected content items file",
    ),
    slack_thread_msg_path: str = typer.Option(
        help="The path to the slack message file",
    ),
):
    try:
        install_logging("Auto_Update_Docker.log")

        # Get nightly packs from tests conf
        tests_conf = load_json_file("Tests/conf.json")
        nightly_packs: list[str] = tests_conf.get("nightly_packs", [])

        # Get the content items coverage from the coverage report
        coverage_report_dict: dict[str, Any] = load_json_file(coverage_report_path)
        content_items_coverage: dict[str, float] = coverage_report_dict["files"]

        # Get the current docker state from the state file
        docker_state: dict = load_csv_file(state_path, "docker_image")

        pr_numbers = set(info["last_pr_number"] for info in docker_state.values() if info["last_pr_number"])
        prs_state: dict[str, Any] = {pr_number: get_pr_status(int(pr_number)) for pr_number in pr_numbers}

        # Get the content items grouped by docker image using the graph
        content_items_by_docker_image: dict[str, list[dict[str, Any]]] = get_content_items_by_docker_image()

        # Calculable the affected content items
        affected_content_items_by_docker_image = get_affected_content_items_by_docker_image(
            content_items_coverage=content_items_coverage,
            docker_state=docker_state,
            prs_state=prs_state,
            content_items_by_docker_image=content_items_by_docker_image,
            nightly_packs=nightly_packs,
        )
        save_json_file(affected_content_items_path, affected_content_items_by_docker_image)

        # Generate the Slack thread message
        slack_thread_file_content = generate_slack_thread_msg(prs_state)
        save_json_file(slack_thread_msg_path, slack_thread_file_content)

    except Exception as e:
        logging.error(f"Got error when extracting affected content {e}")
        logging.error(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    app()
