import logging
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from Tests.scripts.gitlab_slack_notifier import (
    bucket_sync_msg_builder,
    construct_coverage_slack_msg,
)


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

    bucket_sync_msg, bucket_sync_thread = bucket_sync_msg_builder(Path("test"))

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

    result = construct_coverage_slack_msg()
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

    construct_coverage_slack_msg()
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

    result = construct_coverage_slack_msg()
    assert "Last month: no coverage found for last month" in result[0]["title"]
