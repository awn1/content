import os

from slack_sdk import WebClient

SLACK_CHANNEL = 'dmst-secrets'


def get_urls(job_url):
    if job_url:  # the script was triggered from Gitlab
        server_url = os.getenv("CI_SERVER_URL", "https://gitlab.xdr.pan.local")
        namespace = os.getenv("CI_PROJECT_NAMESPACE", "xdr/cortex-content")
        base_url = f"{server_url}/{namespace}/content/-/blob/master"
        username = "Content GitlabCI"
    else:  # the script was triggered from GitHub
        base_url = "https://github.com/demisto/content/blob/master"
        github_repository = os.environ['GITHUB_REPOSITORY']
        github_run_id = os.environ['GITHUB_RUN_ID']
        job_url = f"https://github.com/{github_repository}/actions/runs/{github_run_id}"
        username = "Content circleci"
    return base_url, job_url, username


def create_slack_attachments(color, title, fields, job_url):
    attachment = [{
        'fallback': title,
        'color': color,
        'title': title,
        'title_link': job_url,
        'fields': fields,
    }]
    return attachment


def get_all_github_links(secrets_filenames, matching_secrets, base_url):
    """

    Args:
        secrets_filenames (list): the names of all the files that were found to contain secrets.
        matching_secrets (list): the matching secrets found for the file names.
        base_url (str): the base URL link of the code hosting platform which triggered the command (Gitlab/GitHub).
    Returns:
         List: A list of GitHub links to the files with secrets.
         List: A list of links to the files without the secrets.
    """
    secret_files_links_with_secrets = []
    secret_files_links_no_secrets = []
    for index, secret_file_name in enumerate(secrets_filenames):
        split_secret = secret_file_name.split(':')
        file_name = split_secret[0].strip('.')
        line_number = split_secret[1]
        line_number = "#L{0}".format(line_number)
        secret = matching_secrets[index]
        link_to_file = base_url + file_name + line_number
        file_link = "<{0}|{1} -- {2}>".format(link_to_file, file_name[1:] + line_number, secret)
        secret_files_links_with_secrets.append(file_link)
        secret_files_links_no_secrets.append(link_to_file)

    print(f'secrets_filenames:\n{secret_files_links_no_secrets}\n\nmatching_secrets:\n{matching_secrets}')
    return secret_files_links_with_secrets


def get_fields(secrets_filenames, matching_secrets, base_url):
    """
    This function returns fields for the Slack api call attachments.
    The attachments include links to all files with secrets and a title.
    Args:
        secrets_filenames (list): the names of all the files that were found to contain secrets.
        matching_secrets (list): the matching secrets found for the file names.
        base_url (str): the URL for the gitlab CI job which triggered the script.
    Returns:
         List: Fields for the Slack api call attachments
    """
    secret_files_links = get_all_github_links(secrets_filenames, matching_secrets, base_url)

    entity_fields = []
    if secret_files_links:
        entity_fields.append({
            "title": "{0} - {1}".format("Found Secrets", str(len(secret_files_links))),
            "value": '\n'.join(secret_files_links),
            "short": False
        })
    return entity_fields


def build_link_to_message(response) -> str:
    if response.status_code == 200:
        data: dict = response.data  # type: ignore[assignment]
        channel_id: str = data['channel']
        message_ts: str = data['ts'].replace('.', '')
        return f"https://panw-global.slack.com/archives/{channel_id}/p{message_ts}"
    return ""


def create_attachments_on_failure(secrets_filenames, matching_secrets, message, job_url, base_url):
    print("Extracting build status on failure")
    fields = get_fields(secrets_filenames, matching_secrets, base_url) \
        if secrets_filenames and matching_secrets \
        else get_fields_for_message(message, title='An Error Occurred While Extracting Secrets')
    attachments = create_slack_attachments(color='danger', title='Master Secrets Test - Failure', fields=fields, job_url=job_url)
    return attachments


def create_attachments_on_success(message, job_url):
    print("Extracting build status on success")
    fields = get_fields_for_message(message)
    attachments = create_slack_attachments(color='good', title='Master Secrets Test - Success', fields=fields, job_url=job_url)
    return attachments


def get_fields_for_message(message, title='No Secrets Found'):
    return [{'title': title, 'value': message, 'short': False}]


def slack_notifier(slack_token, secrets_filenames=None, matching_secrets=None, message='', success=False, job_url=None):
    base_url, job_url, username = get_urls(job_url)
    if success:
        attachments = create_attachments_on_success(message, job_url)
    else:
        attachments = create_attachments_on_failure(secrets_filenames, matching_secrets, message, job_url, base_url)

    print(f"Sending Slack messages to #{SLACK_CHANNEL}")
    slack_client = WebClient(token=slack_token)
    response = slack_client.chat_postMessage(
        channel=SLACK_CHANNEL,
        username=username,
        attachments=attachments
    )
    link = build_link_to_message(response)
    print(f'Successfully sent slack message to channel {SLACK_CHANNEL}: {link}')
