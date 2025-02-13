import json
import os
import re
from collections import defaultdict, namedtuple
from datetime import datetime, timedelta
from distutils.util import strtobool
from pathlib import Path
from typing import Any

import requests
from jira import JIRA, Issue, JIRAError
from jira.client import ResultList
from requests.exceptions import HTTPError
from tenacity import RetryCallState, retry, retry_if_exception, stop_after_attempt, wait_exponential

from Tests.scripts.common import AUTO_CLOSE_LABEL, AUTO_CLOSE_PROPERTY, AUTO_CLOSE_TOTAL_SUCCESSFUL_RUNS, Execution_Type
from Tests.scripts.utils import logging_wrapper as logging

GITLAB_PROJECT_ID = os.getenv("CI_PROJECT_ID")
GITLAB_SERVER_URL = os.getenv("CI_SERVER_URL")
CI_PIPELINE_URL = os.getenv("CI_PIPELINE_URL", "")
JIRA_TIME_FORMAT = "%Y-%m-%dT%H:%M:%S.%f%z"

JiraServerInfo = namedtuple("JiraServerInfo", ["server_url", "api_key", "verify_ssl"])
JiraTicketInfo = namedtuple(
    "JiraTicketInfo", ["project_id", "issue_type", "component", "issue_unresolved_transition_name", "additional_fields", "labels"]
)


def log_before_retry(retry_state: RetryCallState):
    logging.info(
        f"Retrying {retry_state.fn} due to {retry_state.outcome.exception()}. "  # type: ignore
        f"Attempt {retry_state.attempt_number} will happen in {retry_state.next_action.sleep} seconds."  # type: ignore
    )


# Custom condition to retry on specific exceptions
def should_retry(exception: BaseException) -> bool:
    if isinstance(exception, HTTPError) and exception.response is not None:
        return exception.response.status_code in [requests.codes.unauthorized, requests.codes.too_many_requests]
    return False


@retry(
    retry=retry_if_exception(should_retry),  # Retry only on specific conditions
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=8),  # Exponential backoff: 2, 4, 8 seconds
    before_sleep=log_before_retry,
)
def search_issues_with_retry(jira_server: JIRA, jql_query: str, max_results: int, start_at: int = 0) -> ResultList[Issue]:
    return jira_server.search_issues(jql_query, maxResults=max_results, startAt=start_at)  # type: ignore[assignment]


def get_jira_server_info() -> JiraServerInfo:
    # Enable logging for 'requests' and 'urllib3' to help debug 4XX/5XX responses
    logging.getLogger("requests").setLevel(logging.DEBUG)
    logging.getLogger("urllib3").setLevel(logging.DEBUG)
    return JiraServerInfo(
        server_url=os.getenv("JIRA_SERVER_URL"),
        api_key=os.getenv("JIRA_API_KEY"),
        verify_ssl=bool(strtobool(os.getenv("JIRA_VERIFY_SSL", "true"))),
    )


def get_jira_ticket_info() -> JiraTicketInfo:
    project_id = os.getenv("JIRA_PROJECT_ID")
    issue_type = os.getenv("JIRA_ISSUE_TYPE", "")  # Default to empty string if not set
    component = os.getenv("JIRA_COMPONENT", "")  # Default to empty string if not set
    issue_unresolved_transition_name = os.getenv("JIRA_ISSUE_UNRESOLVED_TRANSITION_NAME")
    # Jira additional fields are a json string that will be parsed into a dictionary containing the name of the field
    # as the key and the value as a dictionary containing the value of the field.
    additional_fields = json.loads(os.getenv("JIRA_ADDITIONAL_FIELDS", "{}"))
    # Jira label are a json string that will be parsed into a list of labels.
    labels = json.loads(os.getenv("JIRA_LABELS", "[]"))
    return JiraTicketInfo(
        project_id=project_id,
        issue_type=issue_type,
        component=component,
        issue_unresolved_transition_name=issue_unresolved_transition_name,
        additional_fields=additional_fields,
        labels=labels,
    )


def generate_ticket_summary(prefix: str) -> str:
    # This is the existing conventions of the Content Gold Bot, don't change as it will break backward compatibility.
    summary = f"{prefix} fails nightly"
    return summary


def generate_query_by_component_and_issue_type(jira_ticket_info: JiraTicketInfo) -> str:
    jira_labels = "".join(f' AND labels = "{x}"' for x in jira_ticket_info.labels) if jira_ticket_info.labels else ""
    return (
        f'project = "{jira_ticket_info.project_id}" AND issuetype = "{jira_ticket_info.issue_type}" '
        f'AND component = "{jira_ticket_info.component}" {jira_labels}'
    )


