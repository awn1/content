import json
import os
import re
from collections import defaultdict, namedtuple
from datetime import datetime, timedelta
from distutils.util import strtobool
from typing import Any

import requests
from jira import JIRA, Issue
from jira.client import ResultList
from requests.exceptions import HTTPError
from tenacity import RetryCallState, retry, retry_if_exception, stop_after_attempt, wait_exponential

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
