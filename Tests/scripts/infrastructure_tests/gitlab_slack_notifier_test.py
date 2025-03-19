import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from gitlab import Gitlab
from pytest_mock import MockerFixture

import Tests.scripts.gitlab_slack_notifier as gitlab_slack_notifier


@pytest.mark.parametrize(
    "mock_value, expected_bucket_sync_msg, expected_bucket_sync_thread",
    [
        (
            "201",
            [],
            [
                {
                    "fallback": "Sync all buckets pipeline triggered successfully. Status Code: 201",
                    "title": "Sync all buckets pipeline triggered successfully. Status Code: 201",
                    "color": "good",
                    "fields": [
                        {
                            "title": "",
                            "value": "Check the <|xdr-content-sync> channel for job status updates.",
                            "short": False,
                        }
                    ],
                }
            ],
        ),
        (
            "400",
            [
                {
                    "fallback": ":alert: Failed to triggered Sync all buckets pipeline, Status Code: 400",
                    "title": ":alert: Failed to triggered Sync all buckets pipeline, Status Code: 400",
                    "color": "danger",
                }
            ],
            [],
        ),
        ("skipped", [], []),
        (
            "Some Error",
            [
                {
                    "fallback": ":alert: Failed to triggered Sync all buckets pipeline, Error: Some Error",
                    "title": ":alert: Failed to triggered Sync all buckets pipeline, Error: Some Error",
                    "color": "danger",
                }
            ],
            [],
        ),
        (
            None,
            [],
            [
                {
                    "fallback": "The Sync all buckets job was not triggered for any reason",
                    "title": "The Sync all buckets job was not triggered for any reason",
                    "color": "danger",
                }
            ],
        ),
    ],
)
def test_bucket_sync_msg_builder(
    mocker: MockerFixture,
    mock_value: str | None,
    expected_bucket_sync_msg: list,
    expected_bucket_sync_thread: list,
):
    """
    Given:
        - Mock path to artifact
        - Mock returned from `get_artifact_data` function:
          1. 201 (Triggered successfully)
          2. 400 (Triggered failure with HTTPError)
          3. Some Error (Triggered failure without HTTPError)
          4. skipped (In case that test-upload-flow run)
          5. None (In case that log file does not exist, the job failed etc..)

    When:
        - The `bucket_sync_msg_builder` function
    Then:
        - Ensure that the msg and thread msg are returned as expected in each specific case.
    """
    mocker.patch("Tests.scripts.gitlab_slack_notifier.get_artifact_data", return_value=mock_value)
    mocker.patch.object(logging, "debug")
    mocker.patch.object(logging, "info")

    bucket_sync_msg, bucket_sync_thread = gitlab_slack_notifier.bucket_sync_msg_builder(Path("test"))

    assert bucket_sync_msg == expected_bucket_sync_msg
    assert bucket_sync_thread == expected_bucket_sync_thread


@pytest.mark.parametrize(
    "mock_coverage_today, mock_coverage_yesterday, expected_color",
    [
        pytest.param(1.0, 0.5, "good", id="Case 1: Today's coverage percentage is higher then yesterday"),
        pytest.param(
            0.76,
            1.0,
            "good",
            id="Case 2: Today's coverage percentage is less than yesterday's but the difference is less than 0.25 percent",
        ),
        pytest.param(
            0.74,
            1.0,
            "danger",
            id="Case 3: Today's coverage percentage is less than yesterday's and the difference is higher than 0.25 percent",
        ),
    ],
)
def test_construct_coverage_slack_msg(
    mocker: MockerFixture,
    mock_coverage_today: float,
    mock_coverage_yesterday: float,
    expected_color: str,
):
    """
    Given:
        - No args given
    When:
        - the construct_coverage_slack_msg function runs with mocking values.
    Then:
        - Ensure the msg color is as expected.
    """
    mocker.patch(
        "demisto_sdk.commands.coverage_analyze.tools.get_total_coverage",
        side_effect=[mock_coverage_today, mock_coverage_yesterday, 1.0],
    )

    result = gitlab_slack_notifier.construct_coverage_slack_msg()
    assert result[0]["color"] == expected_color


@pytest.mark.parametrize(
    "coverage_last_month, expected_calls",
    [
        pytest.param(0.0, 4, id="Case 1: the coverage file from a month ago does not exist"),
        pytest.param(1.0, 3, id="Case 2: the coverage file from a month ago exist"),
    ],
)
def test_construct_coverage_slack_msg_coverage_last_month(
    mocker: MockerFixture,
    coverage_last_month: float,
    expected_calls: str,
):
    mock_get_total_coverage = mocker.patch(
        "demisto_sdk.commands.coverage_analyze.tools.get_total_coverage",
        side_effect=[1.0, 1.0, coverage_last_month, 1.0],
    )

    gitlab_slack_notifier.construct_coverage_slack_msg()
    assert expected_calls == mock_get_total_coverage.call_count


def test_construct_coverage_slack_msg_no_coverage_last_month(
    mocker: MockerFixture,
):
    """
    Given:
        - No args given
    When:
        - the construct_coverage_slack_msg function runs and simulates a scenario
          where no coverage file exists within the time range from a month ago.
    Then:
        - Ensure the msg includes the expected value for last month.
    """
    mocker.patch(
        "demisto_sdk.commands.coverage_analyze.tools.get_total_coverage",
        return_value=0.0,
    )

    result = gitlab_slack_notifier.construct_coverage_slack_msg()
    assert "Last month: no coverage found for last month" in result[0]["title"]


