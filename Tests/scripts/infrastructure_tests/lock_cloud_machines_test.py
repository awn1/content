import collections
import json
import os
from argparse import Namespace

import pytest
import requests
from requests import ConnectionError, Response

from Tests.scripts.github_client import GithubClient
from Tests.scripts.infra.models import PublicApiKey
from Tests.scripts.infra.settings import Settings
from Tests.scripts.infra.xsoar_api import XsiamClient, XsoarClient
from Tests.scripts.lock_cloud_machines import (
    check_job_status,
    get_and_lock_all_needed_machines,
    get_chosen_machines_by_labels,
    get_machines_locks_details,
    get_my_place_in_the_queue,
    try_to_lock_machine,
    validate_connection_for_machines,
    wait_for_build_to_be_first_in_queue,
)


@pytest.mark.parametrize(
    "responses, expected_times_called, expected_status",
    [
        ([{"status": "running"}], 1, "running"),
        ([ConnectionError, {"status": "running"}], 2, "running"),
        ([ConnectionError, ConnectionError, {"status": "running"}], 3, "running"),
        ([ConnectionError, ConnectionError, ConnectionError, {"status": "running"}], 4, "running"),
        ([ConnectionError, ConnectionError, ConnectionError, {"status": "failed"}], 4, "failed"),
        ([ConnectionError, ConnectionError, {"status": "done"}], 3, "done"),
    ],
)
def test_check_job_status_with_connection_errors(mocker, responses, expected_times_called, expected_status):
    """
    given:  connection error exceptions and eventually real status.
    when:   trying to retrieve gitlab job status
    then:   make sure retry mechanism will be triggered on ConnectionErrors
    """
    side_effect_responses = []
    for response in responses:
        if not isinstance(response, dict):
            side_effect_responses.append(response)
        else:
            r = Response()
            r._content = json.dumps(response).encode()
            side_effect_responses.append(r)

    requests_mocker = mocker.patch.object(requests, "get", side_effect=side_effect_responses)

    assert check_job_status("token", project_id="1", job_id="1", interval=0.001) == expected_status
    assert requests_mocker.call_count == expected_times_called


def test_try_to_lock_machine(mocker):
    """
    given:  machine to try to lock.
    when:   locking for a free machine.
    then:   assert that lock_machine_name returned because the machine was free.
    """
    mocker.patch("Tests.scripts.lock_cloud_machines.check_job_status", return_value="running")
    mocker.patch("Tests.scripts.lock_cloud_machines.lock_machine", return_value="")

    lock_machine_name = try_to_lock_machine(
        "storage_bucket",
        "qa-test-1234",
        [{"job_id": "1235", "machine_name": "qa-test-1235", "project_id": "1234", "old_lock": True}],
        "gitlab_status_token",
        "gcs_locks_path",
        "1234",
    )
    assert lock_machine_name == "qa-test-1234"


def test_try_to_lock_occupied_machine(mocker):
    """
    given:  machine to try to lock.
    when:   locking for a free machine.
    then:   assert that lock_machine_name is empty because there is another lock file with a job that is running.
    """
    mocker.patch("Tests.scripts.lock_cloud_machines.check_job_status", return_value="running")
    mocker.patch("Tests.scripts.lock_cloud_machines.lock_machine", return_value="")

    lock_machine_name = try_to_lock_machine(
        "storage_bucket",
        "qa-test-1234",
        [
            {"project_id": "0", "job_id": "1234", "machine_name": "qa-test-1234", "old_lock": True},
            {"project_id": "0", "job_id": "1235", "machine_name": "qa-test-1235", "old_lock": True},
        ],
        "gitlab_status_token",
        "gcs_locks_path",
        "1234",
    )
    assert not lock_machine_name


class MockResponse:
    def __init__(self, name="", time_created=""):
        self.name = name
        self.time_created = time_created

    def list_blobs(self):
        print(self.name)


