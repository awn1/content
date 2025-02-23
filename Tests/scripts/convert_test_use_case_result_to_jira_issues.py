import argparse
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

import urllib3
from jira import JIRA
from junitparser import JUnitXml, TestSuite
from tabulate import tabulate

from Tests.configure_and_test_integration_instances import get_custom_user_agent
from Tests.scripts.collect_tests.constants import (
    TEST_USE_CASE_BASE_HEADERS,
    TEST_USE_CASE_TO_JIRA_MAPPING,
    TEST_USE_CASE_TO_JIRA_TICKETS_CONVERTED,
)
from Tests.scripts.common import (
    TEST_SUITE_CELL_EXPLANATION,
    TEST_USE_CASE_REPORT_FILE_NAME,
    calculate_results_table,
    get_all_failed_results,
    get_properties_for_test_suite,
    get_test_results_files,
)
from Tests.scripts.generic_test_report import (
    calculate_test_results,
    create_jira_issue_for_test,
    get_summary_for_test,
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
JIRA_MAX_DAYS_TO_REOPEN_DEFAULT = 30
JIRA_MAX_DAYS_TO_REOPEN = (
    os.environ.get("JIRA_MAX_DAYS_TO_REOPEN", JIRA_MAX_DAYS_TO_REOPEN_DEFAULT) or JIRA_MAX_DAYS_TO_REOPEN_DEFAULT
)
JIRA_MAX_TEST_USE_CASE_FAILURES_TO_HANDLE_DEFAULT = 20
JIRA_MAX_TEST_USE_CASE_FAILURES_TO_HANDLE = (
    os.environ.get("JIRA_MAX_TEST_USE_CASE_FAILURES_TO_HANDLE", JIRA_MAX_TEST_USE_CASE_FAILURES_TO_HANDLE_DEFAULT)
    or JIRA_MAX_TEST_USE_CASE_FAILURES_TO_HANDLE_DEFAULT
)


def options_handler() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Converts test use case report to Jira issues")
    parser.add_argument("-a", "--artifacts-path", help="Artifacts path", required=True)
    parser.add_argument("--build-number", help="CI job number where the instances were created", required=True)
    parser.add_argument(
        "-d",
        "--max-days-to-reopen",
        default=JIRA_MAX_DAYS_TO_REOPEN,
        type=int,
        required=False,
        help="The max days to reopen a closed issue",
    )
    parser.add_argument(
        "-f",
        "--max-failures-to-handle",
        default=JIRA_MAX_TEST_USE_CASE_FAILURES_TO_HANDLE,
        type=int,
        required=False,
        help="The max days to reopen a closed issue",
    )
    return parser.parse_args()


def main():
    try:
        install_logging("convert_test_use_case_result_to_jira_issues.log", logger=logging)
        now = datetime.now(tz=timezone.utc)
        options = options_handler()
        artifacts_path = Path(options.artifacts_path)
        jira_server_info = get_jira_server_info()
        jira_ticket_info = get_jira_ticket_info()
        logging.info("Converting test use case report to Jira issues with the following settings:")
        logging.info(f"\tArtifacts path: {artifacts_path}")
        logging.info(f"\tJira server url: {jira_server_info.server_url}")
        logging.info(f"\tJira verify SSL: {jira_server_info.verify_ssl}")
        logging.info(f"\tJira project id: {jira_ticket_info.project_id}")
        logging.info(f"\tJira issue type: {jira_ticket_info.issue_type}")
        logging.info(f"\tJira component: {jira_ticket_info.component}")
        logging.info(f"\tJira labels: {', '.join(jira_ticket_info.labels)}")
        logging.info(f"\tJira issue unresolved transition name: {jira_ticket_info.issue_unresolved_transition_name}")
        logging.info(f"\tMax days to reopen: {options.max_days_to_reopen}")

        jira_server = JIRA(
            jira_server_info.server_url,
            token_auth=jira_server_info.api_key,
            options={
                "verify": jira_server_info.verify_ssl,
                "headers": {"User-Agent": get_custom_user_agent(options.build_number)},
            },
        )
        jira_server_info = jira_server_information(jira_server)
        server_url = jira_server_info["baseUrl"]
        if not (test_use_case_results_files := get_test_results_files(artifacts_path, TEST_USE_CASE_REPORT_FILE_NAME)):
            logging.critical(f"Could not find any test use case result files in {artifacts_path}")
            sys.exit(1)

        logging.info(f"Found {len(test_use_case_results_files)} test use case files")

        issues = jira_search_all_by_query(jira_server, generate_query_by_component_and_issue_type(jira_ticket_info))

        use_case_to_test_suite, jira_ticket_for_use_case, server_versions = calculate_test_results(
            test_use_case_results_files, issues
        )

        logging.debug(
            f"Found {len(jira_ticket_for_use_case)} Jira tickets out " f"of {len(use_case_to_test_suite)}" f" test use case"
        )

        # Search if we have too many test use cases that failed beyond the max allowed limit to open, if so we print the
        # list and exit. This is to avoid opening too many Jira issues.
        failed_use_case_tests = get_all_failed_results(use_case_to_test_suite)

        if len(failed_use_case_tests) >= options.max_failures_to_handle:
            column_align, tabulate_data, _, _ = calculate_results_table(
                jira_ticket_for_use_case, failed_use_case_tests, server_versions, TEST_USE_CASE_BASE_HEADERS
            )
            table = tabulate(tabulate_data, headers="firstrow", tablefmt="pretty", colalign=column_align)
            logging.info(f"Test Use Case Results: {TEST_SUITE_CELL_EXPLANATION}\n{table}")
            logging.critical(
                f"Found {len(failed_use_case_tests)} failed use cases, "
                f"which is more than the max allowed limit of {options.max_failures_to_handle} to handle."
            )

            sys.exit(1)

        for result_file in test_use_case_results_files.values():
            xml = JUnitXml.fromfile(result_file.as_posix())
            for test_suite in xml.iterchildren(TestSuite):
                if issue := create_jira_issue_for_test(
                    jira_ticket_info, jira_server, test_suite, options.max_days_to_reopen, now
                ):
                    # if the ticket was created/updated successfully, we add it to the mapping and override the previous ticket.
                    properties = get_properties_for_test_suite(test_suite)
                    if summary := get_summary_for_test(properties):
                        jira_ticket_for_use_case[summary] = issue

        write_test_to_jira_mapping(server_url, artifacts_path, jira_ticket_for_use_case, TEST_USE_CASE_TO_JIRA_MAPPING)
        open(artifacts_path / TEST_USE_CASE_TO_JIRA_TICKETS_CONVERTED, "w")

        logging.info("Finished creating/updating Jira issues for test use case")

    except Exception as e:
        logging.exception(f"Failed to create jira issues from JUnit results: {e}")
        logging.error(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()