def generate_query_with_summary(jira_ticket_info: JiraTicketInfo, summary: str) -> str:
    jql_query = (
        f"{generate_query_by_component_and_issue_type(jira_ticket_info)} " f'AND summary ~ "{summary}" ORDER BY created DESC'
    )
    return jql_query


def convert_jira_time_to_datetime(jira_time: str) -> datetime:
    return datetime.strptime(jira_time, JIRA_TIME_FORMAT)


def jira_file_link(file_name: str) -> str:
    return f"[^{file_name}]"


def jira_sanitize_file_name(file_name: str) -> str:
    return re.sub(r"[^\w-]", "-", file_name).lower()


def jira_color_text(text: str, color: str) -> str:
    return f"{{color:{color}}}{text}{{color}}"


def get_transition(jira_ticket_info: JiraTicketInfo, jira_server: JIRA, jira_issue: Issue) -> str | None:
    transitions = jira_server.transitions(jira_issue)
    unresolved_transition = next(
        filter(lambda transition: transition["name"] == jira_ticket_info.issue_unresolved_transition_name, transitions), None
    )
    return unresolved_transition["id"] if unresolved_transition else None


def transition_jira_ticket_to_unresolved(jira_server: JIRA, jira_issue: Issue | None, unresolved_transition_id: str | None):
    if unresolved_transition_id:
        jira_server.transition_issue(jira_issue, unresolved_transition_id)


def find_existing_jira_ticket(
    jira_ticket_info: JiraTicketInfo,
    jira_server: JIRA,
    now: datetime,
    max_days_to_reopen: int,
    jira_issue: Issue | None,
) -> tuple[Issue | None, Issue | None, bool, str | None]:
    link_to_issue = None
    jira_issue_to_use = None
    unresolved_transition_id = None
    if use_existing_issue := (jira_issue is not None):
        searched_issue: Issue = jira_issue
        if searched_issue.get_field("resolution"):
            resolution_date = convert_jira_time_to_datetime(searched_issue.get_field("resolutiondate"))
            if use_existing_issue := (resolution_date and (now - resolution_date) <= timedelta(days=max_days_to_reopen)):  # type: ignore[assignment]
                if unresolved_transition_id := get_transition(jira_ticket_info, jira_server, jira_issue):
                    jira_issue_to_use = searched_issue
                else:
                    logging.error(
                        f"Failed to find the '{jira_ticket_info.issue_unresolved_transition_name}' "
                        f"transition for issue {searched_issue.key}"
                    )
                    jira_issue_to_use = None
                    use_existing_issue = False
                    link_to_issue = searched_issue
            else:
                link_to_issue = searched_issue
        else:
            jira_issue_to_use = searched_issue
    return jira_issue_to_use, link_to_issue, use_existing_issue, unresolved_transition_id


def generate_build_markdown_link(ci_pipeline_id: str) -> str:
    ci_pipeline_id_hash = f" #{ci_pipeline_id}" if ci_pipeline_id else ""
    ci_pipeline_markdown_link = (
        f"[Nightly{ci_pipeline_id_hash}|{CI_PIPELINE_URL}]" if CI_PIPELINE_URL else f"Nightly{ci_pipeline_id_hash}"
    )
    return ci_pipeline_markdown_link


def jira_server_information(jira_server: JIRA) -> dict[str, Any]:
    jira_server_info = jira_server.server_info()
    logging.info("Jira server information:")
    for key, value in jira_server_info.items():
        logging.info(f"\t{key}: {value}")
    return jira_server_info


def jira_search_all_by_query(
    jira_server: JIRA,
    jql_query: str,
    max_results_per_request: int = 100,
) -> dict[str, list[Issue]]:
    start_at = 0  # Initialize pagination parameters
    issues: dict[str, list[Issue]] = defaultdict(list)
    while True:
        issues_batch: ResultList[Issue] = search_issues_with_retry(
            jira_server, jql_query, max_results=max_results_per_request, start_at=start_at
        )
        for issue in issues_batch:
            summary: str = issue.get_field("summary").lower()
            issues[summary].append(issue)

        # Update the startAt value for the next page
        start_at += max_results_per_request
        if start_at >= issues_batch.total:
            break

    return issues


def jira_ticket_to_json_data(server_url: str, jira_ticket: Issue) -> dict[str, Any]:
    return {
        "url": jira_issue_permalink(server_url, jira_ticket),
        "key": jira_ticket.key,
    }


def jira_issue_permalink(server_url: str, jira_ticket: Issue):
    """
    Get the browsable URL of the issue.
    We're not using the issue.permalink() method because it returns URL from the proxy, and we need the server Base URL.

    Returns:
        str: browsable URL of the issue
    """
    return f"{server_url}/browse/{jira_ticket.key}"


