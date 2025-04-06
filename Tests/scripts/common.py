import json
import operator
import tempfile
import zipfile
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from itertools import pairwise
from pathlib import Path
from typing import Any, cast

import gitlab
import requests
from dateutil import parser
from gitlab import Gitlab
from gitlab.v4.objects import ProjectJob, ProjectPipeline
from gitlab.v4.objects.commits import ProjectCommit
from jira import Issue
from junitparser import JUnitXml, TestSuite

from Tests.scripts.collect_tests.test_conf import TestConf
from Tests.scripts.utils import logging_wrapper as logging

DOCKERFILES_PR = "Dockerfiles PR"
CONTENT_NIGHTLY = "Content Nightly"
CONTENT_PR = "Content PR"
CONTENT_MERGE = "Content Merge"
DEPLOY_AUTO_UPGRADE_PACKS = "Deploy Auto Upgrade Packs"
BUCKET_UPLOAD = "Upload Packs to Marketplace Storage"
SDK_NIGHTLY = "Demisto SDK Nightly"
TEST_NATIVE_CANDIDATE = "Test Native Candidate"
SECURITY_SCANS = "Security Scans"
BUILD_MACHINES_CLEANUP = "Build Machines Cleanup"
SDK_RELEASE = "Automate Demisto SDK release"
NATIVE_NIGHTLY = "Native Nightly"
CONTENT_DOCS_PR = "Content Docs PR"
CONTENT_DOCS_NIGHTLY = "Content Docs Nightly"
BLACKLIST_VALIDATION = "Blacklist Validation"
RIT_MR = "RIT MR"
RIT_RELEASE = "RIT Release"
RIT_PUBLISH = "RIT Publish"

WORKFLOW_TYPES = {
    DOCKERFILES_PR,
    CONTENT_NIGHTLY,
    NATIVE_NIGHTLY,
    CONTENT_PR,
    CONTENT_MERGE,
    SDK_NIGHTLY,
    BUCKET_UPLOAD,
    TEST_NATIVE_CANDIDATE,
    SECURITY_SCANS,
    BUILD_MACHINES_CLEANUP,
    SDK_RELEASE,
    CONTENT_DOCS_PR,
    CONTENT_DOCS_NIGHTLY,
    DEPLOY_AUTO_UPGRADE_PACKS,
    BLACKLIST_VALIDATION,
    RIT_MR,
    RIT_RELEASE,
    RIT_PUBLISH,
}
BUCKET_UPLOAD_BRANCH_SUFFIX = "-upload_test_branch"
TOTAL_HEADER = "Total"
NOT_AVAILABLE = "N/A"
TEST_SUITE_JIRA_HEADERS: list[str] = ["Jira\nTicket", "Jira\nTicket\nResolution"]
TEST_SUITE_DATA_CELL_HEADER = "S/F/E/T"
TEST_SUITE_CELL_EXPLANATION = "(Table headers: Skipped/Failures/Errors/Total)"
NO_COLOR_ESCAPE_CHAR = "\033[0m"
RED_COLOR = "\033[91m"
GREEN_COLOR = "\033[92m"
TEST_PLAYBOOKS_REPORT_FILE_NAME = "test_playbooks_report.xml"
TEST_MODELING_RULES_REPORT_FILE_NAME = "test_modeling_rules_report.xml"
TEST_USE_CASE_REPORT_FILE_NAME = "test_use_case_report.xml"
SECRETS_FOUND = "Secrets found"

E2E_RESULT_FILE_NAME = "e2e_tests_result.xml"

FAILED_TO_COLOR_ANSI = {
    True: RED_COLOR,
    False: GREEN_COLOR,
}
FAILED_TO_COLOR_NAME = {
    True: "red",
    False: "green",
}
FAILED_TO_MSG = {
    True: "failed",
    False: "succeeded",
}

EVALUATE_CONDITION_SUPPORTED_OPERATORS = {
    "<=": operator.le,
    ">=": operator.ge,
    "<": operator.lt,
    ">": operator.gt,
}

