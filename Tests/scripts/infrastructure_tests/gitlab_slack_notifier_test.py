import logging
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from Tests.scripts.gitlab_slack_notifier import bucket_sync_msg_builder


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