def set_property_value(jira_server: JIRA, issue_key: str, property_issue_key: str, new_value: int | None = None):
    """
    Sets the auto-close property of a JIRA issue to a specific integer value.

    Args:

        jira_server (JIRA): The JIRA server instance to interact with.
        issue_key (str): The key of the JIRA issue to set the property for.
        new_value(int): The new value to set for the auto-close property.
        property_issue_key: the key of the JIRA issue to set the property for.

    Returns:
        None
    """
    try:
        jira_server.add_issue_property(issue=issue_key, key=property_issue_key, data=new_value)
    except JIRAError as e:
        logging.info(f"failed to reset the auto-close property for {issue_key}: {e}")


def get_property_value(jira_server: JIRA, issue_key: str, property_issue_key: str) -> int:
    """
    Retrieves the auto-close property value of a JIRA issue.

    Args:
        jira_server (JIRA): The JIRA server instance to interact with.
        issue_key (str): The key of the JIRA issue to retrieve the property for.
        property_issue_key: the key of the JIRA issue to set the property for.

    Returns:
        int: The value of the property, or 0 if not set.
    """
    try:
        properties = jira_server.issue_properties(issue_key)
        return next((issue_property.value for issue_property in properties if issue_property.key == property_issue_key), 0)
    except JIRAError as e:
        logging.error(f"failed to retrieve {property_issue_key} property for {issue_key}: {e}")
        return 0


def jira_closing_issue(jira_server: JIRA, issue: Issue, comment: str = "Automatically closed"):
    """
    Closes a JIRA issue by transitioning it to the 'Done' status and optionally resets its auto-close property.

    Args:
        jira_server (JIRA): The JIRA server instance to interact with.
        issue (Issue): The issue to close.
        comment (str, optional): A comment to add to the issue when transitioning to 'Done'. Defaults to
                                "Automatically closed".

    Returns:
        None
    """
    set_property_value(jira_server=jira_server, issue_key=issue.key, property_issue_key=AUTO_CLOSE_PROPERTY)
    jira_server.transition_issue(issue=issue.key, transition="Done", fields={"resolution": {"name": "Fixed"}}, comment=comment)
    issue.update(update={"labels": [{"remove": AUTO_CLOSE_LABEL}]})


def jira_auto_close_issue(
    jira_server: JIRA, jira_tickets_dict: dict[str, Issue], failed_executions: dict
) -> tuple[dict[str, Issue], dict[str, Issue], dict[str, Issue]]:
    """
    Automatically handle Jira issues with the "auto-resolve" label based on playbook results.

    Args:
        jira_server (JIRA): The Jira server instance.
        jira_tickets_dict (dict[str, Issue]): Mapping of issue names to Jira issues.
        failed_playbooks (dict): Mapping of issue names to playbook failure details.

    Returns:
        dict[str, Any]: Summary of actions taken on Jira issues.
    """

    runs_with_property, failed_runs_with_property, successful_closed_tickets = {}, {}, {}
    logging.info("starting auto-close mechanism.. ")
    for issue_name, issue in jira_tickets_dict.items():
        if AUTO_CLOSE_LABEL not in issue.fields.labels:
            continue
        test_failed = failed_executions.get(issue_name, {}).get("failures", 0)
        counter_value = get_property_value(jira_server=jira_server, issue_key=issue.key, property_issue_key=AUTO_CLOSE_PROPERTY)
        logging.debug(f"{issue_name=} has {AUTO_CLOSE_PROPERTY}:{counter_value=} ")

        if test_failed:
            # Reset counter if the test playbook failed
            if counter_value != 0:
                set_property_value(jira_server=jira_server, issue_key=issue.key, property_issue_key=AUTO_CLOSE_PROPERTY)
                logging.debug(f"{issue_name=} has failed. The counter was reset")
            failed_runs_with_property[issue_name] = issue

        else:
            if counter_value + 1 >= AUTO_CLOSE_TOTAL_SUCCESSFUL_RUNS:
                logging.debug(f"{issue_name=} closed after consecutive successful." f" Removing {AUTO_CLOSE_LABEL} label.")
                jira_closing_issue(
                    jira_server=jira_server,
                    issue=issue,
                    comment=f"Automatically closed after {AUTO_CLOSE_TOTAL_SUCCESSFUL_RUNS} "
                    f"consecutive successful runs using the {AUTO_CLOSE_LABEL} mechanism.",
                )
                successful_closed_tickets[issue_name] = issue
            else:
                set_property_value(
                    jira_server=jira_server,
                    issue_key=issue.key,
                    property_issue_key=AUTO_CLOSE_PROPERTY,
                    new_value=counter_value + 1,
                )
                runs_with_property[issue_name] = issue
    logging.info("finished auto-close mechanism.. ")
    return runs_with_property, failed_runs_with_property, successful_closed_tickets


