import json
import logging
import os
import sys
import traceback
from typing import Any

import typer
from demisto_sdk.commands.common.docker.docker_image import DockerImage
from demisto_sdk.commands.content_graph.interface.neo4j.neo4j_graph import (
    Neo4jContentGraphInterface as ContentGraphInterface,
)
from neo4j import Record, Transaction

from Tests.scripts.auto_update_docker.utils import (
    STATE_FILE_FIELD_NAMES,
    load_csv_file,
    load_json_file,
    save_csv_file,
    save_json_file,
)
from Tests.scripts.utils.log_util import install_logging

app = typer.Typer(no_args_is_help=True)


def query_the_graph_to_get_all_docker_images(
    tx: Transaction,
) -> list[Record]:
    """
    Queries the content graph to get the docker images with the following conceitedness:
    1. The pack is not an API module pack.
    2. The pack is not hidden.
    3. The item is not deprecated.
    4. The item is not a JavaScript integration.
    5. The item alt_docker_images is not set to True.
    6. The item has a docker_image field and auto_update_docker_image is set to True.
    """
    return list(
        tx.run(
            """
            MATCH (pack:Pack) <-[:IN_PACK]- (item)
            WHERE item.content_type IN ["Integration", "Script"]
              AND NOT pack.object_id = 'ApiModules'
              AND NOT pack.hidden
              AND NOT item.deprecated
              AND NOT item.type = 'javascript'
              AND NOT item.alt_docker_images
              AND item.docker_image IS NOT NULL
              AND item.auto_update_docker_image
            RETURN DISTINCT item.docker_image
            """
        )
    )


def get_all_docker_images() -> set[str]:
    """
    Retrieves all unique Docker images from the content graph.

    This function connects to the content graph, executes a read query to fetch
    all Docker images, and returns a set of unique image names without tags.

    Returns:
        set[str]: A set of unique Docker image names without tags.
    """
    with ContentGraphInterface() as graph, graph.driver.session() as session:
        docker_images = session.execute_read(query_the_graph_to_get_all_docker_images)
    return set(docker_image[0].split(":")[0] for docker_image in docker_images)


def process_docker_images_input(docker_images_input: str) -> tuple[set, set]:
    """
    Process the input string of Docker images and return sets of images to update and exclude.

    This function handles three scenarios:
    1. If Asterisk sign (*) is provided, it returns all Docker images from the content graph.
    2. If images are provided without a prefix, they are added to the update set.
    3. If images are provided with a minus sign prefix, they are added to the exclusion set.

    Args:
        docker_images_input (str): Asterisk sign (*) or A comma-separated string of Docker image names,
                                          optionally prefixed with '-' for exclusion.

    Returns:
        tuple[set, set]: A tuple containing two sets:
            - The first set contains Docker images to update.
            - The second set contains Docker images to exclude.
    """
    images_to_update: set[str] = set()
    images_to_exclude: set[str] = set()

    if docker_images_input == "*":
        logging.info("No Docker images provided. Return all Docker images.")
        return get_all_docker_images(), images_to_exclude

    for image in docker_images_input.split(","):
        image = image.strip()
        if image.startswith("-"):
            images_to_exclude.add(image[1:].strip())
        else:
            images_to_update.add(image)

    if not images_to_update and images_to_exclude:
        images_to_update = get_all_docker_images() - images_to_exclude

    return images_to_update, images_to_exclude


