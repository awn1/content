import getpass
import re
import warnings
from typing import Any

import keyring
import requests
import tabulate
import typer
from urllib3.exceptions import InsecureRequestWarning
from xlogs.commands.common import logger

# Suppress the warning
warnings.filterwarnings("ignore", category=InsecureRequestWarning)

ABOUT_FIELD_ID = "customfield_20735"
REQUESTED_FIELDS = [ABOUT_FIELD_ID]
SLACK_PERMISSION_WEBHOOK_URL = "https://hooks.slack.com/triggers/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"
JIRA_BASE_URL = "https://jira-dc.paloaltonetworks.com/rest/api/2"


class Client:
    def __init__(self, jira_token: str) -> None:
        self.jira_token = jira_token
        self.headers = {"Authorization": f"Bearer {jira_token}", "Content-Type": "application/json"}
        self._session = requests.Session()

    def __del__(self):
        try:
            self._session.close()
        except Exception:
            logger.exception("Failed closing session")

    def get_jira_ticket_data(self, ticket_id: str, ticket_fields: list[str] | None = None) -> dict[str, str]:
        url = f"{JIRA_BASE_URL}/issue/{ticket_id}"
        if ticket_fields:
            url = f'{url}?fields={",".join(ticket_fields)}'

        response = self._session.get(url=url, headers=self.headers)
        return response.json()["fields"]

    def get_assignee_email(self) -> str:
        url = f"{JIRA_BASE_URL}/myself"
        response = self._session.get(url=url, headers=self.headers)
        email = response.json().get("emailAddress")
        if not email:
            raise Exception("Can not get the assignee email address from Jira")
        return email

    def get_in_progress_tickets(self) -> list[dict[str, Any]]:
        url = f"{JIRA_BASE_URL}/search"
        data = {"jql": '"Dev Assignee"  = currentUser() and status = "In Progress"  order by created DESC', "fields": ["summary"]}
        response = self._session.post(url=url, headers=self.headers, json=data)
        return response.json()["issues"]

    def get_approver(self, assignee_email: str) -> str:
        assignee_name = assignee_email.split("@")[0]
        search_pattern = f"Request approved for {assignee_name}"
        url = f"{JIRA_BASE_URL}/search"
        data = {"jql": f'comment ~ "{search_pattern}" order by created DESC', "fields": ["comment"], "maxResults": 1}
        response = self._session.post(url=url, headers=self.headers, json=data)

        comments = response.json()["issues"][0]["fields"]["comment"]["comments"]
        comment_body = [c["body"] for c in comments if search_pattern in c["body"]]
        if not comment_body:
            approver = typer.prompt("Can not detect the last used approver, please provide approver")
        else:
            approver = re.findall("(?<=approver: ).*", comment_body[0])[0]
            logger.info(f"The last used approver are: {approver}")
        return approver

    def get_jira_ticket_id(self) -> str:
        tickets = self.get_in_progress_tickets()
        print(
            tabulate.tabulate(
                [[t.get("key"), t.get("fields", {}).get("summary")] for t in tickets],
                headers=["ID", "Ticket summary"],
                showindex="always",
            )
        )
        jira_ticket_index = typer.prompt("Select a ticket index to request permissions for ", type=int)
        return tickets[jira_ticket_index]["key"]


def get_gcp_project_id(ticket_fields: dict[str, str]) -> str:
    about_field = ticket_fields[ABOUT_FIELD_ID]
    gcp_project_id = re.findall("Project ID: ([0-9]*)", about_field)
    if not gcp_project_id:
        raise Exception(f"Can not extract the GCP project ID from the {about_field=}")
    return gcp_project_id[0]


def get_region(ticket_fields: dict[str, str]) -> str:
    about_field = ticket_fields[ABOUT_FIELD_ID]
    region = re.findall("([a-z]{2}).paloaltonetworks.com", about_field)
    if not region:
        raise Exception(f"Can not extract the region from the {about_field=}")
    return region[0]


def get_jira_token(service: str = "JiraDC", username: str = "GCP-PERMISSIONS") -> str:
    """Return the Jira TOKEN from the Key Chain, or get and save it in case it not exist.

    Args:
        service (str, optional): The service name that the token is stored under in the Key Chain. Defaults to 'JiraDC'.
        username (str, optional): The username that the token is stored under in the Key Chain. Defaults to 'GCP-PERMISSIONS'.
    Returns:
        str: The Jira TOKEN
    """
    jira_token = keyring.get_password(service, username)
    if not jira_token:
        logger.info("""\nAt the first time, you will need to create & enter the Jira Token.
Go to https://jira-dc.paloaltonetworks.com/secure/ViewProfile.jspa?selectedTab=com.atlassian.pats.pats-plugin:jira-user-personal-access-tokens
create the Jira token and past it here.
              """)
        jira_token = getpass.getpass(prompt="Please provide the Jira TOKEN:")
        keyring.set_password(service, username, jira_token)
    return jira_token


def request_permissions_via_slack(region: str, gcp_project_id: str, assignee_email: str, jira_ticket_id: str, approver: str):
    return requests.post(
        url=SLACK_PERMISSION_WEBHOOK_URL,
        headers={"Content-Type": "application/json"},
        verify=False,
        json={
            "region": region,
            "project_id": gcp_project_id,
            "user_id": assignee_email,
            "jira_ticket": jira_ticket_id,
            "approver": approver,
        },
    )


def ask_gcp_permissions():
    try:
        jira_token = get_jira_token()
        client = Client(jira_token)
        ticket_id = client.get_jira_ticket_id()
        ticket_data = client.get_jira_ticket_data(ticket_id, REQUESTED_FIELDS)
        assignee_email = client.get_assignee_email()
        gcp_project_id = get_gcp_project_id(ticket_data)
        region = get_region(ticket_data)
        approver = client.get_approver(assignee_email)
        logger.info(f"{gcp_project_id=}, {region=}, {assignee_email=}, {approver=}")
        request_permissions_via_slack(region, gcp_project_id, assignee_email, ticket_id, approver)
    except Exception:
        jira_token = "TOKEN_REPLACED"  #  hide the jira token in case of printed traceback
        raise