def test_get_my_place_in_the_queue(mocker):
    """
    given:  The job id .
    when:   checking the place in teh queue.
    then:   assert that returns the right place and the right previous_build_in_queue.
    """
    storage = MockResponse()
    mocker.patch.dict(os.environ, {"SLACK_TOKEN": "myslacktoken"})
    mocker.patch("Tests.scripts.lock_cloud_machines.GITLAB_PROJECT_ID", "1061")
    mocker.patch("Tests.scripts.lock_cloud_machines.send_slack_notification")
    mocker.patch.object(
        storage,
        "list_blobs",
        return_value=[
            MockResponse("test/queue/1061-queue-1234", "08/04/2000"),
            MockResponse("test/queue/1061-queue-1235", "05/04/2000"),
            MockResponse("test/queue/1061-queue-1236", "06/04/2000"),
            MockResponse("test/queue/1061-queue-1237", "03/04/2000"),
        ],
    )
    my_place_in_the_queue, previous_build_in_queue = get_my_place_in_the_queue(None, storage, "test", "1235", None)

    assert my_place_in_the_queue == 1
    assert previous_build_in_queue == "1061-queue-1237"


def test_get_my_place_in_the_queue_exception(mocker):
    """
    given:  The job id.
    when:   checking the place in the queue, and if it exists in the queue.
    then:   assert Exception is returned.
    """
    storage = MockResponse()
    mocker.patch.object(storage, "list_blobs", return_value=[MockResponse("test/queue/1234", "08/04/2000")])
    mocker.patch("Tests.scripts.lock_cloud_machines.send_slack_notification")
    with pytest.raises(Exception) as excinfo:
        get_my_place_in_the_queue(None, storage, "test", "1238", None)
    assert str(excinfo.value) == "Unable to find the queue lock file, probably a problem creating the file"


def test_get_machines_locks_details(mocker):
    """
    given:  storage to search.
    when:   get all the lock machines details.
    then:   assert that returns the right details.
    """
    storage = MockResponse()
    mocker.patch.object(
        storage,
        "list_blobs",
        return_value=[
            MockResponse("test/machines_locks/qa-test-1234-lock-1234"),
            MockResponse("test/machines_locks/qa-test-1235-lock-1235"),
            MockResponse("test/machines_locks/qa-test-1236-lock-1236"),
            MockResponse("test/machines_locks/qa-test-1237-lock-1237"),
        ],
    )
    files = get_machines_locks_details(storage, "test", "test", "machines_locks")
    assert files == [
        {"project_id": "1061", "job_id": "1234", "machine_name": "qa-test-1234", "old_lock": True},
        {"project_id": "1061", "job_id": "1235", "machine_name": "qa-test-1235", "old_lock": True},
        {"project_id": "1061", "job_id": "1236", "machine_name": "qa-test-1236", "old_lock": True},
        {"project_id": "1061", "job_id": "1237", "machine_name": "qa-test-1237", "old_lock": True},
    ]


def test_wait_for_build_to_be_first_in_queue(mocker):
    """
    given:  the queue and the job id.
    when:   the first loop the place in the queue wil be 1 and the previous_build_status wil be running.
            the second loop the place in the queue wil be 1 and the previous_build_status wil be failed.
            the third loop the place in the queue wil be 0.
    then:   assert the function "get_my_place_in_the_queue" wil be called 3 times.
            assert the function "check_job_status" wil be called 2 times.
            assert the function "remove_file" wil be called ones.
    """
    mock_my_place = mocker.patch(
        "Tests.scripts.lock_cloud_machines.get_my_place_in_the_queue", side_effect=[(1, "1234"), (1, "1234"), (0, "1234")]
    )
    mock_job_status = mocker.patch("Tests.scripts.lock_cloud_machines.check_job_status", side_effect=["running", "failed"])
    mock_remove_file = mocker.patch("Tests.scripts.lock_cloud_machines.remove_file")
    mocker.patch("Tests.scripts.lock_cloud_machines.sleep", return_value=None)
    mocker.patch("Tests.scripts.lock_cloud_machines.send_slack_notification")

    storage = MockResponse()
    wait_for_build_to_be_first_in_queue(None, storage, storage, "test", "1234", "12345")
    assert mock_my_place.call_count == 3
    assert mock_job_status.call_count == 2
    assert mock_remove_file.call_count == 1