# Mock objects
mock_pipeline_1 = MagicMock(id=67889)
mock_pipeline_2 = MagicMock(id=67890)
mock_job_1 = MagicMock(id=67890, name="blacklist-validation-job")
mock_job_2 = MagicMock(id=67889, name="blacklist-validation-job")

# Mock artifacts
mock_artifacts_1 = {"secrets": ["secret1", "secret2"]}
mock_artifacts_2 = {"secrets": ["secret1", "secret3"]}


@pytest.mark.parametrize(
    """is_within_time_window_return, get_scheduled_pipelines_by_name_return, get_job_by_name_side_effect,
    download_and_read_artifact_side_effect, is_blacklist_pivot_return, secrets_sha_has_been_changed_return, expected_result""",
    [
        pytest.param(
            True,
            [mock_pipeline_1, mock_pipeline_2],
            [mock_job_1, mock_job_2],
            [mock_artifacts_1, mock_artifacts_2],
            None,
            None,
            (True, "Daily Heartbeat - "),
            id="Within time window",
        ),
        pytest.param(
            False,
            [mock_pipeline_1, mock_pipeline_2],
            [mock_job_1, mock_job_2],
            [mock_artifacts_1, mock_artifacts_2],
            True,
            None,
            (True, "Secrets found! :warning:"),
            id="Pivot detected",
        ),
        pytest.param(
            False,
            [mock_pipeline_1, mock_pipeline_2],
            [mock_job_1, mock_job_2],
            [mock_artifacts_1, mock_artifacts_2],
            False,
            None,
            (True, "Successfully fixed! :muscle:"),
            id="Pivot fixed",
        ),
        pytest.param(
            False,
            [mock_pipeline_1, mock_pipeline_2],
            [mock_job_1, mock_job_2],
            [mock_artifacts_1, mock_artifacts_2],
            None,
            True,
            (True, "The set of detected secrets has changed! Secrets found :warning:"),
            id="No pivot, secrets SHA changed",
        ),
        pytest.param(
            False,
            [mock_pipeline_1, mock_pipeline_2],
            [mock_job_1, mock_job_2],
            [mock_artifacts_1, mock_artifacts_1],
            None,
            False,
            (False, ""),
            id="No pivot, secrets SHA not changed",
        ),
        pytest.param(False, [mock_pipeline_2], None, None, None, None, (False, ""), id="Not enough pipelines"),
    ],
)
@patch("time.sleep")  # Mock time.sleep
def test_should_send_blacklist_message(
    mock_sleep,
    mocker,
    is_within_time_window_return,
    get_scheduled_pipelines_by_name_return,
    get_job_by_name_side_effect,
    download_and_read_artifact_side_effect,
    is_blacklist_pivot_return,
    secrets_sha_has_been_changed_return,
    expected_result,
):
    """
    Test the should_send_blacklist_message function with various scenarios.

    Args:
        mocker: The mocker fixture for patching.
        is_within_time_window_return (bool): The return value for the is_within_time_window function.
        get_scheduled_pipelines_by_name_return (list): The return value for the get_scheduled_pipelines_by_name function.
        get_job_by_name_side_effect (list): The side effect for the get_job_by_name function.
        download_and_read_artifact_side_effect (list): The side effect for the download_and_read_artifact function.
        is_blacklist_pivot_return (bool or None): The return value for the is_blacklist_pivot function.
        secrets_sha_has_been_changed_return (bool or None): The return value for the secrets_sha_has_changed function.
        expected_result (tuple): The expected result from the should_send_blacklist_message function.

    Scenarios:
        - Within time window.
        - Pivot detected.
        - Pivot fixed.
        - No pivot, secrets SHA changed.
        - No pivot, secrets SHA not changed.
        - Not enough pipelines.

    Asserts:
        - The result from should_send_blacklist_message matches the expected result.
    """
    # Create a mock GitLab client
    gitlab_client = MagicMock(spec=Gitlab)
    project_id = "12345"

    # Mock the time window check
    mocker.patch.object(gitlab_slack_notifier, "is_within_time_window", return_value=is_within_time_window_return)

    # Mock the pipelines
    mocker.patch.object(
        gitlab_slack_notifier, "get_scheduled_pipelines_by_name", return_value=get_scheduled_pipelines_by_name_return
    )

    # Mock the jobs
    mocker.patch.object(gitlab_slack_notifier, "get_job_by_name", side_effect=get_job_by_name_side_effect)

    # Mock the artifact download
    mocker.patch.object(gitlab_slack_notifier, "download_and_read_artifact", side_effect=download_and_read_artifact_side_effect)

    # Mock the pivot check
    mocker.patch.object(gitlab_slack_notifier, "is_blacklist_pivot", return_value=is_blacklist_pivot_return)

    # Mock the secrets SHA check
    mocker.patch.object(gitlab_slack_notifier, "secrets_sha_has_changed", return_value=secrets_sha_has_been_changed_return)

    # Mock the blacklist status details
    mocker.patch.object(gitlab_slack_notifier, "get_blacklist_status_details", return_value="")

    result = gitlab_slack_notifier.should_send_blacklist_message(gitlab_client, project_id, 1, 2, 3)
    assert result == expected_result
