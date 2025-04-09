import pytest
import requests
from pytest_mock import MockerFixture
from requests.models import Response

from Tests.scripts.trigger_jenkins_job import main


class MockNamespace:
    url = "https://test"
    username = "test"
    token = "test"
    root_folder = None


@pytest.mark.parametrize(
    "mock_status, expected_log",
    [
        (201, "Jenkins job triggered successfully. Status code: 201"),
        (400, "Triggered Sync all buckets failed, Status code: 400"),
    ],
)
def test_main(mocker: MockerFixture, mock_status: int, expected_log: str):
    """
    Given:
        - args for script
    When:
        - The main function run
    Then:
        - Ensure that the log file for the `status_cod` is created
          with the expected `status_code`.
        - Ensure that the expected log message is printed
    """
    mocker.patch(
        "Tests.scripts.trigger_jenkins_job.options_handler",
        return_value=MockNamespace(),
    )
    mocker.patch("Tests.scripts.trigger_jenkins_job.install_logging")
    res_mock = Response()
    res_mock.status_code = mock_status
    mocker.patch.object(requests, "post", return_value=res_mock)
    mock_logging = mocker.patch("logging.info")
    mock_write_text = mocker.patch("pathlib.Path.write_text")

    main()

    assert mock_write_text.call_args_list[0][0][0] == str(mock_status)
    assert mock_logging.call_args_list[1][0][0] == expected_log


def test_main_with_some_error(mocker: MockerFixture):
    """
    Given:
        - args for script
    When:
        - The main function run
    Then:
        - Ensure that the log file for the 'status_cod' is created
          with the expected value even when the API call failed without an HTTPError.
        - Ensure that the expected log message is printed
    """
    mocker.patch(
        "Tests.scripts.trigger_jenkins_job.options_handler",
        return_value=MockNamespace(),
    )
    mocker.patch("Tests.scripts.trigger_jenkins_job.install_logging")
    mocker.patch.object(requests, "post", side_effect=Exception("test"))
    mock_logging = mocker.patch("logging.info")
    mock_write_text = mocker.patch("pathlib.Path.write_text")
    main()
    assert mock_write_text.call_args_list[0][0][0] == "Some Error"
    assert mock_logging.call_args_list[1][0][0] == "Triggered Sync all buckets failed, Error: test"
