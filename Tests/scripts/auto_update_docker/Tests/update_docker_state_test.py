import os
from unittest.mock import Mock, patch

from neo4j import Record, Transaction

from Tests.scripts.auto_update_docker.update_docker_state import (
    generate_slack_thread_msg,
    get_all_docker_images,
    process_docker_images_input,
    query_the_graph_to_get_all_docker_images,
    update_state,
)


@patch("Tests.scripts.auto_update_docker.update_docker_state.get_all_docker_images")
def test_process_docker_images_input(mock_get_all_docker_images):
    """
    Test the process_docker_images_input function.

    Given a mocked get_all_docker_images function returning a set of images
    When process_docker_images_input is called with various input strings
    Then it should correctly process the input and return the expected sets of images to update and exclude
    """
    mock_get_all_docker_images.return_value = {"image1", "image2", "image3"}

    # Test case 1: No input (None)
    images_to_update, images_to_exclude = process_docker_images_input("*")
    assert images_to_update == {"image1", "image2", "image3"}
    assert images_to_exclude == set()

    # Test case 2: Specific images to update
    images_to_update, images_to_exclude = process_docker_images_input("image1,image2")
    assert images_to_update == {"image1", "image2"}
    assert images_to_exclude == set()

    # Test case 3: Exclude specific images
    images_to_update, images_to_exclude = process_docker_images_input("-image1,-image2")
    assert images_to_update == {"image3"}
    assert images_to_exclude == {"image1", "image2"}

    # Test case 4: Mix of inclusion and exclusion
    images_to_update, images_to_exclude = process_docker_images_input("image1,-image2")
    assert images_to_update == {"image1"}
    assert images_to_exclude == {"image2"}

    # Test case 5: Image with specific tag
    images_to_update, images_to_exclude = process_docker_images_input("image1:tag")
    assert images_to_update == {"image1:tag"}
    assert images_to_exclude == set()

    # Test case 6: Multiple images with tags and exclusions
    images_to_update, images_to_exclude = process_docker_images_input("image1:tag1,image2,-image3")
    assert images_to_update == {"image1:tag1", "image2"}
    assert images_to_exclude == {"image3"}


@patch("Tests.scripts.auto_update_docker.update_docker_state.DockerImage")
@patch("Tests.scripts.auto_update_docker.update_docker_state.load_json_file")
def test_update_state_start(mock_load_json, mock_docker_image):
    """
    Test the update_state function with 'start' action.

    Given a mocked load_json_file and DockerImage
    When update_state is called with 'start' action and a set of docker images
    Then it should correctly update the state dictionary with new entries for each docker image
    """
    config = {"image_configs": {"custom_configs": {"image1": {"custom": "config"}}, "default_configs": {"default": "config"}}}
    mock_docker_image.return_value.latest_tag.base_version = "1.0.0"
    initial_state = {}
    docker_images = {"image1", "image2:2.0.0", "image3"}

    updated_state = update_state(initial_state, config, docker_images, "start")

    assert len(updated_state) == 3
    assert updated_state["image1"]["batch_number"] == 1
    assert updated_state["image1"]["batches_config"] == '{\n    "custom": "config"\n}'
    assert updated_state["image1"]["last_pr_number"] == ""
    assert updated_state["image1"]["docker_tag"] == "1.0.0"
    assert updated_state["image2"]["batches_config"] == '{\n    "default": "config"\n}'
    assert updated_state["image2"]["docker_tag"] == "2.0.0"
    assert updated_state["image3"]["docker_tag"] == "1.0.0"


def test_update_state_stop():
    """
    Test the update_state function with 'stop' action.

    Given an initial state dictionary with multiple docker image entries
    When update_state is called with 'stop' action and a set of docker images to remove
    Then it should correctly remove the specified docker images from the state dictionary
    """
    config = {"image_configs": {"custom_configs": {"image1": {"custom": "config"}}, "default_configs": {"default": "config"}}}
    initial_state = {
        "image1": {"batch_number": 1, "last_pr_number": "", "docker_tag": "1.0.0", "batches_config": {"default": "config"}},
        "image2": {"batch_number": 1, "last_pr_number": "", "docker_tag": "2.0.0", "batches_config": {"default": "config"}},
        "image3": {"batch_number": 2, "last_pr_number": "1234", "docker_tag": "3.0.0", "batches_config": {"default": "config"}},
    }
    docker_images = {"image1", "image2"}

    updated_state = update_state(initial_state, config, docker_images, "stop")

    assert len(updated_state) == 1
    assert "image1" not in updated_state
    assert "image2" not in updated_state
    assert "image3" in updated_state
    assert updated_state["image3"]["batch_number"] == 2
    assert updated_state["image3"]["last_pr_number"] == "1234"
    assert updated_state["image3"]["docker_tag"] == "3.0.0"
    assert updated_state["image3"]["batches_config"] == {"default": "config"}


