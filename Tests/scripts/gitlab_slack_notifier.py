import argparse
import contextlib
import json
import logging
import math
import os
import sys
import tempfile
import zipfile
from collections.abc import Iterable
from datetime import datetime, timedelta
from distutils.util import strtobool
from pathlib import Path
from typing import Any

import requests
from gitlab import GitlabGetError
from gitlab.client import Gitlab
from gitlab.v4.objects import ProjectPipeline, ProjectPipelineJob
from junitparser import JUnitXml, TestSuite
from slack_sdk import WebClient

from Tests.Marketplace.marketplace_constants import BucketUploadFlow
from Tests.scripts.common import (
    BUCKET_UPLOAD,
    BUCKET_UPLOAD_BRANCH_SUFFIX,
    CONTENT_DOCS_NIGHTLY,
    CONTENT_DOCS_PR,
    CONTENT_MERGE,
    CONTENT_NIGHTLY,
    CONTENT_PR,
    DOCKERFILES_PR,
    TEST_MODELING_RULES_REPORT_FILE_NAME,
    TEST_PLAYBOOKS_REPORT_FILE_NAME,
    get_instance_directories,
    get_properties_for_test_suite,
    get_slack_user_name,
    get_test_results_files,
    join_list_by_delimiter_in_chunks,
    replace_escape_characters,
    slack_link,
)
from Tests.scripts.github_client import GithubPullRequest
from Tests.scripts.test_modeling_rule_report import (
    TEST_MODELING_RULES_TO_JIRA_TICKETS_CONVERTED,
    calculate_test_modeling_rule_results,
    get_summary_for_test_modeling_rule,
    read_test_modeling_rule_to_jira_mapping,
)
from Tests.scripts.test_playbooks_report import TEST_PLAYBOOKS_TO_JIRA_TICKETS_CONVERTED, read_test_playbook_to_jira_mapping
from Tests.scripts.utils.log_util import install_logging

ROOT_ARTIFACTS_FOLDER = Path(os.getenv("ARTIFACTS_FOLDER", "./artifacts"))
ARTIFACTS_FOLDER_XSOAR = ROOT_ARTIFACTS_FOLDER / "xsoar"
ARTIFACTS_FOLDER_XSIAM = ROOT_ARTIFACTS_FOLDER / "marketplacev2"
ARTIFACTS_FOLDER_XPANSE = ROOT_ARTIFACTS_FOLDER / "xpanse"
ARTIFACTS_FOLDER_XSOAR_SERVER_TYPE = ARTIFACTS_FOLDER_XSOAR / "server_type_XSOAR"
ARTIFACTS_FOLDER_XSOAR_SAAS_SERVER_TYPE = ARTIFACTS_FOLDER_XSOAR / "server_type_XSOAR SAAS"
ARTIFACTS_FOLDER_XPANSE_SERVER_TYPE = ARTIFACTS_FOLDER_XPANSE / "server_type_XPANSE"
ARTIFACTS_FOLDER_XSIAM_SERVER_TYPE = ARTIFACTS_FOLDER_XSIAM / "server_type_XSIAM"
LOCKED_MACHINES_LIST_FILE_NAME = "locked_machines_list.txt"
GITLAB_SERVER_URL = os.getenv("CI_SERVER_URL", "https://gitlab.xdr.pan.local")  # disable-secrets-detection
GITLAB_PROJECT_ID = os.getenv("CI_PROJECT_ID") or 1061
GITLAB_SSL_VERIFY = bool(strtobool(os.getenv("GITLAB_SSL_VERIFY", "true")))
CONTENT_CHANNEL = "dmst-build-test"
XDR_CONTENT_SYNC_CHANNEL_ID = os.getenv("XDR_CONTENT_SYNC_CHANNEL_ID", "")
SLACK_USERNAME = "Content GitlabCI"
SLACK_WORKSPACE_NAME = os.getenv("SLACK_WORKSPACE_NAME", "")
REPOSITORY_NAME = os.getenv("REPOSITORY_NAME", "demisto/content")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
CI_COMMIT_BRANCH = os.getenv("CI_COMMIT_BRANCH", "")
CI_COMMIT_SHA = os.getenv("CI_COMMIT_SHA", "")
CI_SERVER_HOST = os.getenv("CI_SERVER_HOST", "")
DEFAULT_BRANCH = "master"
SLACK_NOTIFY = "slack-notify"
ALL_FAILURES_WERE_CONVERTED_TO_JIRA_TICKETS = " (All failures were converted to Jira tickets)"
UPLOAD_BUCKETS = [
    (ARTIFACTS_FOLDER_XSOAR_SERVER_TYPE, "XSOAR"),
    (ARTIFACTS_FOLDER_XSOAR_SAAS_SERVER_TYPE, "XSOAR SAAS"),
    (ARTIFACTS_FOLDER_XSIAM_SERVER_TYPE, "XSIAM"),
    (ARTIFACTS_FOLDER_XPANSE_SERVER_TYPE, "XPANSE"),
]
TEST_UPLOAD_FLOW_PIPELINE_ID = "test_upload_flow_pipeline_id.txt"
SLACK_MESSAGE = "slack_message.json"
SLACK_MESSAGE_THREADS = "slack_message_threads.json"
SLACK_MESSAGE_CHANNEL_TO_THREAD = "slack_message_channel_to_thread.json"
OLD_SLACK_MESSAGE = "slack_msg.json"
OLD_SLACK_MESSAGE_THREADS = "threaded_messages.json"
OLD_SLACK_MESSAGE_CHANNEL_TO_THREAD = "channel_to_thread.json"
DAYS_TO_SEARCH = 30
ALLOWED_COVERAGE_PROXIMITY = 0.25  # Percentage threshold for allowed coverage proximity.


