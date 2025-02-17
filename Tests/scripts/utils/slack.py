import logging
from collections.abc import Iterable
from time import sleep

from retry import retry
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError, SlackClientError
from slack_sdk.web import SlackResponse

logger = logging.getLogger(__name__)

SKIPPED_MESSAGES = [
    "has joined the channel",
    "Due to a high volume of activity, we are not displaying some messages sent by this application",
    "Any member of your organization can now find and join this channel",
]


@retry((SlackApiError,), delay=1, backoff=2)
def get_conversation_history(client: WebClient, channel_name: str, cursor: str | None, request_limit: int = 200) -> SlackResponse:
    return client.conversations_history(channel=channel_name, limit=request_limit, cursor=cursor)


def get_messages_from_slack(client: WebClient, channel_id: str, sleep_interval: int = 5, max_messages: int = 12_000) -> list:
    try:
        messages = []
        cursor = None
        while True:
            result = get_conversation_history(client, channel_id, cursor)
            cursor = result["response_metadata"]["next_cursor"]
            for message in result["messages"]:
                if any(skip_msg in message["text"] for skip_msg in SKIPPED_MESSAGES):
                    continue
                messages.append(message["text"])
            if not cursor or len(messages) >= max_messages or not result["has_more"]:
                break
            sleep(sleep_interval)  # Wait before the next call due to rate limits
        return messages
    except SlackClientError as e:
        logger.error(f"Error while fetching the conversation history: {e}")
    return []


@retry((SlackApiError,), delay=1, backoff=2)
def _get_conversations_members(
    client: WebClient, channel_name: str, cursor: str | None, request_limit: int = 200
) -> SlackResponse:
    return client.conversations_members(channel=channel_name, limit=request_limit, cursor=cursor)


def get_conversations_members_slack(client: WebClient, channel_id: str, sleep_interval: int = 5) -> list:
    try:
        members = []
        cursor = None
        while True:
            result = _get_conversations_members(client, channel_id, cursor)
            cursor = result["response_metadata"]["next_cursor"]
            members.extend(result["members"])
            if not cursor or not result["has_more"]:
                break
            sleep(sleep_interval)  # Wait before the next call due to rate limits
        return members
    except SlackClientError as e:
        logger.error(f"Error while fetching the conversation history: {e}")
    return []


def get_slack_usernames_from_ids(client: WebClient, user_ids: list[str]) -> dict[str, str | None]:
    usernames = {}
    for user_id in user_ids:
        try:
            response = client.users_info(user=user_id)
            user_info = response["user"]
            usernames[user_id] = user_info["name"]
        except SlackApiError as e:
            print(f"Error fetching user {user_id}: {e.response['error']}")
            usernames[user_id] = None
    return usernames


def get_slack_usernames_mapping(
    client: WebClient, user_ids: list[str], allow_bots: bool, profile_name_entries: Iterable[str]
) -> list[tuple[str, str]]:
    usernames = {}
    for user_id in user_ids:
        try:
            response = client.users_info(user=user_id)
            user_info = response["user"]
            if user_info["is_bot"] and not allow_bots:
                continue
            for name_entry in profile_name_entries:
                if profile_entry := user_info["profile"][name_entry]:
                    usernames[profile_entry] = user_info["name"]
        except SlackApiError as e:
            print(f"Error fetching user {user_id}: {e.response['error']}")
            usernames[user_id] = None
    return sorted(usernames.items(), key=lambda item: len(item[0]), reverse=True)


def tag_user(user: str) -> str:
    return f"@{user}"
