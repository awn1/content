import argparse
import itertools
import json
import logging
import os.path
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from slack_sdk import WebClient

from Tests.scripts.common import day_suffix
from Tests.scripts.utils.log_util import install_logging
from Tests.scripts.utils.slack import get_conversations_members_slack, get_slack_usernames_mapping, tag_user

CONTENT_BUILD_STATUS_SPREADSHEET_ID = os.environ["CONTENT_BUILD_STATUS_SPREADSHEET_ID"]
CONTENT_BUILD_STATUS_OPEN_ISSUES_SHEET_NAME = os.getenv("CONTENT_BUILD_STATUS_OPEN_ISSUES_SHEET_NAME", "open issues")
SLACK_TOKEN = os.environ["SLACK_TOKEN"]
DMST_CONTENT_TEAM_ID = os.environ["DMST_CONTENT_TEAM_ID"]

# Define which permissions scopes are required to access google-sheets.
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
# How to filter hidden rows.
SHEET_HIDDEN_ROWS_FILTER = "sheets(data(rowMetadata(hiddenByFilter,hiddenByUser)))"

# Slack profile name entries to extract the username from the profile name.
SLACK_PROFILE_NAME_ENTRIES = [
    "display_name",
    "display_name_normalized",
    "real_name",
    "real_name_normalized",
]

# Priority column mapping.
PRIORITY_STR_TO_INT = {
    "P1": 1,
    "P2": 2,
    "P3": 3,
    "P4": 4,
    "P5": 5,
}
PRIORITY_INT_TO_STR = {
    1: "P1",
    2: "P2",
    3: "P3",
    4: "P4",
    5: "P5",
}
PRIORITY_INT_TO_COLOR = {
    None: "danger",
    1: "danger",
    2: "danger",
    3: "warning",
    4: "warning",
    5: "warning",
}

# sheet cell contains "N/A"
CELL_NOT_AVAILABLE: str = "N/A"


def convert_user_name_to_user_id(user_name: str, members_mapping: list[tuple[str, str]]) -> str:
    if user_name == CELL_NOT_AVAILABLE:
        return user_name
    users_splits = []
    for k in members_mapping:
        if k[0] in user_name:
            user_name = user_name.replace(k[0], "")
            users_splits.append(tag_user(k[1]))
    if trimmed_user_name := user_name.strip(" ,\n"):
        users_splits.append(trimmed_user_name)
    return ",".join(users_splits)


def options_handler() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Script to generate a report for the build machines.")
    parser.add_argument("-o", "--output-path", required=True, help="The path to save the report to.")
    parser.add_argument("--service_account", help="Path to gcloud service account")
    return parser.parse_args()


def find_column(column_name: str, columns: list[str]) -> str:
    return next(filter(lambda column: column_name.lower() in str(column).lower(), columns), column_name)


def main():
    install_logging("find_pack_dependencies_changes.log", logger=logging)
    try:
        args = options_handler()
        output_path = Path(args.output_path)
        client: WebClient = WebClient(token=SLACK_TOKEN)
        date_now = datetime.now(tz=timezone.utc)
        date_fmt = date_now.strftime(f"%B {day_suffix(date_now.day)}")

        if args.service_account:
            logging.info(f"loading credentials from:{args.service_account}")
            creds = None
            if os.path.exists(os.path.expanduser(args.service_account)):
                creds = Credentials.from_service_account_file(os.path.expanduser(args.service_account), scopes=SCOPES)
            service = build("sheets", "v4", credentials=creds)
        else:
            logging.info("loading credentials from attached identity")
            service = build("sheets", "v4")

        # Call the Sheets API
        spreadsheets = service.spreadsheets()
        sheet_open_issues_rows = (
            spreadsheets.values()
            .get(spreadsheetId=CONTENT_BUILD_STATUS_SPREADSHEET_ID, range=CONTENT_BUILD_STATUS_OPEN_ISSUES_SHEET_NAME)
            .execute()
        )

        sheet_properties = service.spreadsheets().get(spreadsheetId=CONTENT_BUILD_STATUS_SPREADSHEET_ID).execute()
        sheet_url = sheet_properties["spreadsheetUrl"]

        sheet_hidden_rows_filter = spreadsheets.get(
            spreadsheetId=CONTENT_BUILD_STATUS_SPREADSHEET_ID,
            ranges=CONTENT_BUILD_STATUS_OPEN_ISSUES_SHEET_NAME,
            fields=SHEET_HIDDEN_ROWS_FILTER,
        ).execute()
        rows_metadata = sheet_hidden_rows_filter["sheets"][0]["data"][0]["rowMetadata"]
        filtered_rows: dict[str, list[int]] = {"shownRows": [], "hiddenRows": []}
        for i, r in enumerate(rows_metadata):
            filtered_rows["hiddenRows" if (r.get("hiddenByFilter")) or (r.get("hiddenByUser")) else "shownRows"].append(i + 1)
        values = sheet_open_issues_rows.get("values", [])

        visible_rows = []
        for e in filtered_rows["shownRows"]:
            if e - 1 < len(values):
                visible_rows.append([e] + values[e - 1])
            else:
                break

        columns = visible_rows[0]
        visible_rows = visible_rows[1:]
        num_columns = len(columns)
        # Padding the data to align the column length
        adjusted_data = [
            map(
                lambda x: x[0],
                itertools.zip_longest(row, itertools.repeat(CELL_NOT_AVAILABLE, num_columns), fillvalue=CELL_NOT_AVAILABLE),
            )
            for row in visible_rows
        ]
        df = pd.DataFrame(adjusted_data, columns=columns)
        if visible_rows:
            message = f"""
{date_fmt}
Current status of the build -
line # in google sheet - date - priority - description - status - assignee
"""
            # Finding the column position by a search on their text, case-insensitive and contains.
            row_id_column = find_column("1", columns)
            date_column = find_column("Date", columns)
            short_description_column = find_column("Short Description", columns)
            priority_column = find_column("P#", columns)
            assignee_column = find_column("Assignee", columns)
            status_column = find_column("Status", columns)
            members = get_conversations_members_slack(client, DMST_CONTENT_TEAM_ID)
            members_mapping = get_slack_usernames_mapping(client, members, False, SLACK_PROFILE_NAME_ENTRIES)

            highest_priority: int | None = None
            for index, row in df.iterrows():
                row_priority = PRIORITY_STR_TO_INT[row[priority_column]]
                highest_priority = row_priority if highest_priority is None else min(highest_priority, row_priority)
                message += (
                    f"• {row[row_id_column]} - {row[date_column]} - {row[priority_column]} - {row[short_description_column]} "
                    f"- {row[status_column]} - {convert_user_name_to_user_id(row[assignee_column], members_mapping)}\n"
                )
            color = PRIORITY_INT_TO_COLOR[highest_priority]
        else:
            color = "good"
            message = f"""
{date_fmt}
Current status of the build - There are not active items :party_blob:
"""

        title: str = ":sheet: Content build status"
        content_fields = [
            {
                "title": "",
                "value": message,
                "short": False,
                "mrkdwn": True,
            }
        ]
        msg = [{"fallback": title, "color": color, "title": title, "title_link": sheet_url, "fields": content_fields}]
        with open(output_path / "slack_msg.txt", "w") as slack_msg_file:
            json.dump(
                msg,
                slack_msg_file,  # noqa
                indent=4,
                default=str,
                sort_keys=True,
            )

    except Exception as err:
        logging.exception(f"failed to generate daily build status:{err!s}")
        sys.exit(1)


if __name__ == "__main__":  # pragma: no cover
    main()