def options_handler() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Parser for slack_notifier args")
    parser.add_argument("-n", "--name-mapping_path", help="Path to name mapping file.", required=True)
    parser.add_argument("-r", "--repository", help="The repository name", default=REPOSITORY_NAME)
    parser.add_argument("-u", "--url", help="The gitlab server url", default=GITLAB_SERVER_URL)
    parser.add_argument("-p", "--pipeline_id", help="The pipeline id to check the status of", required=True)
    parser.add_argument("-s", "--slack_token", help="The token for slack", required=True)
    parser.add_argument("-c", "--ci_token", help="The token for circleci/gitlab", required=True)
    parser.add_argument(
        "-ch", "--slack_channel", help="The slack channel in which to send the notification", default=CONTENT_CHANNEL
    )
    parser.add_argument("-gp", "--gitlab_project_id", help="The gitlab project id", default=GITLAB_PROJECT_ID)
    parser.add_argument("-tw", "--triggering-workflow", help="The type of ci pipeline workflow the notifier is reporting on")
    parser.add_argument(
        "-a", "--allow-failure", help="Allow posting message to fail in case the channel doesn't exist", required=True
    )
    parser.add_argument("--github-token", required=False, help="A GitHub API token", default=GITHUB_TOKEN)
    parser.add_argument("--current-sha", required=False, help="Current branch commit SHA", default=CI_COMMIT_SHA)
    parser.add_argument("--current-branch", required=False, help="Current branch name", default=CI_COMMIT_BRANCH)
    parser.add_argument("-f", "--file", help="File path with the text to send")
    parser.add_argument("-t", "--attachments", help="File path with the attachments to send", required=False)
    parser.add_argument("-th", "--thread", help="A message to be sent as a thread", required=False)
    parser.add_argument("-dr", "--dry_run", help="true for a dry run pipeline, false for a prod pipeline", default="false")
    return parser.parse_args()


def get_artifact_data(artifact_folder: Path, artifact_relative_path: str) -> str | None:
    """
    Retrieves artifact data according to the artifact relative path from 'ARTIFACTS_FOLDER' given.
    Args:
        artifact_folder (Path): Full path of the artifact root folder.
        artifact_relative_path (str): Relative path of an artifact file.

    Returns:
        (Optional[str]): data of the artifact as str if exists, None otherwise.
    """
    file_name = artifact_folder / artifact_relative_path
    try:
        if file_name.exists():
            logging.info(f"Extracting {file_name}")
            return file_name.read_text()
        else:
            logging.info(f"Did not find {file_name} file")
    except Exception:
        logging.exception(f"Error getting {file_name} file")
    return None


def get_test_report_pipeline_url(pipeline_url: str) -> str:
    return f"{pipeline_url}/test_report"


def get_msg_machines(failed_jobs: dict, job_cause_fail: set[str], job_cause_warning: set[str], msg: str):
    if job_cause_fail.intersection(set(failed_jobs)):
        color = "danger"
    elif job_cause_warning.intersection(set(failed_jobs)):
        color = "warning"
    else:
        color = "good"

    return [
        {
            "fallback": msg,
            "color": color,
            "title": msg,
        }
    ]


def machines_saas_and_xsiam(failed_jobs):
    lock_xsoar_machine_raw_txt = split_results_file(
        get_artifact_data(ARTIFACTS_FOLDER_XSOAR, LOCKED_MACHINES_LIST_FILE_NAME), ","
    )
    lock_xsiam_machine_raw_txt = split_results_file(
        get_artifact_data(ARTIFACTS_FOLDER_XSIAM, LOCKED_MACHINES_LIST_FILE_NAME), ","
    )
    machines = []

    if lock_xsoar_machine_raw_txt:
        machines.extend(
            get_msg_machines(
                failed_jobs,
                {"xsoar_ng_server_ga"},
                {"xsoar-test_playbooks_results"},
                f"XSOAR SAAS:\n{','.join(lock_xsoar_machine_raw_txt)}",
            )
        )

    if lock_xsiam_machine_raw_txt:
        machines.extend(
            get_msg_machines(
                failed_jobs,
                {"xsiam_server_ga", "install-packs-in-xsiam-ga", "install-packs-in-xsoar-ng-ga"},
                {"xsiam-test_playbooks_results", "xsiam-test_modeling_rule_results"},
                f"XSIAM:\n{','.join(lock_xsiam_machine_raw_txt)}",
            )
        )

    if not machines:
        return machines
    return (
        get_msg_machines(
            failed_jobs,
            {
                "xsoar_ng_server_ga",
                "xsiam_server_ga",
                "install-packs-in-xsiam-ga",
                "install-packs-in-xsoar-ng-ga",
            },
            {
                "xsoar-test_playbooks_results",
                "xsiam-test_playbooks_results",
                "xsiam-test_modeling_rule_results",
            },
            f"Used {len(machines)} machine types",
        )
        + machines
    )