# This is the GitHub username of the bot (and its reviewer) that pushes contributions and docker updates to the content repo.
CONTENT_BOT = "content-bot"
CONTENT_BOT_REVIEWER = "github-actions[bot]"

STRING_TO_BOOL_MAP = {
    "y": True,
    "1": True,
    "yes": True,
    "true": True,
    "True": True,
    "n": False,
    "0": False,
    "no": False,
    "false": False,
    "False": False,
    "t": True,
    "f": False,
}

STATUS_MAP = {
    "good": "No secrets found",
    "danger": SECRETS_FOUND,
    "warning": "An error occurred",
}


def string_to_bool(
    input_: Any,
    default_when_empty: bool | None = None,
) -> bool:
    try:
        return STRING_TO_BOOL_MAP[str(input_).lower()]
    except (KeyError, TypeError):
        if input_ in ("", None) and default_when_empty is not None:
            return default_when_empty

    raise ValueError(f"cannot convert {input_} to bool")


def get_instance_directories(artifacts_path: Path) -> dict[str, Path]:
    instance_directories: dict[str, Path] = {}
    for directory in artifacts_path.iterdir():
        if (
            directory.is_dir()
            and directory.name.startswith("instance_")
            and (instance_role_txt := directory / "instance_role.txt").exists()
        ):
            instance_role: str = instance_role_txt.read_text().replace("\n", "")
            instance_directories[instance_role] = directory
    return instance_directories


def get_test_results_files(artifacts_path: Path, file_name: str) -> dict[str, Path]:
    results_files: dict[str, Path] = {}
    for instance_role, directory in get_instance_directories(artifacts_path).items():
        if (file_path := Path(artifacts_path) / directory / file_name).exists():
            logging.info(f"Found result file: {file_path} for instance role: {instance_role}")
            results_files[instance_role] = file_path
    return results_files


def get_properties_for_test_suite(test_suite: TestSuite) -> dict[str, str]:
    return {prop.name: prop.value for prop in test_suite.properties()}


def failed_to_ansi_text(text: str, failed: bool) -> str:
    return f"{FAILED_TO_COLOR_ANSI[failed]}{text}{NO_COLOR_ESCAPE_CHAR}"


class TestSuiteStatistics:
    def __init__(self, no_color, failures: int = 0, errors: int = 0, skipped: int = 0, tests: int = 0):
        self.no_color = no_color
        self.failures = failures
        self.errors = errors
        self.skipped = skipped
        self.tests = tests

    def __add__(self, other):
        return TestSuiteStatistics(
            self.no_color,
            self.failures + other.failures,
            self.errors + other.errors,
            self.skipped + other.skipped,
            self.tests + other.tests,
        )

    def show_with_color(self, res: int, show_as_error: bool | None = None) -> str:
        res_str = str(res)
        if self.no_color or show_as_error is None:
            return res_str
        return failed_to_ansi_text(res_str, show_as_error)

    def __str__(self):
        return (
            f"{self.show_with_color(self.skipped)}/"  # no color for skipped.
            f"{self.show_with_color(self.failures, self.failures > 0)}/"
            f"{self.show_with_color(self.errors, self.errors > 0)}/"
            f"{self.show_with_color(self.tests, self.errors + self.failures > 0)}"
        )


