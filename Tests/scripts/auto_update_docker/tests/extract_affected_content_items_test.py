from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from Tests.scripts.auto_update_docker.extract_affected_content_items import (
    filter_content_items_to_run_on,
    generate_slack_thread_msg,
    get_affected_content_items_by_docker_image,
    get_content_item_to_add,
    get_content_items_by_docker_image,
    get_pr_status,
    increase_batch_number,
    return_content_item_with_suffix,
)


@patch("Tests.scripts.auto_update_docker.extract_affected_content_items.Github")
def test_get_pr_status(mock_github):
    """
    Given a pull request number
    When get_pr_status is called
    Then it should return the correct status and time information

    Given:
    - A mocked Github client
    - Different PR states (merged, closed, open)

    When:
    - get_pr_status is called with a PR number

    Then:
    - It should return the correct status for merged PR
    - It should return the correct status for closed PR
    - It should return the correct status for open PR
    """
    mock_repo = MagicMock()
    mock_pr = MagicMock()
    mock_github.return_value.get_repo.return_value = mock_repo
    mock_repo.get_pull.return_value = mock_pr

    # Test merged PR
    mock_pr.state = "closed"
    mock_pr.merged = True
    mock_pr.merged_at = datetime(2023, 1, 1, tzinfo=timezone.utc)
    result = get_pr_status(1)
    assert result["status"] == "merged"

    # Test closed PR
    mock_pr.merged = False
    mock_pr.closed_at = datetime(2023, 1, 1, tzinfo=timezone.utc)
    result = get_pr_status(1)
    assert result["status"] == "closed"

    # Test open PR
    mock_pr.state = "open"
    mock_pr.created_at = datetime(2023, 1, 1, tzinfo=timezone.utc)
    result = get_pr_status(1)
    assert result["status"] == "open"


def test_get_content_item_to_add():
    """
    Given a set of parameters for a content item
    When get_content_item_to_add is called
    Then it should return the correct content item path or None

    Given:
    - Parameters for a content item including nightly status, support levels, and coverage

    When:
    - get_content_item_to_add is called with these parameters

    Then:
    - It should return the correct content item path when all conditions are met
    - It should return None when the pack is not in nightly_packs
    """
    result = get_content_item_to_add(
        only_nightly=True,
        nightly_packs=["TestPack"],
        content_item_pack_path="TestPack",
        content_item_path=Path("TestPack/Scripts/TestScript.py"),
        target_tag="1.0.0",
        content_item_docker_image_tag="0.9.0",
        support_levels=["xsoar"],
        content_item_support="xsoar",
        min_cov=80,
        content_item_cov=85.0,
    )
    assert result == "TestPack/Scripts/TestScript.yml"

    result = get_content_item_to_add(
        only_nightly=True,
        nightly_packs=["OtherPack"],
        content_item_pack_path="TestPack",
        content_item_path=Path("TestPack/Scripts/TestScript.py"),
        target_tag="1.0.0",
        content_item_docker_image_tag="0.9.0",
        support_levels=["xsoar"],
        content_item_support="xsoar",
        min_cov=80,
        content_item_cov=85.0,
    )
    assert result is None


def test_filter_content_items_to_run_on():
    """
    Given a batch configuration and content items
    When filter_content_items_to_run_on is called
    Then it should return the correct list of content items to run on

    Given:
    - A batch configuration with nightly, coverage, and support settings
    - A list of content items with their properties

    When:
    - filter_content_items_to_run_on is called with these inputs

    Then:
    - It should return a list of content items that meet the batch criteria
    """
    batch_config = {"only_nightly": True, "min_coverage": 80, "support": ["xsoar"]}
    content_items_coverage = {"TestPack/Scripts/TestScript.py": 85.0}
    content_items_by_docker_image = [
        {
            "content_item": "TestPack/Scripts/TestScript.py",
            "pack_path": "TestPack",
            "support_level": "xsoar",
            "docker_image_tag": "0.9.0",
        }
    ]
    target_tag = "1.0.0"
    nightly_packs = ["TestPack"]

    result = filter_content_items_to_run_on(
        batch_config, content_items_coverage, content_items_by_docker_image, target_tag, nightly_packs
    )
    assert result == ["TestPack/Scripts/TestScript.yml"]


def test_increase_batch_number():
    """
    Given a current batch number and total number of batches
    When increase_batch_number is called
    Then it should return the correct next batch number

    Given:
    - A current batch number
    - The total number of batches

    When:
    - increase_batch_number is called with these inputs

    Then:
    - It should return the next batch number or 0 if it reaches the total
    """
    assert increase_batch_number(1, 3) == 2
    assert increase_batch_number(3, 3) == 0