def test_get_and_lock_all_needed_machines(mocker):
    """
    given:  the 2 available machines, machines_count_minimum_condition >=2 and the job id.
    when:   the first loop of the machines the machine1 will be busy and the machine2 will be available to lock.
            then the busy_machines will be [machine1] and the function sleep for 60 seconds.
            the second loop of the machines the machine1 will be available to lock.
    then:   assert the function "try_to_lock_machine" wil be called 3 times.
            assert the returned lock_machine_list == ["machine2", "machine1"]
    """
    storage = MockResponse()
    mocker.patch("Tests.scripts.lock_cloud_machines.get_machines_locks_details", return_value=[])
    mock_try_to_lock_machine = mocker.patch(
        "Tests.scripts.lock_cloud_machines.try_to_lock_machine", side_effect=["", "machine2", "machine1"]
    )
    mocker.patch("Tests.scripts.lock_cloud_machines.sleep", return_value=None)
    lock_machine_list = get_and_lock_all_needed_machines(
        storage, storage, ["machine1", "machine2"], "gcs_locks_path", "job_id", "gitlab_status_token", float("inf"), ">=2", ">=2"
    )
    assert mock_try_to_lock_machine.call_count == 3
    assert lock_machine_list == ["machine2", "machine1"]


def test_validate_connection_for_machines(mocker):
    """
    Given:
        Cloud servers dict and the chosen machine list.
    When:
        Validating that the machines are connectable via the API keys provided for them.
    Then:
        Assert no error is raised, meaning the keys are valid.
    """
    cloud_servers = {
        "__comment__": {
            "dictionary key": "mapping to the instance name",
            "ui_url": "The URL to access the instance in the browser",
            "instance_name": "The name of the instance",
            "base_url": "The base URL for the instance",
            "xsiam_version": "The version of the XSOAR instance",
            "demisto_version": "The version of the Demisto instance",
            "enabled": "Whether the instance is enabled",
            "flow_type": "The flow type of the instance: (nightly, upload, build, etc.)",
            "agent_host_name": "The name of the agent host",
            "agent_host_ip": "The IP address of the agent host",
            "build_machine": "Whether the instance is a build machine",
            "comment": "Any additional comments",
            "server_type": "The server type, can be either 'XSIAM' or 'XSOAR SAAS'",
        },
        "machine-xsoar1": {
            "ui_url": "https://url-xsoar1.us.paloaltonetworks.com",
            "instance_name": "machine-xsoar1",
            "base_url": "https://api-url-xsoar1.us.paloaltonetworks.com",
            "demisto_version": "99.99.98",
            "xsoar_ng_version": "8.7.0",
            "enabled": True,
            "flow_type": "build",
            "build_machine": True,
            "server_type": "XSOAR SAAS",
        },
        "machine-xsoar2": {
            "ui_url": "https://url-xsoar2.us.paloaltonetworks.com",
            "instance_name": "machine-xsoar2",
            "base_url": "https://api-url-xsoar1.us.paloaltonetworks.com",
            "demisto_version": "99.99.98",
            "xsoar_ng_version": "8.7.0",
            "enabled": True,
            "flow_type": "build",
            "build_machine": True,
            "server_type": "XSOAR SAAS",
        },
        "machine-xsiam1": {
            "ui_url": "https://url-xsiam1.us.paloaltonetworks.com/",
            "instance_name": "machine-xsiam1",
            "base_url": "https://api-url-xsiam1.us.paloaltonetworks.com",
            "xsiam_version": "ga",
            "demisto_version": "8.7.0",
            "enabled": True,
            "flow_type": "nightly",
            "agent_host_name": "Win10a",
            "agent_host_ip": "1.1.1.1",
            "build_machine": True,
            "server_type": "XSIAM",
        },
        "machine-xsiam2": {
            "ui_url": "https://url-xsiam2.us.paloaltonetworks.com/",
            "instance_name": "machine-xsiam2",
            "base_url": "https://api-url-xsiam2.us.paloaltonetworks.com",
            "xsiam_version": "ga",
            "demisto_version": "8.7.0",
            "enabled": True,
            "flow_type": "build",
            "agent_host_name": "Win10b",
            "agent_host_ip": "1.2.3.4",
            "build_machine": True,
            "server_type": "XSIAM",
        },
    }

    machine_list = ["machine-xsoar1", "machine-xsiam2", "machine-xsiam1"]
    Xsoar_Admin_User = collections.namedtuple("Xsoar_Admin_User", ["username", "password"])
    mocker.patch.object(Settings, "xsoar_admin_user", return_value=Xsoar_Admin_User("u", "p"))
    mocker.patch(
        "Tests.scripts.infra.xsoar_api.XsoarClient.get_gsm_cloud_machine_details",
        return_value=({"api-key": "a", "x-xdr-auth-id": 2}, "3"),
    )
    Machine_Health_Response = collections.namedtuple("Machine_Health_Response", ["ok"])
    mocker.patch.object(
        requests, "get", side_effect=[Machine_Health_Response(False), Machine_Health_Response(True)] * len(machine_list)
    )
    mocker.patch.object(XsoarClient, "login_via_okta")
    mocker_get_api_key = mocker.patch.object(XsoarClient, "create_api_key", return_value=PublicApiKey(id="3", key="b"))

    mocker_add_secret = mocker.patch(
        "SecretActions.add_build_machine.add_build_machine_secret_to_gsm",
        return_value=({"api-key": "b", "x-xdr-auth-id": 3}, "4"),
    )
    token_map = {"machine-xsiam1": "3", "machine-xsiam2": "4"}

    validate_connection_for_machines(machine_list, cloud_servers, token_map)

    expected_args = [
        {
            "server_id": "machine-xsiam2",
            "machine_type": "xsiam",
            "token_value": "4",
            "public_api_key": mocker_get_api_key.return_value,
        },
        {
            "server_id": "machine-xsiam1",
            "machine_type": "xsiam",
            "token_value": "3",
            "public_api_key": mocker_get_api_key.return_value,
        },
        {
            "server_id": "machine-xsoar1",
            "machine_type": "xsoar-ng",
            "public_api_key": mocker_get_api_key.return_value,
            "token_value": None,
        },
    ]

    # Check that only XSIAM machines were called with token
    for expected_arg in expected_args:
        assert any(call.kwargs == expected_arg for call in mocker_add_secret.call_args_list)


