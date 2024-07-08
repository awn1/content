import argparse
import logging
import os
from typing import Tuple, Any

import gitlab
import requests
from slack_sdk import WebClient
from slack_sdk.web import SlackResponse

logging.basicConfig(level=logging.INFO)

BUILD_CHANNEL = "content-infra-images"  # default value for the Slack channel.
# the default is the id of infra repo in xdr.pan.local
GITLAB_PROJECT_ID = os.getenv("CI_PROJECT_ID", 1701)
# disable-secrets-detection
GITLAB_SERVER_URL = os.getenv("CI_SERVER_URL", "https://gitlab.xdr.pan.local")
SLACK_USERNAME = "Content GitlabCI"
SLACK_WORKSPACE_NAME = os.getenv('SLACK_WORKSPACE_NAME', '')


def construct_slack_msg(
    triggering_workflow, pipeline_url, pipeline_failed_jobs
) -> tuple[list[dict[str, str | list[dict[str, str | bool]] | Any]], Any]:
    """
    Args:
        - triggering_workflow (str): Name of triggering workflow
        - pipeline_url (str): URL of pipeline
        - pipeline_failed_jobs (list): List of failed Gitlab::Job objects

    Returns:
        - A list of Slack message dictionaries and the title of the message.
    """
    title = triggering_workflow
    if pipeline_failed_jobs:
        title += " - Failure"
        color = "danger"
    else:
        title += " - Success"
        color = "good"

    # report failing jobs
    content_fields = []
    failed_jobs_names = {job.name for job in pipeline_failed_jobs}
    if failed_jobs_names:
        content_fields.append(
            {
                "title": f"Failed Jobs - ({len(failed_jobs_names)})",
                "value": "\n".join(failed_jobs_names),
                "short": False,
            }
        )

    slack_msg = [{
        'fallback': title,
        'color': color,
        'title': title,
        'title_link': pipeline_url,
        'fields': content_fields
    }]
    return slack_msg, title


def collect_pipeline_data(gitlab_client, project_id, pipeline_id) -> Tuple[str, list]:
    """
    Args:
        - gitlab_client (Gitlab client object): Gitlab API client
        - project_id (str): ID of Gitlab project
        - pipeline_id (str): ID of Gitlab pipeline

    Returns:
        - The web url of the pipline to access from slack.
        - The failed_jobs script.
    """
    logging.info(f"collect_pipeline_data {project_id=}, {pipeline_id=}")
    project = gitlab_client.projects.get(int(project_id))
    pipeline = project.pipelines.get(int(pipeline_id))
    jobs = pipeline.jobs.list()

    failed_jobs = []
    for job in jobs:
        logging.info(
            f"status of gitlab job with id {job.id} and name {job.name} is {job.status}"
        )
        if job.status == "failed":
            logging.info(f"collecting failed job {job.name}")
            logging.info(
                f'pipeline associated with failed job is {job.pipeline.get("web_url")}'
            )
            failed_jobs.append(job)

    return pipeline.web_url, failed_jobs


def options_handler():
    parser = argparse.ArgumentParser(description="Parser for slack_notifier args")
    parser.add_argument(
        "-u", "--url", help="The gitlab server url", default=GITLAB_SERVER_URL
    )
    parser.add_argument(
        "-p",
        "--pipeline_id",
        help="The pipeline id to check the status of",
        required=True,
    )
    parser.add_argument(
        "-s", "--slack_token", help="The token for slack", required=True
    )
    parser.add_argument(
        "-c", "--ci_token", help="The token for circleci/gitlab", required=True
    )
    parser.add_argument(
        "-ch",
        "--slack_channel",
        help="The slack channel in which to send the notification",
        default=BUILD_CHANNEL,
    )
    parser.add_argument(
        "-gp",
        "--gitlab_project_id",
        help="The gitlab project id",
        default=GITLAB_PROJECT_ID,
    )
    parser.add_argument(
        "-tw",
        "--triggering-workflow",
        help="The type of ci pipeline workflow the notifier is reporting on",
    )
    parser.add_argument(
        "-ofo",
        "--on_fail_only",
        help="Notify via slack only if the pipeline failed",
        default=False,
    )
    options = parser.parse_args()

    return options


def build_link_to_message(response: SlackResponse) -> str:
    logging.info("Building link to message")
    if SLACK_WORKSPACE_NAME and response.status_code == requests.codes.ok:
        data: dict = response.data  # type: ignore[assignment]
        channel_id: str = data['channel']
        message_ts: str = data['ts'].replace('.', '')
        return f"https://{SLACK_WORKSPACE_NAME}.slack.com/archives/{channel_id}/p{message_ts}"
    return ""


def main():
    options = options_handler()
    server_url = options.url
    slack_token = options.slack_token
    ci_token = options.ci_token
    project_id = options.gitlab_project_id
    pipeline_id = options.pipeline_id
    triggering_workflow = options.triggering_workflow
    slack_channel = options.slack_channel
    gitlab_client = gitlab.Gitlab(server_url, private_token=ci_token)

    pipeline_url, pipeline_failed_jobs = collect_pipeline_data(
        gitlab_client, project_id, pipeline_id
    )
    if not options.on_fail_only or pipeline_failed_jobs:
        slack_msg_data, text = construct_slack_msg(
            triggering_workflow, pipeline_url, pipeline_failed_jobs)

        slack_client = WebClient(slack_token)
        response = slack_client.chat_postMessage(
            attachments=slack_msg_data,
            channel=slack_channel, text=text, username=SLACK_USERNAME, link_names=True
        )
        link = build_link_to_message(response)
        logging.info(f'Pipeline {pipeline_id} failed, Successfully sent Slack message to channel {slack_channel} link: {link}')
    else:
        logging.info(
            f'Pipeline {pipeline_id} was successful, no slack message sent.')


if __name__ == "__main__":
    main()
