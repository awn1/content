from pathlib import Path
from unittest.mock import MagicMock

import pytest

from Tests.scripts.common import AUTO_CLOSE_LABEL, AUTO_CLOSE_PROPERTY, Execution_Type
from Tests.scripts.jira_issues import (
    get_property_value,
    jira_auto_close_issue,
    set_property_value,
    write_auto_close_to_jira_mapping,
)

ISSUE_KEY = "CIAC-1111"


def test_set_auto_close_value(mocker):
    """
    Given:
        A requests mock object

    When:
        The set_property_value function is called with the mock client

    Then:
        assert api request was called with the required parameters
    """
    jira_server = MagicMock()
    mock_add_property = jira_server.add_issue_property
    mocker.patch("jira.client.JIRA.add_issue_property")
    set_property_value(jira_server, ISSUE_KEY, AUTO_CLOSE_PROPERTY, 2)
    mock_add_property.assert_called_with(issue=ISSUE_KEY, key=AUTO_CLOSE_PROPERTY, data=2)


def test_get_property_value(mocker):
    """
    Given:
        A requests mock object

    When:
        The get_property_value function is called with the mock client

    Then:
        - assert api request was called with the required parameters
        - assert that the correct issue property value was returned
    """
    jira_server = MagicMock()
    mock_issue_property = MagicMock()
    mock_issue_property.key = "auto-close-counter"
    mock_issue_property.value = 2
    jira_server.issue_properties.return_value = [mock_issue_property]
    mocker.patch("jira.client.JIRA.issue_properties")
    result = get_property_value(jira_server, ISSUE_KEY, AUTO_CLOSE_PROPERTY)
    assert result == 2


def test_jira_auto_close_issue_issue_no_label():
    """
    Given
    - A mocked Jira server with a specific issue and auto-close properties.

    When
    - Calling the `jira_auto_close_issue` method.

    Then
    - Validate that a playbook without the auto-close label won't preform the auto-close mechanism.
    """
    jira_server = MagicMock()
    jira_tickets_for_playbooks = {"TestPlaybook_no_label": jira_server.issue(id="CIAC-1")}
    failed_playbooks = {"TestPlaybook_no_label": {"failures": 0}}
    res = jira_auto_close_issue(jira_server, jira_tickets_for_playbooks, failed_playbooks)
    assert res == ({}, {}, {})


def test_jira_auto_close_issue_issue_label_test_playbook_success(mocker):
    """
    Given
    - A mocked Jira server with a specific issue and auto-close properties.

    When
    - Calling the `jira_auto_close_issue` method with the mocked Jira server, tickets, and failed playbooks.

    Then
    - Validate that the playbook with the auto-close label and passed test-playbook,
     will increase the property value by 1.
    """

    failed_playbooks = {"TestPlaybook_label_1_success": {"failures": 0}}
    jira_server, fields = MagicMock(), MagicMock()
    fields.labels = [AUTO_CLOSE_LABEL]
    jira_server.issue.return_value = MagicMock(fields=fields, properties=AUTO_CLOSE_PROPERTY)

    # mock increasing issue property
    mocker.patch("jira.client.JIRA.add_issue_property")
    mocker.patch("Tests.scripts.jira_issues.get_property_value", return_value=1)
    mock_add_property = jira_server.add_issue_property

    jira_tickets_for_playbooks = {
        "TestPlaybook_label_1_success": jira_server.issue(id=ISSUE_KEY, fields=fields, properties=AUTO_CLOSE_PROPERTY)
    }
    (runs_with_auto_close, failed_runs_with_auto_close, successful_closed_tickets) = jira_auto_close_issue(
        jira_server, jira_tickets_for_playbooks, failed_playbooks
    )

    # Check that the playbook was correctly processed with the auto-close label
    assert mock_add_property.call_args_list[0][1]["data"] == 2
    assert "TestPlaybook_label_1_success" in runs_with_auto_close
    assert failed_runs_with_auto_close == successful_closed_tickets == {}


def test_jira_auto_close_issue_issue_label_test_playbook_fail(mocker):
    """
    Given
    - A mocked Jira server with a specific issue and auto-close properties.

    When
    - Calling the `jira_auto_close_issue` method with the mocked Jira server, tickets, and failed playbooks.

    Then
    - Validate that the playbook with the auto-close label and failed test-playbook,
     will reset the property 'auto-close-counter' to 0.
    """
    failed_playbooks = {"TestPlaybook_label_2_fail": {"failures": 1}}
    jira_server, fields = MagicMock(), MagicMock()
    fields.labels = [AUTO_CLOSE_LABEL]
    jira_server.issue.return_value = MagicMock(fields=fields, properties=AUTO_CLOSE_PROPERTY)
    mocker.patch("Tests.scripts.jira_issues.get_property_value", return_value=1)
    # mock increasing issue property
    mocker.patch("jira.client.JIRA.add_issue_property")
    mock_add_property = jira_server.add_issue_property

    jira_tickets_for_playbooks = {
        "TestPlaybook_label_2_fail": jira_server.issue(id="CIAC-2111", fields=fields, properties=AUTO_CLOSE_PROPERTY)
    }
    (runs_with_auto_close, failed_runs_with_auto_close, successful_closed_tickets) = jira_auto_close_issue(
        jira_server, jira_tickets_for_playbooks, failed_playbooks
    )

    # Check that the playbook was correctly processed with the auto-close label
    assert not mock_add_property.call_args_list[0][1]["data"]
    assert "TestPlaybook_label_2_fail" in failed_runs_with_auto_close
    assert runs_with_auto_close == successful_closed_tickets == {}