def test_modeling_rules_results(artifact_folder: Path, pipeline_url: str, title: str) -> tuple[list[dict[str, Any]], bool]:
    if not (test_modeling_rules_results_files := get_test_results_files(artifact_folder, TEST_MODELING_RULES_REPORT_FILE_NAME)):
        logging.error(f"Could not find any test modeling rule result files in {artifact_folder}")
        title = f"{title} - Failed to get Test Modeling rules results"
        return [
            {
                "fallback": title,
                "color": "warning",
                "title": title,
            }
        ], True

    failed_test_to_jira_mapping = read_test_modeling_rule_to_jira_mapping(artifact_folder)

    modeling_rules_to_test_suite, _, _ = calculate_test_modeling_rule_results(test_modeling_rules_results_files)

    if not modeling_rules_to_test_suite:
        logging.info("Test Modeling rules - No test modeling rule results found for this build")
        title = f"{title} - Test Modeling rules - No test modeling rule results found for this build"
        return [
            {
                "fallback": title,
                "color": "good",
                "title": title,
            }
        ], False

    failed_test_suites_tuples = []
    total_test_suites = 0
    for test_suites in modeling_rules_to_test_suite.values():
        for test_suite in test_suites.values():
            total_test_suites += 1
            if test_suite.failures or test_suite.errors:
                properties = get_properties_for_test_suite(test_suite)
                if modeling_rule := get_summary_for_test_modeling_rule(properties):
                    failed_test_suites_tuples.append(
                        failed_test_data_to_slack_link(modeling_rule, failed_test_to_jira_mapping.get(modeling_rule))
                    )

    if failed_test_suites_tuples:
        if (artifact_folder / TEST_MODELING_RULES_TO_JIRA_TICKETS_CONVERTED).exists():
            title_suffix = ALL_FAILURES_WERE_CONVERTED_TO_JIRA_TICKETS
            color = "warning"
        else:
            title_suffix = ""
            color = "danger"
        failed_test_suites = map(lambda x: x[1], sorted(failed_test_suites_tuples, key=lambda x: (x[0], x[1])))
        title = (
            f"{title} - Failed Tests Modeling rules - Passed:{total_test_suites - len(failed_test_suites_tuples)}, "
            f"Failed:{len(failed_test_suites_tuples)}"
        )

        return [
            {
                "fallback": title,
                "color": color,
                "title": title,
                "title_link": get_test_report_pipeline_url(pipeline_url),
                "fields": [
                    {
                        "title": f"Failed Tests Modeling rules{title_suffix if i == 0 else ' - Continued'}",
                        "value": chunk,
                        "short": False,
                    }
                    for i, chunk in enumerate(join_list_by_delimiter_in_chunks(failed_test_suites))
                ],
            }
        ], True

    title = f"{title} - All Test Modeling rules Passed - ({total_test_suites})"
    return [
        {
            "fallback": title,
            "color": "good",
            "title": title,
            "title_link": get_test_report_pipeline_url(pipeline_url),
        }
    ], False


def failed_test_data_to_slack_link(failed_test: str, jira_ticket_data: dict[str, str] | None) -> tuple[bool, str]:
    if jira_ticket_data:
        return True, slack_link(jira_ticket_data["url"], f"{failed_test} [{jira_ticket_data['key']}]")
    return False, failed_test


def test_playbooks_results_to_slack_msg(
    instance_role: str,
    succeeded_tests: set[str],
    failed_tests: set[str],
    skipped_integrations: set[str],
    skipped_tests: set[str],
    playbook_to_jira_mapping: dict[str, Any],
    test_playbook_tickets_converted: bool,
    title: str,
    pipeline_url: str,
) -> tuple[list[dict[str, Any]], bool]:
    if failed_tests:
        title = (
            f"{title} ({instance_role}) - Test Playbooks - Passed:{len(succeeded_tests)}, Failed:{len(failed_tests)}, "
            f"Skipped - {len(skipped_tests)}, Skipped Integrations - {len(skipped_integrations)}"
        )
        if test_playbook_tickets_converted:
            title_suffix = ALL_FAILURES_WERE_CONVERTED_TO_JIRA_TICKETS
            color = "warning"
        else:
            title_suffix = ""
            color = "danger"

        failed_playbooks: Iterable[str] = map(
            lambda x: x[1],
            sorted(
                [
                    failed_test_data_to_slack_link(playbook_id, playbook_to_jira_mapping.get(playbook_id))
                    for playbook_id in failed_tests
                ],
                key=lambda x: (x[0], x[1]),
            ),
        )
        return [
            {
                "fallback": title,
                "color": color,
                "title": title,
                "title_link": get_test_report_pipeline_url(pipeline_url),
                "mrkdwn_in": ["fields"],
                "fields": [
                    {
                        "title": f"Failed Test Playbooks{title_suffix}",
                        "value": chunk,
                        "short": False,
                    }
                    for i, chunk in enumerate(join_list_by_delimiter_in_chunks(failed_playbooks))
                ],
            }
        ], True
    title = (
        f"{title} ({instance_role}) - All Tests Playbooks Passed - Passed:{len(succeeded_tests)}, "
        f"Skipped - {len(skipped_tests)}, Skipped Integrations - {len(skipped_integrations)})"
    )
    return [
        {
            "fallback": title,
            "color": "good",
            "title": title,
            "title_link": get_test_report_pipeline_url(pipeline_url),
        }
    ], False


def split_results_file(tests_data: str | None, delim: str = "\n") -> list[str]:
    return list(filter(None, tests_data.split(delim))) if tests_data else []


