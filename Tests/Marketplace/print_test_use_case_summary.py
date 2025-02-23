import argparse
import sys
import traceback
from pathlib import Path

import urllib3
from jira import JIRA
from tabulate import tabulate

from Tests.configure_and_test_integration_instances import get_custom_user_agent
from Tests.scripts.collect_tests.constants import TEST_USE_CASE_BASE_HEADERS, TEST_USE_CASE_TO_JIRA_MAPPING
from Tests.scripts.common import (
    TEST_SUITE_CELL_EXPLANATION,
    TEST_USE_CASE_REPORT_FILE_NAME,
    calculate_results_table,
    get_test_results_files,
)
from Tests.scripts.generic_test_report import (
    calculate_test_results,
    write_test_to_jira_mapping,
)
from Tests.scripts.jira_issues import (
    generate_query_by_component_and_issue_type,
    get_jira_server_info,
    get_jira_ticket_info,
    jira_search_all_by_query,
    jira_server_information,
)
from Tests.scripts.utils import logging_wrapper as logging
from Tests.scripts.utils.log_util import install_logging

urllib3.disable_warnings()  # Disable insecure warnings


def options_handler() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Utility for printing the test use case summary")
    parser.add_argument("--artifacts-path", help="Path to the artifacts directory", required=True)
    parser.add_argument("--build-number", help="CI job number where the instances were created", required=True)
    parser.add_argument("--without-jira", help="Print the summary without Jira tickets", action="store_true")
    return parser.parse_args()


def print_test_use_case_summary(artifacts_path: Path, without_jira: bool, build_number: str) -> bool:
    logging.info(f"Printing test use case summary - artifacts path: {artifacts_path}")
    # iterate over the artifacts path and find all the test use case result files
    if not (test_use_case_results_files := get_test_results_files(artifacts_path, TEST_USE_CASE_REPORT_FILE_NAME)):
        logging.error(f"Could not find any test use case result files in {artifacts_path}")
        return True

    logging.info(f"Found {len(test_use_case_results_files)} test use case files")
    jira_server_info = get_jira_server_info()
    if without_jira:
        logging.info("Printing test use case summary without Jira tickets")
        issues = None
        server_url = jira_server_info.server_url
    else:
        jira_ticket_info = get_jira_ticket_info()
        logging.info("Searching for Jira tickets for test use case with the following settings:")
        logging.info(f"\tJira server url: {jira_server_info.server_url}")
        logging.info(f"\tJira verify SSL: {jira_server_info.verify_ssl}")
        logging.info(f"\tJira project id: {jira_ticket_info.project_id}")
        logging.info(f"\tJira issue type: {jira_ticket_info.issue_type}")
        logging.info(f"\tJira component: {jira_ticket_info.component}")
        logging.info(f"\tJira labels: {', '.join(jira_ticket_info.labels)}")

        jira_server = JIRA(
            jira_server_info.server_url,
            token_auth=jira_server_info.api_key,
            options={
                "verify": jira_server_info.verify_ssl,
                "headers": {"User-Agent": get_custom_user_agent(build_number)},
            },
        )
        jira_server_info = jira_server_information(jira_server)
        server_url = jira_server_info["baseUrl"]

        issues = jira_search_all_by_query(jira_server, generate_query_by_component_and_issue_type(jira_ticket_info))

    use_cases_to_test_suite, jira_tickets_for_test_use_cases, server_versions = calculate_test_results(
        test_use_case_results_files, issues
    )

    write_test_to_jira_mapping(server_url, artifacts_path, jira_tickets_for_test_use_cases, TEST_USE_CASE_TO_JIRA_MAPPING)

    if use_cases_to_test_suite:
        logging.info(
            f"Found {len(jira_tickets_for_test_use_cases)} Jira tickets out of {len(use_cases_to_test_suite)} " "Test Use Cases"
        )

        column_align, tabulate_data, xml, total_errors = calculate_results_table(
            jira_tickets_for_test_use_cases,
            use_cases_to_test_suite,
            server_versions,
            TEST_USE_CASE_BASE_HEADERS,
            without_jira=without_jira,
        )

        table = tabulate(tabulate_data, headers="firstrow", tablefmt="pretty", colalign=column_align)
        logging.info(f"Test Use Case Results: {TEST_SUITE_CELL_EXPLANATION}\n{table}")
        return total_errors != 0

    logging.info("Test Use Case Results - No test use case results found")
    return False


def main():
    try:
        install_logging("print_test_use_case_summary.log", logger=logging)
        options = options_handler()
        artifacts_path = Path(options.artifacts_path)
        logging.info(f"Printing test use case summary - artifacts path: {artifacts_path}")

        if print_test_use_case_summary(artifacts_path, options.without_jira, options.build_number):
            logging.critical("test use case summary found errors")
            sys.exit(1)

        logging.info("Test use case summary finished successfully")
    except Exception as e:
        logging.error(f"Failed to get the test use case summary: {e}")
        logging.error(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()