def test_jira_auto_close_issue_issue_label_test_playbook_success_remove_label(mocker):
    """
    Given
    - A mocked Jira server with a specific issue and auto-close properties.

    When
    - Calling the `jira_auto_close_issue` method with the mocked Jira server, tickets, and failed playbooks.

    Then
    - Validate that the playbook with the auto-close label and successe test-playbook,
     will reset the property 'auto-close-counter' to 0.
    """
    failed_playbooks = {"TestPlaybook_label_2_success": {"failures": 0}}
    jira_server, fields = MagicMock(), MagicMock()
    fields.labels = [AUTO_CLOSE_LABEL]
    jira_server.issue.return_value = MagicMock(fields=fields, properties=AUTO_CLOSE_PROPERTY)
    mocker.patch("Tests.scripts.jira_issues.get_property_value", return_value=2)
    # mock increasing issue property
    mocker.patch("jira.client.JIRA.add_issue_property")
    mock_add_property = jira_server.add_issue_property

    mocker.patch("jira.client.JIRA.transition_issue")
    mock_transition_issue = jira_server.transition_issue

    jira_tickets_for_playbooks = {
        "TestPlaybook_label_2_success": jira_server.issue(id="CIAC-2111", fields=fields, properties=AUTO_CLOSE_PROPERTY)
    }

    (runs_with_auto_close, failed_runs_with_auto_close, successful_closed_tickets) = jira_auto_close_issue(
        jira_server, jira_tickets_for_playbooks, failed_playbooks
    )

    # Check that the playbook was correctly processed with the auto-close label
    assert mock_transition_issue.call_args_list[0][1]["transition"] == "Done"
    assert mock_transition_issue.call_args_list[0][1]["fields"]["resolution"]["name"] == "Fixed"
    assert not mock_add_property.call_args_list[0][1]["data"]
    assert "TestPlaybook_label_2_success" in successful_closed_tickets
    assert runs_with_auto_close == failed_runs_with_auto_close == {}


@pytest.fixture
def mock_dependencies_write_auto_close_to_jira_mapping(mocker):
    """
    Fixture to mock external dependencies used by the write_auto_close_to_jira_mapping function.
    """
    # Mock the create_jira_mapping_dict function

    mock_create_jira_mapping_dict = mocker.patch("Tests.scripts.jira_issues.create_jira_mapping_dict")

    # Mock the save_jira_mapping_to_file function
    mock_save_jira_mapping_to_file = mocker.patch("Tests.scripts.jira_issues.save_jira_mapping_to_file")
    return mock_create_jira_mapping_dict, mock_save_jira_mapping_to_file


def test_write_auto_close_to_jira_mapping(mock_dependencies_write_auto_close_to_jira_mapping):
    """
    Given:
        - Mocked create_jira_mapping_dict and save_jira_mapping_to_file functions.

    When:
        - The write_auto_close_to_jira_mapping function is called with test data.

    Then:
        - Assert that create_jira_mapping_dict is called with the correct arguments for playbook tickets and auto-close logs.
        - Assert that save_jira_mapping_to_file is called with the correct file paths and data.
    """
    # Unpack the mocked functions
    mock_create_jira_mapping_dict, mock_save_jira_mapping_to_file = mock_dependencies_write_auto_close_to_jira_mapping

    # Sample test data
    server_url = "https://jira.example.com"
    artifacts_path = Path("/path/to/artifacts")
    path_auto_resolve = "auto_resolved_tickets.json"

    runs_with_auto_close = {"PB-103": MagicMock()}
    failed_auto_close = {"PB-104": MagicMock()}

    # Mock return values for create_jira_mapping_dict
    mock_create_jira_mapping_dict.return_value = {"PB-101": ISSUE_KEY}

    # Call the function under test
    write_auto_close_to_jira_mapping(
        server_url=server_url,
        artifacts_path=artifacts_path,
        path_auto_close=path_auto_resolve,
        runs_with_property=runs_with_auto_close,
        failed_property=failed_auto_close,
        successful_property=None,
        test_execution_type=Execution_Type.TEST_PLAYBOOKS,
    )

    # Assertions
    # Check that create_jira_mapping_dict was called for both playbooks and auto-close logs
    mock_create_jira_mapping_dict.assert_any_call(server_url, runs_with_auto_close)
    mock_create_jira_mapping_dict.assert_any_call(server_url, failed_auto_close)
    # Check that save_jira_mapping_to_file was called for playbooks and auto-close logs
    assert artifacts_path / path_auto_resolve in mock_save_jira_mapping_to_file.call_args[0]
    assert {
        "Current TestPlaybooks running with auto close": {"PB-101": ISSUE_KEY},
        "Failed TestPlaybooks": {"PB-101": ISSUE_KEY},
    } in mock_save_jira_mapping_to_file.call_args[0]