def get_playbook_tests_data(artifact_folder: Path) -> tuple[set[str], set[str], set[str], set[str]]:
    succeeded_tests = set()
    failed_tests = set()
    skipped_tests = set()
    skipped_integrations = set(split_results_file(get_artifact_data(artifact_folder, "skipped_integrations.txt")))
    xml = JUnitXml.fromfile(str(artifact_folder / TEST_PLAYBOOKS_REPORT_FILE_NAME))
    for test_suite in xml.iterchildren(TestSuite):
        properties = get_properties_for_test_suite(test_suite)
        if playbook_id := properties.get("playbook_id"):
            if test_suite.failures or test_suite.errors:
                failed_tests.add(playbook_id)
            elif test_suite.skipped:
                skipped_tests.add(playbook_id)
            else:
                succeeded_tests.add(playbook_id)

    return succeeded_tests, failed_tests, skipped_tests, skipped_integrations


def test_playbooks_results(artifact_folder: Path, pipeline_url: str, title: str) -> tuple[list[dict[str, Any]], bool]:
    test_playbook_to_jira_mapping = read_test_playbook_to_jira_mapping(artifact_folder)
    test_playbook_tickets_converted = (artifact_folder / TEST_PLAYBOOKS_TO_JIRA_TICKETS_CONVERTED).exists()
    has_failed_tests = False
    test_playbook_slack_msg = []
    for instance_role, instance_directory in get_instance_directories(artifact_folder).items():
        try:
            succeeded_tests, failed_tests, skipped_tests, skipped_integrations = get_playbook_tests_data(instance_directory)
            if succeeded_tests or failed_tests:  # Handling case where no playbooks had run
                instance_slack_msg, instance_has_failed_tests = test_playbooks_results_to_slack_msg(
                    instance_role,
                    succeeded_tests,
                    failed_tests,
                    skipped_integrations,
                    skipped_tests,
                    test_playbook_to_jira_mapping,
                    test_playbook_tickets_converted,
                    title,
                    pipeline_url,
                )
                test_playbook_slack_msg += instance_slack_msg
                has_failed_tests |= instance_has_failed_tests
        except Exception:
            logging.exception(f"Failed to get test playbook results for {instance_role}")
            has_failed_tests = True
            test_playbook_slack_msg.append(
                {
                    "fallback": f"{title} - Failed to get Test Playbooks results for {instance_role}",
                    "title": f"{title} - Failed to get Test Playbooks results for {instance_role}",
                    "color": "danger",
                }
            )

    return test_playbook_slack_msg, has_failed_tests


def bucket_sync_msg_builder(artifact_path: Path) -> tuple[list, list]:
    bucket_sync_results = get_artifact_data(
        artifact_folder=artifact_path / "logs",
        artifact_relative_path="trigger_sync_all_buckets_status_code.log",
    )

    if not bucket_sync_results:
        logging.error("The Sync all buckets job was not triggered for any reason, file for status_code not found")
        title = "The Sync all buckets job was not triggered for any reason"
        return [], [
            {
                "fallback": title,
                "title": title,
                "color": "danger",
            }
        ]

    if bucket_sync_results == "skipped":
        # In case the run is `test-upload-flow`
        logging.debug("Skipping `Sync all buckets` msg in test upload-flow")
        return [], []

    if bucket_sync_results == "201":
        # Triggered successfully
        title = f"Sync all buckets pipeline triggered successfully. Status Code: {bucket_sync_results}"
        field_value = f"Check the {slack_link(XDR_CONTENT_SYNC_CHANNEL_ID, 'xdr-content-sync')} channel for job status updates."
        return [], [
            {
                "fallback": title,
                "title": title,
                "color": "good",
                "fields": [
                    {
                        "title": "",
                        "value": field_value,
                        "short": False,
                    }
                ],
            }
        ]

    # Triggered fail
    title = ":alert: Failed to triggered Sync all buckets pipeline,"
    if bucket_sync_results.startswith("Some Error"):
        # Some error
        title += f" Error: {bucket_sync_results}"
    else:
        # HTTP Error
        title += f" Status Code: {bucket_sync_results}"
    return [
        {
            "fallback": title,
            "title": title,
            "color": "danger",
        }
    ], []