@patch("Tests.scripts.auto_update_docker.extract_affected_content_items.ContentGraphInterface")
def test_get_content_items_by_docker_image(mock_graph):
    """
    Given a mocked ContentGraphInterface
    When get_content_items_by_docker_image is called
    Then it should return the correct dictionary of content items by docker image

    Given:
    - A mocked ContentGraphInterface with predefined return values

    When:
    - get_content_items_by_docker_image is called

    Then:
    - It should return a dictionary with docker images as keys and content item details as values
    """
    mock_session = MagicMock()
    mock_graph.return_value.__enter__.return_value.driver.session.return_value.__enter__.return_value = mock_session
    mock_session.execute_read.return_value = [
        ("demisto/python3:1.0.0", "TestPack/Scripts/TestScript.yml", "python", "Packs/TestPack", "xsoar")
    ]

    result = get_content_items_by_docker_image()
    assert "demisto/python3" in result
    assert len(result["demisto/python3"]) == 1
    assert result["demisto/python3"][0]["content_item"] == Path("TestPack/Scripts/TestScript.py")
    assert result["demisto/python3"][0]["support_level"] == "xsoar"
    assert result["demisto/python3"][0]["pack_path"] == "TestPack"
    assert result["demisto/python3"][0]["docker_image_tag"] == "1.0.0"


def test_return_content_item_with_suffix():
    """
    Given a content item YAML path and type
    When return_content_item_with_suffix is called
    Then it should return the correct path with the appropriate suffix

    Given:
    - A content item YAML path
    - A content item type (python or powershell)

    When:
    - return_content_item_with_suffix is called with these inputs

    Then:
    - It should return the correct path with .py or .ps1 suffix
    - It should raise an exception for unknown types
    """
    assert return_content_item_with_suffix("TestPack/Scripts/TestScript.yml", "python") == Path("TestPack/Scripts/TestScript.py")
    assert return_content_item_with_suffix("TestPack/Scripts/TestScript.yml", "powershell") == Path(
        "TestPack/Scripts/TestScript.ps1"
    )

    with pytest.raises(Exception):
        return_content_item_with_suffix("TestPack/Scripts/TestScript.yml", "unknown")


def test_get_affected_content_items_by_docker_image():
    """
    Given content items coverage, docker state, PR state, and content items by docker image
    When get_affected_content_items_by_docker_image is called
    Then it should return the correct affected content items for the docker image

    Given:
    - Content items coverage data for a test script
    - Docker state information for a Python3 docker image
    - PR state information for a merged PR
    - Content items grouped by docker image
    - List of nightly packs

    When:
    - get_affected_content_items_by_docker_image is called with these inputs

    Then:
    - It should return a dictionary with "demisto/python3" as a key
    - The "demisto/python3" entry should contain the correct content item
    - The next batch number should be 2
    """
    content_items_coverage = {"TestPack/Scripts/TestScript.py": 85.0}
    batches_config = (
        '{"batches": [{"min_coverage": 70, "support": ["xsoar", "partner", "community"], "only_nightly": true}, '
        '{"min_coverage": 90, "support": ["xsoar"]}], "cadence": {"hours": 336, "from": "merged"}}'
    )
    docker_state = {
        "demisto/python3": {"docker_tag": "1.0.0", "batch_number": "1", "batches_config": batches_config, "last_pr_number": "123"}
    }
    prs_state = {"123": {"status": "merged", "hours_passed": 340}}
    content_items_by_docker_image = {
        "demisto/python3": [
            {
                "content_item": Path("TestPack/Scripts/TestScript.py"),
                "support_level": "xsoar",
                "pack_path": "TestPack",
                "docker_image_tag": "0.9.0",
            }
        ]
    }
    nightly_packs = ["TestPack"]

    result = get_affected_content_items_by_docker_image(
        content_items_coverage, docker_state, prs_state, content_items_by_docker_image, nightly_packs
    )

    assert "demisto/python3" in result
    assert result["demisto/python3"]["content_items"] == ["TestPack/Scripts/TestScript.yml"]
    assert result["demisto/python3"]["next_batch_number"] == 2


def test_generate_slack_thread_msg():
    """
    Given a PR state with open and merged PRs
    When generate_slack_thread_msg is called
    Then it should return the correct Slack message for open PRs

    Given:
    - PR state with two open PRs and one merged PR

    When:
    - generate_slack_thread_msg is called with this PR state

    Then:
    - It should return a list with one Slack message
    - The message should contain the correct pretext
    - The message should include the open PR numbers
    - The message should not include the merged PR number

    Given:
    - PR state with no open PRs

    When:
    - generate_slack_thread_msg is called with this PR state

    Then:
    - It should return an empty list
    """
    prs_state = {"123": {"status": "open"}, "124": {"status": "merged"}, "125": {"status": "open"}}

    result = generate_slack_thread_msg(prs_state)
    assert len(result) == 1
    assert "List of PRs awaiting review:" in result[0]["pretext"]
    assert "PR #123" in result[0]["text"]
    assert "PR #125" in result[0]["text"]
    assert "PR #124" not in result[0]["text"]

    # Test with no open PRs
    prs_state = {"123": {"status": "merged"}, "124": {"status": "closed"}}
    result = generate_slack_thread_msg(prs_state)
    assert result == []
