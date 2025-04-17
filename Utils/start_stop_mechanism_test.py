import logging
from unittest.mock import patch

import pytest

from Tests.scripts.infra.viso_api import VisoAPI


@pytest.fixture(autouse=True)
def set_env_vars(monkeypatch):
    monkeypatch.setenv("VISO_API_URL", "http://example.com")
    monkeypatch.setenv("VISO_API_KEY", "123")
    monkeypatch.setenv("GROUP_OWNER", "group_owner")


@pytest.fixture
def mocked_viso():
    return VisoAPI(base_url="http://example.com", api_key="123")


@pytest.fixture
def mock_tenants():
    return [
        {"lcaas_id": "tenant1", "status": "running", "stop_status": "stopped"},
        {"lcaas_id": "tenant2", "status": "running", "stop_status": "started"},
    ]


@patch.object(VisoAPI, "get_all_tenants")
def test_start_stop_mechanism_success(mock_get_all_tenants, mocked_viso, mock_tenants, mocker):
    """
    Given:
        - Two tenants which are running, one its stop_status is 'stopped' and the second is 'started'
    When:
        - Executing start_stop_mechanism on these two tenants with the 'stop' action
    Then:
        - Ensure result contains 2 reports for the 2 tenants with success=True
        (we should get a list which contains 2 reports with success:
         1. since tenant1 is ready from the beginning and no action is needed.
         2. tenant2 is success too, since it was sent to execution stop action, and we mocked its result as success)
    """

    from Utils.start_stop_mechanism import TenantReport

    mock_get_all_tenants.return_value = mock_tenants

    report_1 = [TenantReport(lcaas_id="tenant1", status="running", stop_status="stopped", success=True)]
    report_2 = [TenantReport(lcaas_id="tenant2", status="running", stop_status="stopped", success=True)]
    mocker.patch("Utils.start_stop_mechanism.start_stop_machines", return_value=report_2)

    from Utils.start_stop_mechanism import start_stop_mechanism

    result = start_stop_mechanism(tenants_id={"tenant1", "tenant2"}, action="stop")

    assert result == report_2 + report_1


@patch.object(VisoAPI, "get_all_tenants")
def test_start_stop_mechanism_no_tenants(mock_get_all_tenants, mocked_viso, caplog):
    """
    Given:
        - no tenants
    When:
        - Executing start_stop_mechanism with the 'stop' action
    Then:
        - Ensure result is an empty list
        - Ensure the logs as expected and informative (since no tenants are retrieved)
    """
    mock_get_all_tenants.return_value = []

    from Utils.start_stop_mechanism import start_stop_mechanism

    with caplog.at_level(logging.INFO):
        result = start_stop_mechanism(tenants_id={"tenant1"}, action="stop")

    logs = caplog.text.split("\n")
    assert result == []
    assert "No relevant tenants were found to execute the action='stop' on." in logs[0]


@patch.object(VisoAPI, "get_all_tenants")
def test_start_stop_mechanism_sanity_check(mock_get_all_tenants, mocked_viso, caplog):
    """
    Given:
        - A single tenant which is running and its stop_status is stopped
    When:
        - Executing start_stop_mechanism on this single tenant with the 'stop' action
    Then:
        - Ensure result contains one report for this tenant with success=True
        - Ensure the logs as expected and informative (since the tenant is already ready an no action is needed)
    """
    mock_get_all_tenants.return_value = [{"lcaas_id": "tenant1", "status": "running", "stop_status": "stopped"}]

    # Now call the function
    from Utils.start_stop_mechanism import TenantReport, start_stop_mechanism

    with caplog.at_level(logging.INFO):
        result = start_stop_mechanism(tenants_id={"tenant1"}, action="stop")

    expected_result = [TenantReport(lcaas_id="tenant1", status="running", stop_status="stopped", success=True)]
    logs = caplog.text.split("\n")
    assert len(result) == 1
    assert result == expected_result
    assert (
        "Tenant's details: status = running and stop_status = stopped, and the given action is stop."
        " Nothing needs to be done in this case." in logs[0]
    )
    assert "No relevant tenants were found to execute the action='stop' on." in logs[1]
