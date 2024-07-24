import logging
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