def calculate_results_table(
    jira_tickets_for_result: dict[str, Issue],
    results: dict[str, dict[str, Any]],
    server_versions: set[str],
    base_headers: list[str],
    add_total_row: bool = True,
    no_color: bool = False,
    without_jira: bool = False,
    with_skipped: bool = False,
    multiline_headers: bool = True,
    transpose: bool = False,
) -> tuple[list[str], list[list[Any]], JUnitXml, int]:
    # Importing pandas here to avoid importing it when not needed.
    import pandas as pd  # type: ignore

    xml = JUnitXml()
    headers_multiline_char = "\n" if multiline_headers else " "
    headers = [h.replace("\n", headers_multiline_char) for h in base_headers]
    if not without_jira:
        headers.extend([h.replace("\n", headers_multiline_char) for h in TEST_SUITE_JIRA_HEADERS])
    column_align = ["left"] * len(headers)
    fixed_headers_length = len(headers)
    server_versions_list: list[str] = sorted(server_versions)
    for server_version in server_versions_list:
        server_version_header = server_version.replace(" ", headers_multiline_char)
        headers.append(
            server_version_header
            if transpose
            else f"{server_version_header}{headers_multiline_char}{TEST_SUITE_DATA_CELL_HEADER}"
        )
        column_align.append("center")
    tabulate_data = [headers]
    total_row: list[Any] = [""] * fixed_headers_length + [TestSuiteStatistics(no_color) for _ in range(len(server_versions_list))]
    total_errors = 0
    for result, result_test_suites in results.items():
        row: list[Any] = []
        if not without_jira:
            if jira_ticket := jira_tickets_for_result.get(result):
                row.extend(
                    (
                        jira_ticket.key,
                        jira_ticket.get_field("resolution") if jira_ticket.get_field("resolution") else NOT_AVAILABLE,
                    )
                )
            else:
                row.extend([NOT_AVAILABLE] * len(TEST_SUITE_JIRA_HEADERS))

        skipped_count = 0
        errors_count = 0
        for server_version in server_versions_list:
            test_suite: TestSuite | None = result_test_suites.get(server_version)
            if test_suite:
                xml.add_testsuite(test_suite)
                row.append(
                    TestSuiteStatistics(
                        no_color,
                        test_suite.failures,
                        test_suite.errors,
                        test_suite.skipped,
                        test_suite.tests,
                    )
                )
                errors_count += test_suite.errors + test_suite.failures
                if test_suite.skipped and test_suite.failures == 0 and test_suite.errors == 0:
                    skipped_count += 1
            else:
                row.append(NOT_AVAILABLE)

        total_errors += errors_count
        # If all the test suites were skipped, don't add the row to the table.
        if skipped_count != len(server_versions_list) or with_skipped:
            row_result = f"{result}{headers_multiline_char}({TEST_SUITE_DATA_CELL_HEADER})" if transpose else result
            if no_color:
                row_result_color = row_result
            else:
                row_result_color = failed_to_ansi_text(row_result, errors_count > 0)
            row.insert(0, row_result_color)
            tabulate_data.append(row)

            # Offset the total row by the number of fixed headers
            for i, cell in enumerate(row[fixed_headers_length:], start=fixed_headers_length):
                if isinstance(cell, TestSuiteStatistics):
                    total_row[i] += cell
        else:
            logging.debug(f"Skipping {result} since all the test suites were skipped")
    if add_total_row:
        total_row[0] = TOTAL_HEADER if no_color else failed_to_ansi_text(TOTAL_HEADER, total_errors > 0)
        tabulate_data.append(total_row)

    if transpose:
        tabulate_data = pd.DataFrame(tabulate_data, index=None).transpose().to_numpy()

    return column_align, tabulate_data, xml, total_errors


def is_tpb_part_of_nightly(playbook: str, config: TestConf, pack_id: str) -> bool:
    """Return whether the given playbook id is one that should run in nightly or not.

    Args:
        playbook (str): The playbook id.
        config (TestConf): The conf.json object.
        pack_id (str): The pack id of the TPB pack.

    Returns:
        bool: whether the given playbook id is one that should run in nightly or not.
    """
    return pack_id in config.nightly_packs or playbook in config.non_api_tests