def create_jira_mapping_dict(server_url: str, jira_tickets_logs: dict[str, Issue]) -> dict[str, Any]:
    """
    Creates a mapping dictionary from playbook IDs to their corresponding JIRA ticket JSON data.

    Args:
        server_url (str): The URL of the JIRA server.
        jira_tickets_logs (dict[str, Issue]): A dictionary where keys are playbook IDs and values are JIRA Issue objects.

    Returns:
        dict: A dictionary mapping playbook IDs to their JIRA ticket JSON data.
    """
    return {
        playbook_id: jira_ticket_to_json_data(server_url, jira_ticket) for playbook_id, jira_ticket in jira_tickets_logs.items()
    }


def save_jira_mapping_to_file(file_path: Path, jira_mapping_dict: dict[str, Any]):
    """
    Saves a JIRA mapping dictionary to a specified file.

    Args:
        file_path (Path): The path to the file where the dictionary will be saved.
        jira_mapping_dict (dict[str, Any]): The mapping dictionary to be saved.

    Returns:
        None
    """
    logging.info(f"Writing JIRA mapping to {file_path}")
    with file_path.open("w") as file:
        json.dump(jira_mapping_dict, file, indent=4, sort_keys=True, default=str)


def write_test_execution_to_jira_mapping(
    server_url: str,
    artifacts_path: Path,
    path_log_file: str,
    jira_tickets_dict: dict[str, Issue],
):
    """
    Writes test playbook/ modeling rule -to-JIRA mapping and auto-resolved ticket logs to files.

    Args:

        path_auto_close:  The path to the directory where the auto resolve files will be saved.
        path_log_file:  The path to the directory where the logs files will be saved.
        server_url (str): The URL of the JIRA server.
        artifacts_path (Path): The path to the directory where the files will be saved.
        jira_tickets_dict (dict[str, Issue]): A dictionary mapping playbook IDs to JIRA Issue objects.

    Returns:
        None
    """
    test_execution_result_to_jira_mapping = create_jira_mapping_dict(server_url, jira_tickets_dict)
    save_jira_mapping_to_file(artifacts_path / path_log_file, test_execution_result_to_jira_mapping)
    logging.debug(f"JIRA Mapping saved to {artifacts_path / path_log_file}")


def write_auto_close_to_jira_mapping(
    server_url: str,
    artifacts_path: Path,
    path_auto_close: str,
    test_execution_type: Execution_Type,
    runs_with_property: dict[str, Issue] | None = None,
    failed_property: dict[str, Issue] | None = None,
    successful_property: dict[str, Issue] | None = None,
):
    """
    Writes test playbook/ modeling rule -to-JIRA mapping and auto-resolved ticket logs to files.

    Args:

        path_auto_close:  The path to the directory where the auto resolve files will be saved.
        server_url (str): The URL of the JIRA server.
        artifacts_path (Path): The path to the directory where the files will be saved.
        runs_with_property (dict[str, Any]): A dictionary of playbook IDs and their corresponding JIRA
                                                        Issues for tickets with auto-close label.
        failed_property (dict[str, Any]): A dictionary of playbook IDs and their corresponding JIRA
                                                        Issues for tickets with auto-close label that failed.
        successful_property (dict[str, Any]): A dictionary of playbook IDs and their corresponding JIRA
                                                        Issues for tickets with auto-close label that closed after
                                                        successful max runs.
        test_execution_type: Determine Type of test execution ('ModelingRules' or 'TestPlaybooks').

    Returns:
        None
    """
    property_ticket_logs_to_file = {}

    if runs_with_property:
        property_ticket_logs_to_file[f"Current {test_execution_type.value} running with auto close"] = create_jira_mapping_dict(
            server_url, runs_with_property
        )
    if failed_property:
        property_ticket_logs_to_file[f"Failed {test_execution_type.value}"] = create_jira_mapping_dict(
            server_url, failed_property
        )
    if successful_property:
        property_ticket_logs_to_file[f"Closed {test_execution_type.value} After Successful Runs"] = create_jira_mapping_dict(
            server_url, successful_property
        )
    if property_ticket_logs_to_file:
        logging.debug(f"JIRA auto-close results saved to {artifacts_path / path_auto_close}")
        save_jira_mapping_to_file(
            artifacts_path / path_auto_close,
            property_ticket_logs_to_file,
        )
