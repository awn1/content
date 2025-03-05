import argparse
import json
import sys
from pathlib import Path

import requests
import urllib3

from Tests.scripts.common import get_slack_user_name

ALLOWED_USERS = ["content-bot", "svc -xsoar-gitlab-mirror", "svc-xsoar-gitlab-mirror", "svc-xsoar-gitlab-mir"]


def get_group_members(permission_group: str, github_token: str, verify_ssl: bool) -> list:
    """
    Get the members of a group in github.
    :param permission_group: The name of the group.
    :param github_token: The github token.
    :param verify_ssl: Whether to verify the ssl certificate.
    :return: The members of the group.
    """
    github_endpoint = f"https://api.github.com/orgs/demisto/teams/{permission_group}/members"

    headers = {"Authorization": "Bearer " + github_token} if github_token else {}

    response = requests.get(github_endpoint, headers=headers, verify=verify_ssl)

    if response.status_code not in [200, 201]:
        print(f"Failed in pulling group members:\n{response.text}")
        sys.exit(1)

    permissions_response = response.json()
    group_members = [f.get("login") for f in permissions_response]
    return group_members


def get_on_call_devs(content_roles_path: str) -> list:
    """
    Get the on call devs from the content roles file.
    :param content_roles_path: The path to the content roles file.
    :return: The on call devs.
    """
    return json.loads(Path(content_roles_path).read_text()).get("ON_CALL_DEVS") or []


def main():
    parser = argparse.ArgumentParser(description="User Permissions Check")
    parser.add_argument("-t", "--token", help="Github token", required=False)
    parser.add_argument("-g", "--group", help="The permission group to check in", required=False)
    parser.add_argument("-u", "--user", help="The user to verify his permissions", required=False)
    parser.add_argument("-n", "--name-mapping_path", help="The path to name mapping file", required=True)
    parser.add_argument("-c", "--content_roles", help="The path to the content roles file", required=True)

    args = parser.parse_args()
    github_token = args.token
    verify_ssl = bool(github_token)

    if not verify_ssl:
        urllib3.disable_warnings()

    github_group_members = get_group_members(permission_group=args.group, github_token=github_token, verify_ssl=verify_ssl)
    on_calls = get_on_call_devs(args.content_roles)
    gitlab_group_members = [get_slack_user_name(user, user, args.name_mapping_path) for user in github_group_members]
    gitlab_allowed_users = gitlab_group_members + on_calls + ALLOWED_USERS
    if args.user in gitlab_allowed_users:
        print(f"User '{args.user}' is allowed to trigger")
    else:
        print(f"User '{args.user}' is not allowed to trigger the flow as it is not part of {gitlab_allowed_users}")
        sys.exit(1)


if __name__ == "__main__":
    main()