def get_all_failed_results(results: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    failed_results = {}
    for result, result_test_suites in results.items():
        for test_suite in result_test_suites.values():
            if test_suite.errors or test_suite.failures:
                failed_results[result] = result_test_suites
                break

    return failed_results


def replace_escape_characters(sentence: str, replace_with: str = " ") -> str:
    escape_chars = ["\n", "\r", "\b", "\f", "\t"]
    for escape_char in escape_chars:
        sentence = sentence.replace(escape_char, replace_with)
    return sentence


def get_pipelines_and_commits(gitlab_client: Gitlab, project_id, look_back_hours: int):
    """
    Get all pipelines and commits on the master branch in the last X hours.
    The commits and pipelines are in order of creation time.
    Args:
        gitlab_client - the gitlab instance
        project_id - the id of the project to query
        look_back_hours - the number of hours to look back for commits and pipeline
    Return:
        a list of gitlab pipelines and a list of gitlab commits in ascending order (as the way it is in the UI)
    """
    project = gitlab_client.projects.get(project_id)

    # Calculated the timestamp for look_back_hours ago
    time_threshold = (datetime.now(tz=timezone.utc) - timedelta(hours=look_back_hours)).isoformat()

    commits = project.commits.list(all=True, since=time_threshold, order_by="updated_at", sort="asc")
    pipelines = project.pipelines.list(
        all=True, updated_after=time_threshold, ref="master", source="push", order_by="id", sort="asc"
    )

    return pipelines, commits


def get_person_in_charge(commit: ProjectCommit) -> tuple[str, str, str] | tuple[None, None, None]:
    """
    Returns the name of the person in charge of the commit, the PR link and the beginning of the PR name.

    Args:
        commit: The Gitlab commit object containing author info.

    Returns:
        name: The name of the commit author.
        pr: The GitHub PR link for the Gitlab commit.
        beginning_of_pr_name: The beginning of the PR name.
    """
    name = commit.author_name
    # pr number is always the last id in the commit title, starts with a number sign, may or may not be in parentheses.
    pr_number = commit.title.split("#")[-1].strip("()")
    beginning_of_pr_name = commit.title[:20] + "..."
    if pr_number.isnumeric():
        pr = f"https://github.com/demisto/content/pull/{pr_number}"
        return name, pr, beginning_of_pr_name
    else:
        return None, None, None


def are_entities_in_order(entity_a: ProjectPipeline | ProjectJob, entity_b: ProjectPipeline | ProjectJob) -> bool:
    """
    Check if the entities (pipelines or jobs) are in the same order of their creation timestamps.

    Args:
        entity_a: The first entity object (pipeline or job).
        entity_b: The second entity object (pipeline or job).

    Returns:
        bool: True if entity_a is created after entity_b, False otherwise.
    """
    entity_a_timestamp = parser.parse(entity_a.created_at)
    entity_b_timestamp = parser.parse(entity_b.created_at)
    return entity_a_timestamp > entity_b_timestamp


def is_pivot(current_entity: ProjectPipeline | ProjectJob, entity_to_compare: ProjectPipeline | ProjectJob) -> bool | None:
    """
    Determine if the current entity status a pivot from the previous entity status.
    Args:
        current_entity: The current entity object (pipeline or job).
        entity_to_compare: An entity object (pipeline or job) to compare to.
    Returns:
        True if the status changed from success to fail.
        False if the status changed from failed to success.
        None if the status didn't change or the entities are not in order of creation.
    """

    in_order = are_entities_in_order(entity_a=current_entity, entity_b=entity_to_compare)
    if in_order:
        logging.info(
            f"The status of the current entity {current_entity.id} is {current_entity.status} and the "
            f"status of the compared entity {entity_to_compare.id} is {entity_to_compare.status}"
        )

        if entity_to_compare.status == "success" and current_entity.status == "failed":
            return True
        if entity_to_compare.status == "failed" and current_entity.status == "success":
            return False
    else:
        logging.error(
            f"The entities are not in order of creation, current entity: {current_entity.id}, "
            f"compared entity: {entity_to_compare.id}"
        )
    return None


def extract_blacklist_status(artifact: str) -> str | None:
    """
    Extracts the 'color' status from a blacklist job artifact.

    Args:
        artifact (str): JSON string representing the artifact.

    Returns:
        str | None: The color status if available, otherwise None.
    """
    try:
        artifact_data = json.loads(artifact)

        if not artifact_data or not isinstance(artifact_data, list):
            logging.error("Invalid artifact format: Expected a non-empty list")
            return None

        return artifact_data[0].get("color")

    except json.JSONDecodeError:
        logging.exception("Failed to parse blacklist artifact: Invalid JSON")
        return None
    except (IndexError, AttributeError) as e:
        logging.exception(f"Unexpected artifact structure: {e}")
        return None


def get_blacklist_status_details(job_artifact: str) -> str:
    """
    Parses the blacklist check result from the given artifact and returns its detailed status.

    Args:
        job_artifact (str): JSON string representing the blacklist artifact.

    Returns:
        str: A description of the blacklist check status.
    """
    color = extract_blacklist_status(job_artifact)

    message = STATUS_MAP.get(cast(str, color), "Unknown status")  # the cast is for mypy
    logging.info(f"Blacklist check status: {message}")

    return message


def is_blacklist_pivot(last_blacklist_artifact: str, second_to_last_blacklist_artifact: str) -> bool | None:
    """
    Determines if there is a pivot in the blacklist job based on the color field in the artifacts.

    Args:
        last_blacklist_artifact (str): JSON string representing the most recent blacklist job artifact.
        second_to_last_blacklist_artifact (str): JSON string representing the previous blacklist job artifact.

    Returns:
        bool | None:
            - True if the last artifact is 'good' and the previous was 'danger'.
            - False if the last artifact is 'danger' and the previous was 'good'.
            - None if no pivot is detected or data is missing.
    """
    color_last = extract_blacklist_status(last_blacklist_artifact)
    color_prev = extract_blacklist_status(second_to_last_blacklist_artifact)

    if color_last and color_prev:
        logging.info(f"Last artifact color: '{color_last}', Previous artifact color: '{color_prev}'")

        if color_last == "good" and color_prev == "danger":
            return False
        if color_last == "danger" and color_prev == "good":
            return True

    return None


def get_reviewer(pr_url: str) -> str | None:
    """
    Get the first reviewer who approved the PR.
    Args:
        pr_url: The URL of the PR.
    Returns:
        The name of the first reviewer who approved the PR.
    """
    approved_reviewer = None
    try:
        # Extract the owner, repo, and pull request number from the URL
        _, _, _, repo_owner, repo_name, _, pr_number = pr_url.split("/")

        # Get reviewers
        reviews_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/pulls/{pr_number}/reviews"
        reviews_response = requests.get(reviews_url)
        reviews_data = reviews_response.json()

        # Find the reviewer who provided approval
        for review in reviews_data:
            if review["state"] == "APPROVED":
                approved_reviewer = review["user"]["login"]
                break
    except Exception as e:
        logging.error(f"Failed to get reviewer for PR {pr_url}: {e}")
    return approved_reviewer


def get_slack_user_name(name: str | None, default: str | None, name_mapping_path: str) -> str:
    """
    Get the Slack username for a given GitHub name.
    Args:
        default: The default name to return if the name is not found.
        name: The name to convert.
        name_mapping_path: The path to the name mapping file.
    Returns:
        The Slack username.
    """
    with open(name_mapping_path) as name_mapping:
        mapping = json.load(name_mapping)
        # If the name is the name of the 'docker image update bot' reviewer - return the owner of that bot.
        if name == CONTENT_BOT_REVIEWER:
            return mapping.get("docker_images", {}).get("owner", default)
        else:
            return mapping.get("names", {}).get(name, default)


def get_commit_by_sha(commit_sha: str, list_of_commits: list[ProjectCommit]) -> ProjectCommit | None:
    """
    Get a commit by its SHA.
    Args:
        commit_sha: The SHA of the commit.
        list_of_commits: A list of commits.
    Returns:
        The commit object.
    """
    return next((commit for commit in list_of_commits if commit.id == commit_sha), None)


def get_pipeline_by_commit(commit: ProjectCommit, list_of_pipelines: list[ProjectPipeline]) -> ProjectPipeline | None:
    """
    Get a pipeline by its commit.
    Args:
        commit: The commit object.
        list_of_pipelines: A list of pipelines.
    Returns:
        The pipeline object.
    """
    return next((pipeline for pipeline in list_of_pipelines if pipeline.sha == commit.id), None)


def create_shame_message(
    suspicious_commits: list[ProjectCommit], pipeline_changed_status: bool, name_mapping_path: str
) -> tuple[str, str, str, str] | None:
    """
    Create a shame message for the person in charge of the commit, or for multiple people in case of multiple suspicious commits.
    Args:
        suspicious_commits: A list of suspicious commits.
        pipeline_changed_status: A boolean indicating if the pipeline status changed.
        name_mapping_path: The path to the name mapping file.
    Returns:
        A tuple of strings containing the message, the person in charge, the PR link and the color of the message.
    """
    hi_and_status = person_in_charge = in_this_pr = color = ""
    for suspicious_commit in suspicious_commits:
        name, pr, beginning_of_pr = get_person_in_charge(suspicious_commit)
        if name and pr and beginning_of_pr:
            if name == CONTENT_BOT:
                name = get_reviewer(pr)
            name = get_slack_user_name(name, name, name_mapping_path)
            msg = "broken" if pipeline_changed_status else "fixed"
            color = "danger" if pipeline_changed_status else "good"
            emoji = ":cry:" if pipeline_changed_status else ":muscle:"
            if suspicious_commits.index(suspicious_commit) == 0:
                hi_and_status = f"Hi, The build was {msg} {emoji} by:"
                person_in_charge = f"@{name}"
                in_this_pr = f" That was done in this PR: {slack_link(pr, beginning_of_pr)}"

            else:
                person_in_charge += f" or @{name}"
                in_this_pr = ""

    return (hi_and_status, person_in_charge, in_this_pr, color) if hi_and_status and person_in_charge and color else None


def slack_link(url: str, text: str) -> str:
    """
    Create a Slack link.
    Args:
        url: The URL to link to.
        text: The text to display.
    Returns:
        The Slack link.
    """
    return f"<{url}|{text}>"


def was_message_already_sent(commit_index: int, list_of_commits: list, list_of_pipelines: list) -> bool:
    """
    Check if a message was already sent for newer commits, this is possible if pipelines of
    later commits finished before the pipeline of the current commit.
    Args:
        commit_index: The index of the current commit.
        list_of_commits: A list of commits.
        list_of_pipelines: A list of pipelines.
    Returns:

    """
    for previous_commit, current_commit in pairwise(reversed(list_of_commits[:commit_index])):
        current_pipeline = get_pipeline_by_commit(current_commit, list_of_pipelines)
        previous_pipeline = get_pipeline_by_commit(previous_commit, list_of_pipelines)
        # in rare cases some commits have no pipeline
        if current_pipeline and previous_pipeline and (is_pivot(current_pipeline, previous_pipeline) is not None):
            return True
    return False


def get_job_by_name(gitlab_client: gitlab.Gitlab, project_id: str, pipeline_id: str, job_name: str) -> ProjectJob | None:
    """
    Retrieve a job within a given pipeline that matches a specific job name (Only one job is expected to match the name).
    Args:
        gitlab_client - The GitLab client instance.
        project_id - The ID of the project.
        pipeline_id - The ID of the pipeline.
        job_name - The name of the job to filter.

    Returns:
         The job object if found, None otherwise
    """
    project = gitlab_client.projects.get(project_id)
    pipeline = project.pipelines.get(pipeline_id)
    jobs = pipeline.jobs.list(all=True)

    # Find the job by the specified job name
    for job in jobs:
        if job.name == job_name:
            return job
    logging.error(f"Job {job_name} not found in pipeline {pipeline_id}")
    return None


def download_and_read_artifact(gitlab_client: gitlab.Gitlab, project_id: str, job_id: int, artifact_path: Path) -> str:
    """
    Download (for reading only, without saving the file) the artifact of a specific job and read the content of a file.

    Args:
        gitlab_client (gitlab.Gitlab): The GitLab client instance.
        project_id (str): The ID of the project.
        job_id (int): The ID of the job.
        artifact_path (str): The path of the file to read within the artifact.
    Returns:
        str: The content of the specified file.
    """
    try:
        # Get the job object
        job = gitlab_client.projects.get(project_id).jobs.get(job_id)

        with tempfile.TemporaryDirectory() as temp_dir:
            artifacts_zip_file = Path(temp_dir) / "artifacts.zip"

            # Download and extract the artifact
            with open(artifacts_zip_file, "wb") as f:
                job.artifacts(streamed=True, action=f.write)
            with zipfile.ZipFile(artifacts_zip_file, "r") as zip_ref:
                zip_ref.extractall(temp_dir)

            # Read the content of the specified file within the extracted directory
            return (Path(temp_dir) / artifact_path).read_text()
    except Exception as e:
        logging.error(f"Failed to download or extract artifacts for job {job_id}: {e}")
        raise


def secrets_sha_has_changed(last_job_artifacts, second_to_last_job_artifacts) -> bool:
    """
    Check if the SHA of secrets has changed between the last and second-to-last job artifacts.

    Args:
        last_job_artifacts (str): Artifacts from the last job.
        second_to_last_job_artifacts (str): Artifacts from the second-to-last job.

    Returns:
        bool: True if SHA changed, False otherwise.
    """
    try:
        sha_last = json.loads(last_job_artifacts)[0].get("hash")
        sha_prev = json.loads(second_to_last_job_artifacts)[0].get("hash")

        if not sha_last or not sha_prev:
            logging.warning("Missing SHA in one or both jobs.")
            return False
        logging.info(f"Last job SHA: {sha_last}, Previous job SHA: {sha_prev}")

    except json.JSONDecodeError:
        logging.exception("Failed to parse job artifacts: Invalid JSON")
        return False
    except (IndexError, KeyError) as e:
        logging.exception(f"Unexpected artifact structure: {e}")
        return False

    return sha_last != sha_prev


def get_nearest_newer_commit_with_pipeline(
    list_of_pipelines: list[ProjectPipeline], list_of_commits: list[ProjectCommit], current_commit_index: int
) -> tuple[ProjectPipeline, list] | tuple[None, None]:
    """
     Get the nearest newer commit that has a pipeline.
    Args:
        list_of_pipelines: A list of pipelines.
        list_of_commits: A list of commits.
        current_commit_index: The index of the current commit.
    Returns:
        A tuple of the nearest pipeline and a list of suspicious commits that have no pipelines.
    """
    suspicious_commits = []
    for index in reversed(range(current_commit_index - 1)):
        next_commit = list_of_commits[index]
        suspicious_commits.append(list_of_commits[index + 1])
        next_pipeline = get_pipeline_by_commit(next_commit, list_of_pipelines)
        if next_pipeline:
            return next_pipeline, suspicious_commits
    return None, None


def get_nearest_older_commit_with_pipeline(
    list_of_pipelines: list[ProjectPipeline], list_of_commits: list[ProjectCommit], current_commit_index: int
) -> tuple[ProjectPipeline, list] | tuple[None, None]:
    """
     Get the nearest oldest commit that has a pipeline.
    Args:
        list_of_pipelines: A list of pipelines.
        list_of_commits: A list of commits.
        current_commit_index: The index of the current commit.
    Returns:
        A tuple of the nearest pipeline and a list of suspicious commits that have no pipelines.
    """
    suspicious_commits = []
    for index in range(current_commit_index, len(list_of_commits) - 1):
        previous_commit = list_of_commits[index + 1]
        suspicious_commits.append(list_of_commits[index])
        previous_pipeline = get_pipeline_by_commit(previous_commit, list_of_pipelines)
        if previous_pipeline:
            return previous_pipeline, suspicious_commits
    return None, None


def evaluate_condition(parameter: float, condition: str, hundred_percent: float = 1) -> bool:
    """
    Evaluates a parameter against a given condition string.

    :param parameter: The value to evaluate.
    :param condition: The condition string (e.g., "<=50%", ">10", "<=0").
    :param hundred_percent: The value that represents 100% for percentage-based conditions.
    :return: Boolean indicating if the parameter meets the condition.
    """

    # Determine the operator used in the condition
    for op in EVALUATE_CONDITION_SUPPORTED_OPERATORS:
        if op in condition:
            operator_func = EVALUATE_CONDITION_SUPPORTED_OPERATORS[op]
            condition_value_str = condition.split(op)[1].strip()
            break
    else:
        raise ValueError(f"Unknown condition format: {condition}")

    # Check if the condition contains a percentage
    if "%" in condition_value_str:
        condition_value = float(condition_value_str.replace("%", "").strip())
        parameter = (parameter / hundred_percent) * 100
    else:
        condition_value = float(condition_value_str)

    # Evaluate the condition
    return operator_func(parameter, condition_value)


def join_list_by_delimiter_in_chunks(list_to_join: Iterable[str], delimiter: str = ", ", max_length: int = 2_000) -> list[str]:
    """
    Join a list of strings into chunks with a given delimiter and maximum length.
    Args:
        list_to_join (list): The list to split.
        delimiter (str): The delimiter to join the chunks.
        max_length (int): The maximum length of each chunk.

    Returns:
        list: The list of chunks.
    """
    chunks = []
    current_chunk = ""
    for item in list_to_join:
        if len(current_chunk) + len(item) + len(delimiter) > max_length:
            chunks.append(current_chunk)
            current_chunk = ""
        current_chunk += f"{item}{delimiter}"
    if current_chunk:
        chunks.append(current_chunk)
    return chunks


def is_within_time_window(target_hours: int, target_minutes: int, window_minutes: int) -> bool:
    """
    Check if the current time is within a specified time window of a target time.

    Args:
        target_hours - The starting hour (0-23) in UTC for the range window when the Slack message should be sent.
        target_minutes - The starting minute (0-59) in UTC for the range window when the Slack message should be sent.
        window_minutes - The duration of the range window in minutes during which the Slack message can be sent.

    Returns:
        True if the current time is within the time window of the target time, False otherwise.
    """
    now = datetime.now(tz=timezone.utc)
    target_time = now.replace(hour=target_hours, minute=target_minutes, second=0, microsecond=0)

    # Calculate the time difference
    time_difference = abs(now - target_time)

    logging.info(
        f"Current time (UTC): {now}, "
        f"Target time (UTC): {target_time}, "
        f"Time difference: {time_difference}, "
        f"Window duration: {timedelta(minutes=window_minutes)}"
    )

    # Check if the time difference is within the specified time window
    return time_difference <= timedelta(minutes=window_minutes)


def get_scheduled_pipelines_by_name(
    gitlab_client: Gitlab, project_id: str, pipeline_name: str, look_back_hours: int
) -> list[ProjectPipeline]:
    """
    Get all scheduled pipelines of a specific name within the last X hours.
    Args:
        gitlab_client - The GitLab client instance.
        project_id - The ID of the project to query.
        pipeline_name - The name of the scheduled pipeline to filter.
        look_back_hours - The number of hours to look back for scheduled pipelines.

    Returns:
        A list of GitLab pipelines that match the criteria.
    """
    project = gitlab_client.projects.get(project_id)
    time_threshold = (datetime.now(tz=timezone.utc) - timedelta(hours=look_back_hours)).isoformat()

    return project.pipelines.list(
        all=True,
        updated_after=time_threshold,
        ref="master",
        source="schedule",
        order_by="id",
        sort="asc",
        name=pipeline_name,
    )


def day_suffix(day: int) -> str:
    if 4 <= day <= 20 or 24 <= day <= 30:
        return str(day) + "th"
    elif day % 10 == 1:
        return str(day) + "st"
    elif day % 10 == 2:
        return str(day) + "nd"
    elif day % 10 == 3:
        return str(day) + "rd"
    else:
        return str(day) + "th"


def get_previous_pipeline(last_pipelines, given_pipeline_id) -> str | None:
    """
    Retrieve the ID of the pipeline that ran immediately before the given pipeline.
    Args:
        last_pipelines (list[ProjectPipeline]): A list of pipelines, sorted in ascending order.
        given_pipeline_id (str): The ID of the pipeline for which to find the previous pipeline.

    Returns:
        str: The ID of the pipeline that ran immediately before the given pipeline, or None if there is no previous pipeline.
    """
    for i in range(1, len(last_pipelines)):
        if last_pipelines[i].id == given_pipeline_id:
            return last_pipelines[i - 1].id if i > 0 else None
    return None
