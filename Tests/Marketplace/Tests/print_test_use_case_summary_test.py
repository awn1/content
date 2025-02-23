from pathlib import Path

from Tests.Marketplace.print_test_use_case_summary import print_test_use_case_summary
from Tests.scripts.collect_tests.constants import TEST_USE_CASE_TO_JIRA_MAPPING


class MockJiraServer:
    def __init__(self, server_url, verify_ssl):
        self.server_url = server_url
        self.verify_ssl = verify_ssl


def test_print_test_use_case_summary_without_jira(mocker):
    """

    Given: test use case results
    When: running test use case in build
    Then: Validate the correct behaviour regarding Jira.

    """
    artifacts_path = Path("Tests/Marketplace/Tests/test_data")
    build_number = "123"
    without_jira = True

    # Patch the necessary functions and objects
    mock_get_test_results_files = mocker.patch(
        "Tests.Marketplace.print_test_use_case_summary.get_test_results_files",
        return_value=["/path/to/test_use_case_results_file"],
    )
    mock_get_jira_server_info = mocker.patch(
        "Tests.Marketplace.print_test_use_case_summary.get_jira_server_info",
        return_value=MockJiraServer(server_url="https://your_jira_server_url", verify_ssl=False),
    )
    mock_get_jira_ticket_info = mocker.patch(
        "Tests.Marketplace.print_test_use_case_summary.get_jira_ticket_info",
        return_value={
            "project_id": "your_project_id",
            "issue_type": "your_issue_type",
            "component": "your_component",
            "labels": ["label1", "label2"],
        },
    )
    mock_jira_search_all_by_query = mocker.patch("Tests.Marketplace.print_test_use_case_summary.jira_search_all_by_query")
    mock_write_test_to_jira_mapping = mocker.patch("Tests.Marketplace.print_test_use_case_summary.write_test_to_jira_mapping")
    mock_calculate_test_results = mocker.patch(
        "Tests.Marketplace.print_test_use_case_summary.calculate_test_results",
        return_value=(["test_use_case1", "test_use_case2"], ["JIRA-123", "JIRA-456"], []),
    )
    mock_calculate_results_table = mocker.patch(
        "Tests.Marketplace.print_test_use_case_summary.calculate_results_table",
        return_value=("mocked_column_align", "mocked_data", "mocked_xml", 0),
    )
    mocker.patch("Tests.Marketplace.print_test_use_case_summary.tabulate")
    mocker.patch("Tests.Marketplace.print_test_use_case_summary.logging")

    # Call the function to be tested
    result = print_test_use_case_summary(artifacts_path, without_jira, build_number)

    assert not result
    mock_get_test_results_files.assert_called_with(artifacts_path, "test_use_case_report.xml")
    mock_get_jira_server_info.assert_called_once()
    mock_get_jira_ticket_info.assert_not_called()
    mock_jira_search_all_by_query.assert_not_called()
    mock_write_test_to_jira_mapping.assert_called_once_with(
        "https://your_jira_server_url", artifacts_path, ["JIRA-123", "JIRA-456"], TEST_USE_CASE_TO_JIRA_MAPPING
    )
    mock_calculate_test_results.assert_called_with(["/path/to/test_use_case_results_file"], None)
    mock_calculate_results_table.assert_called_with(
        ["JIRA-123", "JIRA-456"], ["test_use_case1", "test_use_case2"], [], ["Test Use Case"], without_jira=True
    )