def update_state(state: dict[str, Any], config: dict[str, Any], docker_images: set[str], action: str) -> dict[str, Any]:
    """
    Update the state dictionary for Docker images based on the specified action.

    This function modifies the state dictionary by either adding new entries for Docker images
    or removing existing entries, depending on the action parameter.

    For the 'start' action:
    - Adds new entries for each Docker image in the set.
    - Configures each entry with docker tag, last PR number, batch number, and batch configuration.
    - Uses default or custom configurations from the BATCHES_CONFIG_FILE.

    For the 'stop' action:
    - Removes entries for the specified Docker images from the state dictionary.

    Args:
        state (dict[str, Any]): The current state dictionary to be updated.
        config (dict[str, Any]): The configuration dictionary.
        docker_images (set[str]): A set of Docker image names to process.
        action (str): The action to perform, either "start" or "stop".

    Returns:
        dict[str, Any]: The updated state dictionary.
    """
    if action.lower() == "start":
        images_config: dict = config.get("image_configs", {})
        logging.info(f"config is {images_config}")
        for image in docker_images:
            image_name, tag = image.split(":") if ":" in image else (image, DockerImage(image).latest_tag.base_version)
            batches_config = images_config.get("custom_configs", {}).get(image_name, images_config.get("default_configs", {}))
            logging.info(f"Updating image {image} with tag {tag} and batch config {batches_config}")

            if not image_name:
                logging.error(f"Invalid Docker image format: {image}")
                continue

            state[image_name] = {
                "docker_tag": tag,
                "last_pr_number": "",
                "batch_number": 1,
                "batches_config": json.dumps(batches_config, default=str, indent=4, sort_keys=True),
            }

    elif action.lower() == "stop":
        for image in docker_images:
            image_name = image.split(":")[0]
            logging.info(f"Removing image {image_name} from state file")
            state.pop(image_name, None)

    return state


def generate_slack_thread_msg(state_path: str) -> list[Any]:
    """
    Generate a message for a Slack thread about the updated Docker state file.

    This function creates a structured message suitable for posting in a Slack thread.
    The message includes details about the updated Docker state file, such as its path
    and filename.

    Args:
        state_path (str): The full path to the updated Docker state file.

    Returns:
        list[Any]: A list containing a single dictionary with the following keys:
            - file: The full path to the state file.
            - filename: The base name of the state file.
            - title: A title describing the update action.
            - initial_comment: An initial comment for the Slack thread.

    Example:
        >>> generate_slack_thread_msg("/path/to/docker_state.csv")
        [
            {
                "file": "/path/to/docker_state.csv",
                "filename": "docker_state.csv",
                "title": "Updated docker state file.",
                "initial_comment": "Updated docker state file.",
            }
        ]
    """
    return [
        {
            "file": state_path,
            "filename": os.path.basename(state_path),
            "title": "Updated docker state file.",
            "initial_comment": "Updated docker state file.",
        }
    ]


@app.command()
def reset_docker_images_state_file(
    docker_images: str = typer.Option(
        help="A comma separated list of docker images to update or remove.",
        default="demisto/py3-tools",
    ),
    action: str = typer.Option(
        help="The action to perform. Can be 'Start' or 'Stop'.",
        default="start",
        show_default=True,
        callback=lambda value: value.lower(),
    ),
    state_path: str = typer.Option(
        help="The path to the state file that holds all the docker images state info (batch-number, last-tag, etc.)",
        default="state.csv",
    ),
    config_path: str = typer.Option(
        help="The path to the configration file in content-test-conf repo.",
    ),
    slack_attachment_path: str = typer.Option(
        default="slack_attachments.json",
        help="The path of the slack attachment file",
    ),
):
    try:
        install_logging("Update_Docker_State.log")

        logging.info(f"Action arg is set to: {action}")
        images_to_include, images_to_exclude = process_docker_images_input(docker_images)
        logging.info(f"{len(images_to_include)} images to include and {len(images_to_exclude)} images to exclude")

        state = load_csv_file(state_path, "docker_image")
        config = load_json_file(config_path)
        updated_state = update_state(state, config, images_to_include, action)
        save_csv_file(state_path, updated_state, "docker_image", STATE_FILE_FIELD_NAMES)

        slack_attach_msg = generate_slack_thread_msg(state_path)
        save_json_file(slack_attachment_path, slack_attach_msg)

        logging.info(f"State file '{state_path}' has been updated with the latest Docker image information.")

    except Exception as e:
        logging.error(f"An error occurred while updating the Docker image state: {e}")
        logging.error(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    app()