def bucket_upload_results(
    bucket_artifact_folder: Path, marketplace_name: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    # Importing here to avoid importing demisto-sdk.
    from Tests.Marketplace.marketplace_services import get_upload_data  # noqa: E402

    slack_msg_append = []
    threaded_messages = []
    pack_results_path = bucket_artifact_folder / BucketUploadFlow.PACKS_RESULTS_FILE_FOR_SLACK

    logging.info(f'retrieving upload data from "{pack_results_path}"')
    successful_packs, _, failed_packs, _ = get_upload_data(
        pack_results_path.as_posix(), BucketUploadFlow.UPLOAD_PACKS_TO_MARKETPLACE_STORAGE
    )
    if successful_packs:
        slack_msg_append.append(
            {
                "fallback": f"Successfully uploaded {len(successful_packs)} Pack(s) to {marketplace_name}",
                "title": f"Successfully uploaded {len(successful_packs)} Pack(s) to {marketplace_name}",
                "color": "good",
            }
        )
        threaded_messages.append(
            {
                "fallback": f'Successfully uploaded {marketplace_name} Pack(s): '
                f'{", ".join(sorted({*successful_packs},key=lambda s: s.lower()))} to {marketplace_name}',
                "title": f"Successfully uploaded {len(successful_packs)} Pack(s) to {marketplace_name}:",
                "color": "good",
                "fields": [
                    {"title": "", "value": ", ".join(sorted({*successful_packs}, key=lambda s: s.lower())), "short": False}
                ],
            }
        )

    if failed_packs:
        slack_msg_append.append(
            {
                "fallback": f"Failed to upload {len(failed_packs)} Pack(s) to {marketplace_name}",
                "title": f"Failed to upload {len(failed_packs)} Pack(s) to {marketplace_name}",
                "color": "danger",
            }
        )
        threaded_messages.append(
            {
                "fallback": f'Failed to upload {marketplace_name} Pack(s): '
                f'{", ".join(sorted({*failed_packs}, key=lambda s: s.lower()))}',
                "title": f"Failed to upload {len(failed_packs)} Pack(s) to {marketplace_name}:",
                "color": "danger",
                "fields": [{"title": "", "value": ", ".join(sorted({*failed_packs}, key=lambda s: s.lower())), "short": False}],
            }
        )

    return slack_msg_append, threaded_messages


def construct_slack_msg_sync_buckets(threaded_messages, slack_msg_append):
    bucket_sync_failure, bucket_sync_success = bucket_sync_msg_builder(ROOT_ARTIFACTS_FOLDER)
    threaded_messages.extend(bucket_sync_success)
    slack_msg_append.extend(bucket_sync_failure)


def construct_slack_msg(
    triggering_workflow: str,
    pipeline_url: str,
    pipeline_failed_jobs: list[ProjectPipelineJob],
    pull_request: GithubPullRequest | None,
    file: str | None,
    attachments: str | None,
    thread: str | None,
    dry_run: str = "true",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str, list[dict[str, Any]]]:
    # report failing jobs
    content_fields = []

    failed_jobs_names = {job.name: job.web_url for job in pipeline_failed_jobs}
    if failed_jobs_names:
        failed_jobs = [slack_link(url, name) for name, url in sorted(failed_jobs_names.items())]
        content_fields.append(
            {"title": f"Failed Jobs - ({len(failed_jobs_names)})", "value": "\n".join(failed_jobs), "short": False}
        )

    if pull_request:
        content_fields.append(
            {
                "title": "Pull Request",
                "value": slack_link(pull_request.data["html_url"], replace_escape_characters(pull_request.data["title"])),
                "short": False,
            }
        )

    # report failing unit-tests
    triggering_workflow_lower = triggering_workflow.lower()

    # report pack updates
    threaded_messages = []
    slack_msg_append = []

    logging.debug(f"constructing slack msg for {triggering_workflow_lower=} and {dry_run=}")
    try:
        dry_run_bool = bool(strtobool(dry_run))
    except ValueError:
        dry_run_bool = True
    if "upload" in triggering_workflow_lower:
        for bucket in UPLOAD_BUCKETS:
            slack_msg, threaded_message = bucket_upload_results(*bucket)
            threaded_messages.extend(threaded_message)
            slack_msg_append.extend(slack_msg)
        construct_slack_msg_sync_buckets(threaded_messages, slack_msg_append)
    elif triggering_workflow_lower in ["deploy auto upgrade packs", "override corepacks"] and not dry_run_bool:
        construct_slack_msg_sync_buckets(threaded_messages, slack_msg_append)

    has_failed_tests = False
    # report failing test-playbooks and test modeling rules.
    if triggering_workflow in {CONTENT_NIGHTLY, CONTENT_PR, CONTENT_MERGE}:
        test_playbooks_slack_msg_xsoar, test_playbooks_has_failure_xsoar = test_playbooks_results(
            ARTIFACTS_FOLDER_XSOAR, pipeline_url, title="XSOAR"
        )
        test_playbooks_slack_msg_xsiam, test_playbooks_has_failure_xsiam = test_playbooks_results(
            ARTIFACTS_FOLDER_XSIAM, pipeline_url, title="XSIAM"
        )
        test_modeling_rules_slack_msg_xsiam, test_modeling_rules_has_failure_xsiam = test_modeling_rules_results(
            ARTIFACTS_FOLDER_XSIAM, pipeline_url, title="XSIAM"
        )
        slack_msg_append += test_playbooks_slack_msg_xsoar + test_playbooks_slack_msg_xsiam + test_modeling_rules_slack_msg_xsiam
        has_failed_tests |= (
            test_playbooks_has_failure_xsoar or test_playbooks_has_failure_xsiam or test_modeling_rules_has_failure_xsiam
        )
        slack_msg_append += missing_content_packs_test_conf(ARTIFACTS_FOLDER_XSOAR_SERVER_TYPE)
    if triggering_workflow == CONTENT_NIGHTLY:
        # The coverage Slack message is only relevant for nightly and not for PRs.
        slack_msg_append += construct_coverage_slack_msg()

    # Always add the machines used for the tests.
    threaded_messages.extend(machines_saas_and_xsiam(failed_jobs_names))

    title = triggering_workflow

    if file:
        slack_msg_append.extend(read_and_parse(file, f"Failed to read file and parse {file}", slack_msg_append))

    if thread:
        threaded_messages.extend(read_and_parse(thread, f"Failed to read thread file and parse {thread}", slack_msg_append))

    attachments_json = (
        read_and_parse(attachments, f"Failed to read attachments file and parse {attachments}", slack_msg_append)
        if attachments
        else []
    )

    if pull_request:
        pr_number = pull_request.data["number"]
        pr_title = replace_escape_characters(pull_request.data["title"])
        title += f" (PR#{pr_number} - {pr_title})"

    # In case we have failed tests we override the color only in case all the pipeline jobs have passed.
    if has_failed_tests:
        title_append = " [Has Failed Tests]"
        color = "warning"
    else:
        title_append = ""
        color = "good"

    if pipeline_failed_jobs:
        title += " - Failure"
        color = "danger"
    else:
        title += " - Success"
        # No color is needed in case of success, as it's controlled by the color of the test failures' indicator.

    title += title_append
    return (
        [{"fallback": title, "color": color, "title": title, "title_link": pipeline_url, "fields": content_fields}]
        + slack_msg_append,
        threaded_messages,
        title,
        attachments_json,
    )


def read_and_parse(file_path: str, error_title: str, on_error_append_to: list):
    # Read and parse the file, if an error occurs append the error message to the append_to list.
    try:
        return json.loads(Path(file_path).read_text())
    except Exception:
        logging.exception(error_title)
        on_error_append_to.append(
            {
                "fallback": error_title,
                "title": error_title,
                "color": "danger",
            }
        )
    return []


def missing_content_packs_test_conf(artifact_folder: Path) -> list[dict[str, Any]]:
    if missing_packs_list := split_results_file(get_artifact_data(artifact_folder, "missing_content_packs_test_conf.txt")):
        title = f"Notice - Missing packs - ({len(missing_packs_list)})"
        return [
            {
                "fallback": title,
                "color": "warning",
                "title": title,
                "fields": [
                    {
                        "title": "The following packs exist in content-test-conf, but not in content",
                        "value": ", ".join(missing_packs_list),
                        "short": False,
                    }
                ],
            }
        ]
    return []


def collect_pipeline_data(gitlab_client: Gitlab, project_id: str, pipeline_id: str) -> tuple[str, list[ProjectPipelineJob]]:
    project = gitlab_client.projects.get(int(project_id))
    pipeline = project.pipelines.get(int(pipeline_id))

    failed_jobs: list[ProjectPipelineJob] = []
    for job in pipeline.jobs.list(iterator=True):
        logging.info(f"status of gitlab job with id {job.id} and name {job.name} is {job.status}")
        if job.status == "failed":
            logging.info(f"collecting failed job {job.name}")
            logging.info(f'pipeline associated with failed job is {job.pipeline.get("web_url")}')
            failed_jobs.append(job)  # type: ignore[arg-type]

    return pipeline.web_url, failed_jobs


def construct_coverage_slack_msg(sleep_interval: int = 1) -> list[dict[str, Any]]:
    from demisto_sdk.commands.coverage_analyze.tools import get_total_coverage

    coverage_today = get_total_coverage(filename=(ROOT_ARTIFACTS_FOLDER / "coverage_report" / "coverage-min.json").as_posix())
    coverage_yesterday = get_total_coverage(date=datetime.now() - timedelta(days=1))

    # The artifacts are kept for 30 days, so we can get the coverage for the last month.
    # When the coverage file does not exist, we try to import the file from the following day,
    # and the attempt will continue until the day before yesterday.
    for days_ago in range(DAYS_TO_SEARCH, 2, -1):
        if coverage_last_month := get_total_coverage(date=datetime.now() - timedelta(days=days_ago)):
            break
    else:
        coverage_last_month = "no coverage found for last month"

    if isinstance(coverage_last_month, float):  #  The coverage file is found
        coverage_last_month = f"{coverage_last_month:.3f}%"

    color = (
        "good"
        if coverage_today >= coverage_yesterday
        or math.isclose(coverage_today, coverage_yesterday, abs_tol=ALLOWED_COVERAGE_PROXIMITY)
        else "danger"
    )
    title = (
        f"Content code coverage: {coverage_today:.3f}% (Yesterday: {coverage_yesterday:.3f}%, "
        f"Last month: {coverage_last_month})"
    )

    return [
        {
            "fallback": title,
            "color": color,
            "title": title,
        }
    ]


def get_message_p_from_ts(ts):
    return f"p{ts.replace('.', '')}"


def build_link_to_message(channel_id: str, message_ts: str) -> str:
    if SLACK_WORKSPACE_NAME:
        return f"https://{SLACK_WORKSPACE_NAME}.slack.com/archives/{channel_id}/{message_ts}"
    return ""


def channels_to_send_msg(computed_slack_channel):
    if computed_slack_channel in ("dmst-build", CONTENT_CHANNEL):
        return (computed_slack_channel,)
    else:
        return CONTENT_CHANNEL, computed_slack_channel


def write_json_to_file(json_data: Any, file_path: Path) -> None:
    with contextlib.suppress(Exception), open(file_path, "w") as f:
        json.dump(json_data, f, indent=4, sort_keys=True, default=str)
        logging.debug(f"Successfully wrote data to {file_path}")


def get_pipeline_by_id(gitlab_client: Gitlab, project_id: str, pipeline_id: str) -> ProjectPipeline:
    project = gitlab_client.projects.get(int(project_id))
    pipeline = project.pipelines.get(int(pipeline_id))
    return pipeline


def get_slack_downstream_pipeline_id(pipeline: ProjectPipeline):
    for bridge in pipeline.bridges.list(all=True):
        if SLACK_NOTIFY in bridge.name.lower() and bridge.downstream_pipeline:
            pipeline_id = bridge.downstream_pipeline.get("id")
            return pipeline_id
    return None


def get_pipeline_slack_data(gitlab_client: Gitlab, pipeline_id: str, project_id: str) -> tuple[list, list, dict, ProjectPipeline]:
    pipeline = get_pipeline_by_id(gitlab_client, project_id, pipeline_id)
    slack_message = []
    slack_message_threads = []
    slack_message_channel_to_thread = {}
    slack_notify_job = None
    slack_pipeline = None
    if (slack_pipeline_id := get_slack_downstream_pipeline_id(pipeline)) and (
        slack_pipeline := get_pipeline_by_id(gitlab_client, project_id, slack_pipeline_id)
    ):
        for job in slack_pipeline.jobs.list():
            if job.name == SLACK_NOTIFY:
                slack_notify_job = job
                break

    if slack_notify_job and slack_pipeline:
        with tempfile.TemporaryDirectory(dir=ROOT_ARTIFACTS_FOLDER, prefix=SLACK_NOTIFY) as temp_dir:
            artifacts_zip_file = Path(temp_dir) / f"{SLACK_NOTIFY}.zip"
            logging.info(f"Downloading artifacts for slack notify job: {slack_notify_job.id} to file {artifacts_zip_file}")
            gitlab_project = gitlab_client.projects.get(int(slack_pipeline.project_id))
            slack_job_obj = gitlab_project.jobs.get(slack_notify_job.id)
            try:
                with open(artifacts_zip_file, "wb") as f:
                    slack_job_obj.artifacts(streamed=True, action=f.write)
                zip_file = zipfile.ZipFile(artifacts_zip_file)
                temp_zip_dir = Path(temp_dir)
                zip_file.extractall(temp_zip_dir)
                for root, _dirs, files in os.walk(temp_zip_dir, topdown=True):
                    for file in files:
                        if SLACK_MESSAGE in file or OLD_SLACK_MESSAGE in file:
                            slack_message = json.loads((Path(root) / file).read_text())
                        if SLACK_MESSAGE_THREADS in file or OLD_SLACK_MESSAGE_THREADS in file:
                            slack_message_threads = json.loads((Path(root) / file).read_text())
                        if SLACK_MESSAGE_CHANNEL_TO_THREAD in file or OLD_SLACK_MESSAGE_CHANNEL_TO_THREAD in file:
                            slack_message_channel_to_thread = json.loads((Path(root) / file).read_text())
            except GitlabGetError as e:
                logging.error(f"Failed to download artifacts for slack notify job: {slack_notify_job.id} with error: {e}")

    return slack_message, slack_message_threads, slack_message_channel_to_thread, pipeline


def main():
    install_logging("Slack_Notifier.log")
    options = options_handler()
    triggering_workflow = options.triggering_workflow  # ci workflow type that is triggering the slack notifier
    pipeline_id = options.pipeline_id
    project_id = options.gitlab_project_id
    server_url = options.url
    ci_token = options.ci_token
    computed_slack_channel = options.slack_channel
    gitlab_client = Gitlab(server_url, private_token=ci_token, ssl_verify=GITLAB_SSL_VERIFY)
    slack_token = options.slack_token
    slack_client = WebClient(token=slack_token)
    logging.info(
        f"Sending Slack message for pipeline {pipeline_id} in project {project_id} on server {server_url} "
        f"triggering workflow:'{triggering_workflow}' allowing failure:{options.allow_failure} "
        f"slack channel:{computed_slack_channel} dry run:{options.dry_run}"
    )
    pull_request = None
    if options.current_branch != DEFAULT_BRANCH:
        try:
            branch = options.current_branch
            if triggering_workflow == BUCKET_UPLOAD and BUCKET_UPLOAD_BRANCH_SUFFIX in branch:
                branch = branch[: branch.find(BUCKET_UPLOAD_BRANCH_SUFFIX)]
            logging.info(f"Searching for pull request for origin branch:{options.current_branch} and calculated branch:{branch}")
            pull_request = GithubPullRequest(
                options.github_token,
                repository=options.repository,
                branch=branch,
                fail_on_error=True,
                verify=False,
            )
            author = pull_request.data.get("user", {}).get("login")
            if triggering_workflow in {CONTENT_NIGHTLY, CONTENT_PR, CONTENT_DOCS_PR, CONTENT_DOCS_NIGHTLY, DOCKERFILES_PR}:
                # This feature is only supported for content nightly and content pr workflows.
                computed_slack_channel = f"@{get_slack_user_name(author, author, options.name_mapping_path)}"
            else:
                logging.info(f"Not supporting custom Slack channel for {triggering_workflow} workflow")
            logging.info(
                f"Sending slack message to channel {computed_slack_channel} for "
                f"Author:{author} of PR#{pull_request.data.get('number')}"
            )
        except Exception:
            logging.error(f"Failed to get pull request data for branch {options.current_branch}")
    else:
        logging.info("Not a pull request build, skipping PR comment")

    pipeline_url, pipeline_failed_jobs = collect_pipeline_data(gitlab_client, project_id, pipeline_id)
    slack_msg_data, threaded_messages, title, attachments_json = construct_slack_msg(
        triggering_workflow,
        pipeline_url,
        pipeline_failed_jobs,
        pull_request,
        options.file,
        options.attachments,
        options.thread,
        options.dry_run,
    )

    slack_msg_output_file = ROOT_ARTIFACTS_FOLDER / SLACK_MESSAGE
    logging.info(f"Writing Slack message to {slack_msg_output_file}")
    write_json_to_file(slack_msg_data, slack_msg_output_file)
    threaded_messages_output_file = ROOT_ARTIFACTS_FOLDER / SLACK_MESSAGE_THREADS
    logging.info(f"Writing Slack threaded messages to {threaded_messages_output_file}")
    write_json_to_file(threaded_messages, threaded_messages_output_file)
    channel_to_thread = {}

    # From the test upload flow we only want the Slack message and threads, so we can append them to the current
    # pipeline's messages, we don't care about the channel mapping.
    test_upload_flow_pipeline_id_file = ROOT_ARTIFACTS_FOLDER / TEST_UPLOAD_FLOW_PIPELINE_ID
    if test_upload_flow_pipeline_id_file.exists():
        test_upload_flow_pipeline_id = test_upload_flow_pipeline_id_file.read_text().strip()
        test_upload_flow_slack_message = None
        test_upload_flow_slack_message_threads = None
        try:
            test_upload_flow_slack_message, test_upload_flow_slack_message_threads, _, test_upload_flow_pipeline = (
                get_pipeline_slack_data(gitlab_client, test_upload_flow_pipeline_id, project_id)
            )
            logging.info(f"Got Slack data from test upload flow pipeline: {test_upload_flow_pipeline_id}")
            test_upload_flow_pipeline_title = (
                f"Test Upload Flow Slack message - Pipeline Status:{test_upload_flow_pipeline.status}"
            )
            threaded_messages.append(
                {
                    "title_link": test_upload_flow_pipeline.web_url,
                    "color": "good" if test_upload_flow_pipeline.status == "success" else "danger",
                    "fallback": test_upload_flow_pipeline_title,
                    "title": test_upload_flow_pipeline_title,
                }
            )

            threaded_messages.extend(test_upload_flow_slack_message)
            threaded_messages.extend(test_upload_flow_slack_message_threads)
        except Exception as e:
            logging.exception(f"Failed to get Slack message or threads for test upload flow pipeline, reason: {e}")
        finally:
            if not test_upload_flow_slack_message or not test_upload_flow_slack_message_threads:
                logging.error(
                    f"Failed to get Slack message or threads for test upload flow pipeline: {test_upload_flow_pipeline_id}"
                )
                threaded_messages.append(
                    {
                        "fallback": "Failed to get Slack message or threads for test upload flow pipeline",
                        "title": "Failed to get Slack message or threads for test upload flow pipeline",
                        "color": "danger",
                    }
                )

    # We only need the channel mapping from the parent pipeline, so we can append it to the current pipeline's messages.
    parent_slack_message_channel_to_thread: dict = {}
    if (parent_pipeline_id := os.getenv("SLACK_PARENT_PIPELINE_ID")) and (
        parent_project_id := os.getenv("SLACK_PARENT_PROJECT_ID")
    ):
        logging.info(f"Parent pipeline data found: {parent_pipeline_id} in project {parent_project_id}")
        _, _, parent_slack_message_channel_to_thread, _ = get_pipeline_slack_data(
            gitlab_client, parent_pipeline_id, parent_project_id
        )
        logging.info(f"Got Slack data from parent pipeline: {parent_pipeline_id} in project {parent_project_id}")
    else:
        logging.info("No parent pipeline data found")

    errors = []
    for channel in channels_to_send_msg(computed_slack_channel):
        try:
            parent_thread = parent_slack_message_channel_to_thread.get(channel)
            response = slack_client.chat_postMessage(
                channel=channel,
                attachments=slack_msg_data,
                username=SLACK_USERNAME,
                link_names=True,
                text=title,
                thread_ts=parent_thread,
            )
            data: dict = response.data  # type: ignore[assignment]
            thread_ts: str = data["ts"]
            channel_id = data["channel"]
            channel_to_thread[channel] = thread_ts
            if parent_thread:
                threaded_ts = parent_thread
            else:
                threaded_ts = thread_ts
            if threaded_messages:
                for slack_msg in threaded_messages:
                    slack_client.chat_postMessage(
                        channel=channel,
                        attachments=[slack_msg],
                        username=SLACK_USERNAME,
                        thread_ts=threaded_ts,
                        text=slack_msg.get("title", title),
                    )
            if attachments_json:
                for attachment in attachments_json:
                    slack_client.files_upload_v2(
                        channel=channel_id,
                        thread_ts=threaded_ts,
                        file=attachment["file"],
                        filename=attachment.get("filename"),
                        title=attachment.get("title"),
                        alt_txt=attachment.get("alt_txt"),
                        initial_comment=attachment.get("initial_comment"),
                    )

            if response.status_code == requests.codes.ok:
                link = build_link_to_message(data["channel"], get_message_p_from_ts(threaded_ts))
                logging.info(f"Successfully sent Slack message to channel {channel} link: {link}")
        except Exception:
            if strtobool(options.allow_failure):
                logging.warning(f"Failed to send Slack message to channel {channel} not failing build")
            else:
                logging.exception(f"Failed to send Slack message to channel {channel}")
                errors.append(channel)
    channel_to_thread_output_file = ROOT_ARTIFACTS_FOLDER / SLACK_MESSAGE_CHANNEL_TO_THREAD
    logging.info(f"Writing channel to thread mapping to {channel_to_thread_output_file}")
    write_json_to_file(channel_to_thread, channel_to_thread_output_file)

    if errors:
        logging.error(f'Failed to send Slack message to channels: {", ".join(errors)}')
        sys.exit(1)


if __name__ == "__main__":
    main()