def test_xsoar_user_label_found(mocker):
    """
    Test case to verify that when an XSOAR user label is found,
    the function correctly retrieves the GitHub PR author, maps it to a Slack username,
    and returns the Slack username.
    """
    github_client = GithubClient("")
    labels = ["chosen-machine-xsoar-user"]
    pr_number = 123
    options = Namespace()
    options.server_type = XsoarClient.SERVER_TYPE
    options.name_mapping_path = "/mock/path"
    options.chosen_machine_path = "/mock/chosen_machine.txt"

    mock_get_pr_author = mocker.patch("Tests.scripts.lock_cloud_machines.get_pr_author", return_value="mock_github_user")
    mock_get_slack_user_name = mocker.patch(
        "Tests.scripts.lock_cloud_machines.get_slack_user_name", return_value="mock_slack_user"
    )
    mocker.patch("builtins.open")

    result = get_chosen_machines_by_labels(github_client, labels, pr_number, options)

    assert result == "mock_slack_user"
    mock_get_pr_author.assert_called_once_with(github_client, pr_number)
    mock_get_slack_user_name.assert_called_once_with(name="mock_github_user", default="not found", name_mapping_path="/mock/path")


def test_xsoar_user_label_not_found():
    """
    Test case to verify that if no matching label is found in the provided list,
    the function returns an empty string and does not attempt to fetch GitHub or Slack usernames.
    """
    github_client = GithubClient("")
    labels = ["random-label"]
    pr_number = 123
    options = Namespace()
    options.server_type = XsoarClient.SERVER_TYPE
    options.name_mapping_path = "/mock/path"
    options.chosen_machine_path = "/mock/chosen_machine.txt"

    result = get_chosen_machines_by_labels(github_client, labels, pr_number, options)

    assert result == ""  # No matching label found


def test_xsiam_flow_type_label_found(mocker):
    """
    Test case to verify that when a valid XSIAM flow type label is found,
    the function extracts the flow type correctly and returns it.
    """
    github_client = GithubClient("")
    labels = ["chosen-machine-xsiam-testflow"]
    pr_number = 123
    options = Namespace()
    options.server_type = XsiamClient.SERVER_TYPE
    options.name_mapping_path = "/mock/path"
    options.chosen_machine_path = "/mock/chosen_machine.txt"

    mocker.patch("builtins.open")

    result = get_chosen_machines_by_labels(github_client, labels, pr_number, options)

    assert result == "testflow"  # Extracted from label


def test_invalid_label_format():
    """
    Test case to verify that if an invalid label format is provided,
    the function returns an empty string instead of an incorrectly parsed value.
    """
    github_client = GithubClient("")
    labels = ["chosen-machine-xsiam"]
    pr_number = 123
    options = Namespace()
    options.server_type = XsiamClient.SERVER_TYPE
    options.name_mapping_path = "/mock/path"
    options.chosen_machine_path = "/mock/chosen_machine.txt"

    result = get_chosen_machines_by_labels(github_client, labels, pr_number, options)

    assert result == ""  # Invalid format should return empty string
