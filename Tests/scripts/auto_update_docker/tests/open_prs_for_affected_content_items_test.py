from unittest.mock import MagicMock, patch

from Tests.scripts.auto_update_docker.open_prs_for_affected_content_items import (
    create_docker_image_table,
    create_local_branch,
    create_pr_body,
    create_remote_pr,
    update_content_items_docker_images,
    update_docker_state,
)


def test_create_local_branch():
    """
    Given:
    - A Git repository object
    - A new branch name "test-branch"

    When:
    - The create_local_branch function is called with these parameters

    Then:
    - The Git checkout method should be called once
    - The checkout should be performed with the arguments "-b", "test-branch", and "master"
    - This ensures a new branch is created from the master branch
    """
    mock_git = MagicMock()
    branch_name = "test-branch"
    create_local_branch(mock_git, branch_name)
    mock_git.checkout.assert_called_once_with("-b", branch_name, "master")


def test_create_docker_image_table():
    """
    Given:
    - A dictionary of docker images information containing:
        - Two images: "image1" and "image2"
        - Each image has target tag, batch numbers, and content items

    When:
    - The create_docker_image_table function is called with this information

    Then:
    - The result should be a string containing a GitHub-flavored markdown table
    - The table should have the correct headers
    - The table should contain correct data for both images, including:
        - Docker image names
        - Target tags
        - Current batch numbers
        - Total batches
        - Number of updated items
    """
    docker_images_info = {
        "image1": {"target_tag": "v1.0", "next_batch_number": 2, "total_batches": 3, "content_items": ["item1", "item2"]},
        "image2": {"target_tag": "v2.0", "next_batch_number": 1, "total_batches": 2, "content_items": ["item3"]},
    }
    result = create_docker_image_table(docker_images_info)
    assert (
        result
        == """|   # | Docker Image   | Target Tag   |   Current Batch |   Total Batches |   Updated Items |
|-----|----------------|--------------|-----------------|-----------------|-----------------|
|   1 | image1         | v1.0         |               2 |               3 |               2 |
|   2 | image2         | v2.0         |               1 |               2 |               1 |"""
    )


def test_create_pr_body():
    gitlab_pipeline_url = "https://gitlab.com/pipeline/123"
    affected_content_items = {"docker1": {"content_items": ["item1", "item2"]}, "docker2": {"content_items": ["item3"]}}
    result = create_pr_body(gitlab_pipeline_url, affected_content_items)
    assert "Auto updated docker images for the following content items" in result
    assert gitlab_pipeline_url in result
    assert "docker1" in result and "docker2" in result
    assert "item1" in result and "item2" in result and "item3" in result


@patch("Tests.scripts.auto_update_docker.open_prs_for_affected_content_items.Repository")
def test_create_remote_pr(mock_repo):
    """
    Given:
    - A mocked Repository object
    - A GitLab pipeline URL: "https://gitlab.com/pipeline/123"
    - An output table path: "test_table.txt"
    - Affected content items: {"docker1": {"content_items": ["item1"]}}
    - A head branch name: "test-branch"
    - A PR reviewer: "reviewer"
    - A PR assignee: "assignee"

    When:
    - The create_remote_pr function is called with these parameters

    Then:
    - The function should return the URL of the created PR: "https://github.com/test/pr/1"
    - The create_pull method of the mocked repo should be called once
    - The create_review_request method of the created PR should be called once
    - The add_to_assignees method of the created PR should be called once
    - The set_labels method of the created PR should be called once
    """
    import os
    import tempfile
    from unittest.mock import MagicMock

    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as temp_file:
        temp_file.write("Some content for the test table")

    mock_pr = MagicMock()
    mock_repo.create_pull.return_value = mock_pr
    mock_pr.html_url = "https://github.com/test/pr/1"
    result = create_remote_pr(
        gitlab_pipeline_url="https://gitlab.com/pipeline/123",
        output_table_path=temp_file.name,
        affected_content_items={"docker1": {"content_items": ["item1"], "next_batch_number": 1, "total_batches": 3}},
        head_branch="test-branch",
        remote_content_repo=mock_repo,
        pr_reviewer="reviewer",
        pr_assignee="assignee",
    )
    assert result == "https://github.com/test/pr/1"
    mock_repo.create_pull.assert_called_once()
    mock_pr.create_review_request.assert_called_once()
    mock_pr.add_to_assignees.assert_called_once()
    mock_pr.set_labels.assert_called_once()

    os.unlink(temp_file.name)


def test_update_content_items_docker_images():
    """
    Given:
    - A docker image name: "new_image"
    - A target tag: "new_tag"
    - A list of content items: ["item1.yml", "item2.yml"]
    - Mocked file contents with old docker image information

    When:
    - The update_content_items_docker_images function is called with these parameters

    Then:
    - The function should return the list of updated content items: ["item1.yml", "item2.yml"]
    - The open function should be called 4 times (2 reads and 2 writes)
    - The docker image information in the content items should be updated to the new image and tag
    """
    with patch("builtins.open", create=True) as mock_open:
        mock_open.return_value.__enter__.return_value.read.return_value = "dockerimage: old_image:old_tag"
        result = update_content_items_docker_images(
            docker_image="new_image", target_tag="new_tag", content_items=["item1.yml", "item2.yml"]
        )
    assert result == ["item1.yml", "item2.yml"]
    assert mock_open.call_count == 4  # 2 reads and 2 writes


def test_update_docker_state():
    """
    Given:
    - An initial docker state: {"image1": {"batch_number": 1, "last_pr_number": "100"}}
    - Affected items information: {"image1": {"content_items": ["item1"], "next_batch_number": 2}}
    - A new PR number: "101"

    When:
    - The update_docker_state function is called with these parameters

    Then:
    - The function should return an updated docker state
    - The batch number for "image1" should be updated to 2
    - The last PR number for "image1" should be updated to "101"
    """
    state = {"image1": {"batch_number": 1, "last_pr_number": "100"}}
    affected_items = {"image1": {"content_items": ["item1"], "next_batch_number": 2}}
    pr_number = "101"
    result = update_docker_state(state, affected_items, pr_number)
    assert result["image1"]["batch_number"] == 2
    assert result["image1"]["last_pr_number"] == "101"