def test_update_state_invalid_action():
    """
    Test the update_state function with an invalid action.

    Given an initial state dictionary and a set of docker images
    When update_state is called with an invalid action
    Then it should return the initial state unchanged
    """
    config = {"image_configs": {"custom_configs": {"image1": {"custom": "config"}}, "default_configs": {"default": "config"}}}
    initial_state = {}
    docker_images = {"image1"}

    updated_state = update_state(initial_state, config, docker_images, "invalid")

    assert updated_state == initial_state


@patch("Tests.scripts.auto_update_docker.update_docker_state.DockerImage")
@patch("Tests.scripts.auto_update_docker.update_docker_state.load_json_file")
def test_update_state_start_empty_input(mock_load_json, mock_docker_image):
    """
    Test the update_state function with 'start' action and empty input.

    Given a mocked load_json_file and DockerImage
    When update_state is called with 'start' action and an empty set of docker images
    Then it should return an empty state dictionary
    """
    config = {"image_configs": {"custom_configs": {"image1": {"custom": "config"}}, "default_configs": {"default": "config"}}}
    mock_load_json.return_value = {
        "image_configs": {"custom_configs": {"image1": {"custom": "config"}}, "default_configs": {"default": "config"}}
    }
    mock_docker_image.return_value.latest_tag.base_version = "1.0.0"
    initial_state = {}
    docker_images = set()

    updated_state = update_state(initial_state, config, docker_images, "start")

    assert updated_state == {}


def test_update_state_stop_empty_input():
    """
    Test the update_state function with 'stop' action and empty input.

    Given an initial state dictionary with a docker image entry
    When update_state is called with 'stop' action and an empty set of docker images
    Then it should return the initial state unchanged
    """
    config = {"image_configs": {"custom_configs": {"image1": {"custom": "config"}}, "default_configs": {"default": "config"}}}
    initial_state = {"image1": {"batch_number": 1, "last_pr_number": "", "docker_tag": "1.0.0"}}
    docker_images = set()

    updated_state = update_state(initial_state, config, docker_images, "stop")

    assert updated_state == initial_state


def test_query_the_graph_to_get_all_docker_images():
    """
    Test the query_the_graph_to_get_all_docker_images function.

    Given a mocked Transaction object with predefined results
    When query_the_graph_to_get_all_docker_images is called
    Then it should return the correct list of docker images from the graph query
    """
    mock_tx = Mock(spec=Transaction)
    mock_result = [
        Record({"item.docker_image": "image1:tag1"}),
        Record({"item.docker_image": "image2:tag2"}),
        Record({"item.docker_image": "image3:tag3"}),
    ]
    mock_tx.run.return_value = mock_result

    result = query_the_graph_to_get_all_docker_images(mock_tx)

    mock_tx.run.assert_called_once()
    assert len(result) == 3
    assert result[0]["item.docker_image"] == "image1:tag1"
    assert result[1]["item.docker_image"] == "image2:tag2"
    assert result[2]["item.docker_image"] == "image3:tag3"


@patch("Tests.scripts.auto_update_docker.update_docker_state.ContentGraphInterface")
def test_get_all_docker_images(mock_graph_interface):
    """
    Test the get_all_docker_images function.

    Given a mocked ContentGraphInterface with predefined results
    When get_all_docker_images is called
    Then it should return the correct set of unique docker image names without tags
    """
    mock_session = Mock()
    mock_graph_interface.return_value.__enter__.return_value.driver.session.return_value.__enter__.return_value = mock_session

    mock_session.execute_read.return_value = [
        Record({"item.docker_image": "image1:tag1"}),
        Record({"item.docker_image": "image2:tag2"}),
        Record({"item.docker_image": "image3:tag3"}),
    ]

    result = get_all_docker_images()

    mock_session.execute_read.assert_called_once_with(query_the_graph_to_get_all_docker_images)
    assert result == {"image1", "image2", "image3"}


def test_generate_slack_thread_msg():
    """
    Test the generate_slack_thread_msg function.

    Given a state file path
    When generate_slack_thread_msg is called with this path
    Then it should return a correctly formatted list with a single dictionary
    """
    test_path = "/path/to/test_state.csv"
    expected_result = [
        {
            "file": test_path,
            "filename": "test_state.csv",
            "title": "Updated docker state file.",
            "initial_comment": "Updated docker state file.",
        }
    ]

    result = generate_slack_thread_msg(test_path)

    assert result == expected_result
    assert len(result) == 1
    assert result[0]["file"] == test_path
    assert result[0]["filename"] == os.path.basename(test_path)
    assert result[0]["title"] == "Updated docker state file."
    assert result[0]["initial_comment"] == "Updated docker state file."
