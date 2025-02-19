import argparse
import random
import sys
import time
import warnings
from collections.abc import Iterable
from datetime import datetime
from time import sleep
from typing import Any

import requests
import urllib3
from google.auth import _default
from google.cloud import storage  # type: ignore[attr-defined]
from slack_sdk import WebClient as SlackWebClient
from urllib3.exceptions import InsecureRequestWarning

from Tests.Marketplace.common import get_json_file
from Tests.scripts.common import BUCKET_UPLOAD_BRANCH_SUFFIX, evaluate_condition, get_slack_user_name
from Tests.scripts.github_client import GithubClient
from Tests.scripts.infra.resources.constants import AUTOMATION_GCP_PROJECT
from Tests.scripts.infra.settings import Settings
from Tests.scripts.infra.xsoar_api import SERVER_TYPE_TO_CLIENT_TYPE, XsiamClient, XsoarClient
from Tests.scripts.utils import logging_wrapper as logging
from Tests.scripts.utils.log_util import install_logging
from Utils.github_workflow_scripts.utils import get_env_var

GITLAB_SERVER_URL = get_env_var("CI_SERVER_URL", "https://gitlab.xdr.pan.local")  # disable-secrets-detection
LOCKS_BUCKET = "xsoar-ci-artifacts"
QUEUE_REPO = "queue"
MACHINES_LOCKS_REPO = "machines_locks"
JOB_STATUS_URL = "{}/api/v4/projects/{}/jobs/{}"  # disable-secrets-detection
PIPELINE_STATUS_URL = "{}/api/v4/projects/{}/pipelines/{}"  # disable-secrets-detection
GITLAB_PROJECT_ID = get_env_var("CI_PROJECT_ID", "1061")  # default is Content
COMMENT_FIELD_NAME = "__comment__"
SLACK_TOKEN = get_env_var("SLACK_TOKEN", "")
SLACK_CHANNEL = get_env_var("WAIT_SLACK_CHANNEL", "dmst-wait-in-line")

urllib3.disable_warnings(InsecureRequestWarning)
warnings.filterwarnings("ignore", _default._CLOUD_SDK_CREDENTIALS_WARNING)
from Tests.scripts.infra.viso_api import VisoAPI  # noqa

VISO_API_URL: str = get_env_var("VISO_API_URL")
VISO_API_KEY = get_env_var("VISO_API_KEY")
CONTENT_TENANTS_GROUP_OWNER = get_env_var("CONTENT_TENANTS_GROUP_OWNER")


def send_slack_notification(slack_client: SlackWebClient, text_list: list[str]):
    """
    Sends a Slack notification with a list of items.

    Args:
        slack_client(SlackWebClient): The Slack client.
        text_list (List[str]): A list of items to be included in the Slack notification.

    """
    try:
        text: str = "\n".join(text_list)
        slack_client.chat_postMessage(channel=SLACK_CHANNEL, text=text)
    except Exception as e:
        logging.info(f"Failed to send Slack notification. Reason: {e!s}")


def options_handler() -> argparse.Namespace:
    """
    Returns: options parsed from input arguments.

    """
    parser = argparse.ArgumentParser(description="Utility for lock machines")
    parser.add_argument("--service_account", help="Path to gcloud service account.")
    parser.add_argument("--gcs_locks_path", help="Path to lock repo.")
    parser.add_argument("--ci_job_id", help="the job id.")
    parser.add_argument("--ci_pipeline_id", help="the pipeline id.")
    parser.add_argument("--cloud_servers_path", help="Path to secret cloud server metadata file.")
    parser.add_argument("--flow_type", help="The flow type.")
    parser.add_argument("--server_type", help="The server type.")
    parser.add_argument("--gitlab_status_token", help="gitlab token to get the job status.")
    parser.add_argument("--response_machine", help="file to update the chosen machine.")
    parser.add_argument("--lock_machine_name", help="a machine name to lock the specific machine")
    parser.add_argument("--lock_timeout", help="the lock timeout, set to 0 to disable the lock timeout.")
    parser.add_argument(
        "--machines-count-minimum-condition",
        help="The minimum condition to locked machines count to allow the build to properly operate.",
    )
    parser.add_argument(
        "--machines-count-timeout-condition", help="The condition to keep searching for machines until the timeout is reached."
    )
    parser.add_argument("--github_token", help="The github token.")
    parser.add_argument("--branch_name", help="The name of the branch.")
    parser.add_argument("--name-mapping_path", help="Path to name mapping file.", required=False)
    parser.add_argument("--chosen_machine_path", help="File to update if a machine is chosen by labels.")
    options = parser.parse_args()
    return options


def get_queue_locks_details(storage_client: storage.Client, bucket_name: str, prefix: str) -> list[dict]:
    """
    get a list of all queue locks files.
    Args:
        storage_client(storage.Client): The GCP storage client.
        bucket_name(str): the bucket name.
        prefix(str): the prefix to search for specific files.

    Returns: list of dicts with the job-id and the time_created of the lock file.

    """
    blobs = storage_client.list_blobs(bucket_name)
    files = []
    found = False
    for blob in blobs:
        if blob.name.startswith(prefix):
            found = True
            files.append({"name": blob.name.strip(prefix), "time_created": blob.time_created})
        elif found:
            break
    return files


def get_machines_locks_details(
    storage_client: storage.Client,
    bucket_name: str,
    lock_repository_name: str,
    machines_lock_repo: str,
) -> list[dict]:
    """
    get a list of all machines locks files.
    Args:
        storage_client(storage.Client): The GCP storage client.
        bucket_name(str): the bucket name.
        lock_repository_name(str):  the lock_repository_name name.
        machines_lock_repo(str): the machines_lock_repo name.

    Returns: list of dicts with the job-id and the time_created of the lock file.

    """
    blobs = storage_client.list_blobs(bucket_name)
    files = []
    found = False
    for blob in blobs:
        if blob.name.startswith(lock_repository_name):
            found = True
            if blob.name.startswith(f"{lock_repository_name}/{machines_lock_repo}"):
                lock_file_name = blob.name.split("/")[-1]
                if lock_file_name:
                    if len(lock_file_name_separate := lock_file_name.split("-lock-")) == 3:
                        project_id, machine_name, job_id = lock_file_name_separate
                        is_old_lock = False
                    else:
                        machine_name, job_id = lock_file_name_separate
                        project_id = "1061"  # default is Content
                        is_old_lock = True
                    files.append(
                        {
                            "project_id": project_id,
                            "machine_name": machine_name,
                            "job_id": job_id,
                            "old_lock": is_old_lock,
                        }
                    )
        elif found:
            break
    return files


def check_job_status(
    token: str,
    project_id: str,
    job_id: str,
    num_of_retries: int = 5,
    interval: float = 30.0,
) -> str | None:
    """
    get the status of a job in gitlab.

    Args:
        project_id(str): the project id.
        token(str): the gitlab token.
        job_id(str): the job id to check.
        num_of_retries (int): num of retries to establish a connection to gitlab in case of a connection error.
        interval (float): the interval to wait before trying to establish a connection to gitlab each attempt.

    Returns: the status of the job.

    """
    if "_" in job_id:
        job_id = job_id.split("_")[1]
        user_endpoint = JOB_STATUS_URL.format(GITLAB_SERVER_URL, project_id, job_id)
    else:
        user_endpoint = PIPELINE_STATUS_URL.format(GITLAB_SERVER_URL, project_id, job_id)
    headers = {"PRIVATE-TOKEN": token}

    for attempt_num in range(1, num_of_retries + 1):
        try:
            logging.debug(
                f"Try to get the status of job ID {job_id} from project id {project_id} in attempt number"
                f"{attempt_num},user_endpoint: {user_endpoint}"
            )
            response = requests.get(user_endpoint, headers=headers)
            response_as_json = response.json()
            logging.debug(f"{user_endpoint=} raw response={response_as_json} for {job_id=} of {project_id=}")
            return response_as_json.get("status")
        except requests.ConnectionError as error:
            logging.error(f"Got connection error: {error} in attempt number {attempt_num}")
            if attempt_num == num_of_retries:
                raise error
            logging.debug(f"sleeping for {interval} seconds to try to re-establish gitlab connection")
            time.sleep(interval)
    return None


def remove_file(storage_bucket: Any, file_path: str):
    """
    deletes a file from the bucket
    Args:
        storage_bucket(google.cloud.storage.bucket.Bucket): google storage bucket where lock machine is stored.
        file_path(str): the path of the file.
    """
    blob = storage_bucket.blob(file_path)
    try:
        blob.delete()
    except Exception as err:
        logging.error(f"when we try to delete a build_from_queue = {file_path}, we get an error: {err!s}")


def lock_machine(storage_bucket: Any, lock_repository_name: str, machine_name: str, job_id: str):
    """
    create a lock machine file
    Args:
        storage_bucket(google.cloud.storage.bucket.Bucket): google storage bucket where lock machine is stored.
        lock_repository_name(str) the lock repository name.
        machine_name: the machine to lock.
        job_id(str): the job id that locks.
    """
    blob = storage_bucket.blob(
        f"{lock_repository_name}/{MACHINES_LOCKS_REPO}/{GITLAB_PROJECT_ID}-lock-{machine_name}-lock-{job_id}"
    )
    blob.upload_from_string("")


def adding_build_to_the_queue(storage_bucket: Any, lock_repository_name: str, job_id: str):
    """
    create a lock machine file
    Args:
        storage_bucket(google.cloud.storage.bucket.Bucket): google storage bucket where lock machine is stored.
        lock_repository_name(str): the lock repository name.
        job_id(str): the job id to be added to the queue.
    """
    blob = storage_bucket.blob(f"{lock_repository_name}/{QUEUE_REPO}/{GITLAB_PROJECT_ID}-queue-{job_id}")
    blob.upload_from_string("")


def get_my_place_in_the_queue(
    slack_client: SlackWebClient,
    storage_client: storage.Client,
    gcs_locks_path: str,
    job_id: str,
    my_prev_place: int | None = None,
) -> tuple[int, str]:
    """
    get the place in the queue for job-id by the time-created of lock-file time-created.
    Args:
        slack_client(SlackWebClient): The Slack client.
        storage_client(storage.Client): The GCP storage client.
        gcs_locks_path(str): the lock repository name.
        job_id(str): the job id to check.
        my_prev_place(int): the previous place in the queue of the job-id

    Returns: the place in the queue.

    """
    logging.debug("getting all builds in the queue")
    builds_in_queue = get_queue_locks_details(
        storage_client=storage_client,
        bucket_name=LOCKS_BUCKET,
        prefix=f"{gcs_locks_path}/{QUEUE_REPO}/",
    )
    # sorting the files by time_created
    sorted_builds_in_queue: list[dict] = sorted(builds_in_queue, key=lambda d: d["time_created"], reverse=False)

    my_place_in_the_queue = next(
        (index for (index, d) in enumerate(sorted_builds_in_queue) if d["name"] == f"{GITLAB_PROJECT_ID}-queue-{job_id}"),
        None,
    )
    if my_place_in_the_queue is None:
        raise Exception("Unable to find the queue lock file, probably a problem creating the file")
    previous_build_in_queue = ""
    if my_place_in_the_queue > 0:
        previous_build_in_queue = sorted_builds_in_queue[my_place_in_the_queue - 1].get("name")  # type: ignore[assignment]

    try:
        if my_place_in_the_queue != my_prev_place:
            send_slack_notification(
                slack_client,
                [
                    f"{gcs_locks_path}",
                    f"{datetime.now().strftime('%Y-%m-%dT%H:%M:%S.%f')}",
                    f"Job ID: {job_id}",
                    f"{len(builds_in_queue)}",
                ],
            )
    except Exception as e:
        logging.info(f"Failed to send Slack notification. Reason: {e!s}")

    return my_place_in_the_queue, previous_build_in_queue


def try_to_lock_machine(
    storage_bucket: Any,
    machine: str,
    machines_locks: list,
    gitlab_status_token: str,
    gcs_locks_path: str,
    job_id: str,
) -> str:
    """
    try to lock machine for the job
    Args:
        storage_bucket(google.cloud.storage.bucket.Bucket): google storage bucket where lock machine is stored.
        machine(str): the machine to lock.
        machines_locks(srt): all the exiting lock files.
        gitlab_status_token(str): the gitlab token.
        gcs_locks_path(str): the lock repository name.
        job_id(str): the job id to check.

    Returns: the machine name if locked.

    """
    lock_machine_name = ""
    job_id_of_the_existing_lock, project_id_of_the_existing_lock, is_old_lock = next(
        ((d["job_id"], d["project_id"], d["old_lock"]) for d in machines_locks if d["machine_name"] == machine),
        (None, None, None),
    )

    if job_id_of_the_existing_lock and project_id_of_the_existing_lock:  # This means there might be a build using this machine
        logging.debug(
            f"There is a lock file for job id: {job_id_of_the_existing_lock}"
            f"from project id: {project_id_of_the_existing_lock}"
        )
        job_id_of_the_existing_lock_status = check_job_status(
            gitlab_status_token,
            project_id_of_the_existing_lock,
            job_id_of_the_existing_lock,
        )
        logging.debug(
            f"the status of job id: {job_id_of_the_existing_lock}"
            f"from project id: {project_id_of_the_existing_lock} is: {job_id_of_the_existing_lock_status}"
        )
        if job_id_of_the_existing_lock_status != "running":
            # The job holding the machine is not running anymore, it is safe to remove its lock from the machine.
            logging.info(
                f"Found job [{job_id_of_the_existing_lock}] from project id [{project_id_of_the_existing_lock}] status: "
                f"{job_id_of_the_existing_lock_status} that's locking machine: {machine}. Deleting the lock."
            )

            file_name_to_remove = (
                f"{machine}-lock-{job_id_of_the_existing_lock}"
                if is_old_lock
                else f"{project_id_of_the_existing_lock}-lock-{machine}-lock-{job_id_of_the_existing_lock}"
            )
            remove_file(
                storage_bucket,
                file_path=f"{gcs_locks_path}/{MACHINES_LOCKS_REPO}/{file_name_to_remove}",
            )
        else:
            return lock_machine_name
    else:
        # machine found! create lock file
        logging.debug("There is no existing lock file")
    logging.info(f"Locking machine {machine}")
    lock_machine(storage_bucket, gcs_locks_path, machine, job_id)
    lock_machine_name = machine
    return lock_machine_name


def get_and_lock_all_needed_machines(
    storage_client: storage.Client,
    storage_bucket: storage.bucket.Bucket,
    list_machines: list[str],
    gcs_locks_path: str,
    job_id: str,
    gitlab_status_token: str,
    lock_timeout: float,
    machines_count_timeout_condition: str,
    machines_count_minimum_condition: str,
    sleep_interval: int = 60,
):
    """
    get the requested machines and locked them to the job-id.
    The function will wait (busy waiting) until it was able to successfully lock the requested number of machines.
    In between runs, it will sleep for a minute to allow other builds to finish.
    Args:
        storage_client(storage.Client): The GCP storage client.
        storage_bucket(google.cloud.storage.bucket.Bucket): google storage bucket where lock machine is stored.
        list_machines (list): all the exiting machines.
        gcs_locks_path(str): the lock repository name.
        job_id(str): the job id to lock.
        gitlab_status_token(str): the gitlab token.
        lock_timeout(float): the lock timeout, set to 0 to disable the lock timeout.
        machines_count_minimum_condition(str): The minimum condition to locked machines count to allow the build to
        properly operate.
        machines_count_timeout_condition(str): The condition to keep searching for machines until the timeout is reached.
        sleep_interval(int): the interval to sleep between runs.

    Returns: the machine name if locked.
    """

    logging.debug("getting all machines lock files")
    hundred_percent = len(list_machines)
    locked_machine_list: list[str] = []
    start_time = time.time()
    while not evaluate_condition(len(locked_machine_list), machines_count_timeout_condition, hundred_percent):
        busy_machines = []
        for machine in list_machines:
            machines_locks = get_machines_locks_details(storage_client, LOCKS_BUCKET, gcs_locks_path, MACHINES_LOCKS_REPO)
            lock_machine_name = try_to_lock_machine(
                storage_bucket,
                machine,
                machines_locks,
                gitlab_status_token,
                gcs_locks_path,
                job_id,
            )

            # We managed to lock a machine
            if lock_machine_name:
                locked_machine_list.append(lock_machine_name)
                if evaluate_condition(len(locked_machine_list), machines_count_timeout_condition, hundred_percent):
                    logging.info(f"Locked {len(locked_machine_list)} machines, condition: {machines_count_timeout_condition}")
                    break
            else:
                # If the machine was busy we save it to try it again later
                busy_machines.append(machine)

        # Next round we will try and lock only the busy machines
        list_machines = busy_machines

        if evaluate_condition(len(locked_machine_list), machines_count_timeout_condition, hundred_percent):
            logging.info(f"Locked {len(locked_machine_list)} machines, condition: {machines_count_timeout_condition}")
            break

        if lock_timeout and lock_timeout < time.time() - start_time:
            logging.warning(f"Lock timeout of {lock_timeout:.2f} seconds reached")
            break

        logging.debug(f"Locked {len(locked_machine_list)} machines, sleeping for {sleep_interval} seconds")
        sleep(sleep_interval)

    if not evaluate_condition(len(locked_machine_list), machines_count_minimum_condition, hundred_percent):
        logging.error(
            f"Failed to lock the minimum number of machines. Locked {len(locked_machine_list)} machines, "
            f"condition: {machines_count_minimum_condition}"
        )
        sys.exit(1)

    return locked_machine_list


def create_list_of_machines_to_run(lock_machine_name: str, test_machines: Iterable[str]) -> list[str]:
    """
    get the list of the available machines (or one specific given machine for debugging).
    Args:
        lock_machine_name(str): the name of the file with the list of the test machines.
        test_machines(Iterable[str]): the list of the available machines.

    Returns:
        list: the machines list.

    Returns: the machines list.
    """
    if lock_machine_name:  # For debugging: We got a name of a specific machine to use.
        logging.info(f"trying to lock the given machine: {lock_machine_name}")
        return [lock_machine_name]

    logging.info("getting all machine names")  # We are looking for a free machine in all the available machines.
    list_machines = list(test_machines)
    random.shuffle(list_machines)

    return list_machines


def wait_for_build_to_be_first_in_queue(
    slack_client: SlackWebClient,
    storage_client: storage.Client,
    storage_bucket: storage.bucket.Bucket,
    gcs_locks_path: str,
    job_id: str,
    gitlab_status_token: str,
):
    """
    this function will wait (busy waiting) for the current build to be the first in the queue,
    in case he is not the first it will check if the build before it is alive and cancel it in case it is not,
    between runs it will sleep for a random amount of seconds.
    Args:
        slack_client(SlackWebClient): The Slack client.
        storage_client(storage.Client): The GCP storage client.
        storage_bucket(google.cloud.storage.bucket.Bucket): google storage bucket where lock machine is stored.
        gcs_locks_path(str): the lock repository name.
        job_id(str): the job id to check.
        gitlab_status_token(str): the gitlab token.
    """
    sleep(random.randint(1, 3))
    my_place_in_the_queue = None
    while True:
        my_place_in_the_queue, previous_build = get_my_place_in_the_queue(
            slack_client, storage_client, gcs_locks_path, job_id, my_place_in_the_queue
        )
        logging.info(f"My place in the queue is: {my_place_in_the_queue}")

        if my_place_in_the_queue == 0:
            break

        if len(previous_build_separate := previous_build.split("-queue-")) > 1:
            previous_project_id, previous_job_id = previous_build_separate
        else:
            previous_project_id = "1061"  # default is Content
            previous_job_id = previous_build_separate[0]

        # we check the status of the build that is ahead of me in the queue
        previous_build_status = check_job_status(gitlab_status_token, previous_project_id, previous_job_id)
        if previous_build_status != "running":
            # delete the lock file of the build because it's not running
            remove_file(storage_bucket, f"{gcs_locks_path}/{QUEUE_REPO}/{previous_build}")
        else:
            sleep(random.randint(8, 13))


def get_viso_tenants() -> dict[str, dict]:
    tenants = {}
    if not VISO_API_URL or not VISO_API_KEY:
        logging.error("VISO_API_URL or VISO_API_KEY env vars are not set.")
    else:
        viso_api = VisoAPI(VISO_API_URL, VISO_API_KEY)
        try:
            tenants_list = viso_api.get_all_tenants(CONTENT_TENANTS_GROUP_OWNER)
            tenants = {tenant["lcaas_id"]: tenant for tenant in tenants_list}
        except Exception as e:
            logging.debug(f"Failed to get tenants: {e}")
            logging.error("Failed to get tenants")
            tenants = {}

    return tenants


def validate_connection_for_machines(machine_list: list[str], cloud_servers: dict[str, dict], token_map: dict[str, str]):
    """
    For relevant server types, gets the cloud machine API key from GSM and checks it.
    If it is not valid or doesn't exist, creates one and saves it to GSM.

    Raises InvalidAPIKey Exception if creating a new API key was unsuccessful.
    """
    for cloud_machine in machine_list:
        conf = cloud_servers.get(cloud_machine)
        if client_type := SERVER_TYPE_TO_CLIENT_TYPE.get(conf.get("server_type")):  # type: ignore[union-attr, arg-type]
            xsoar_admin_user = Settings.xsoar_admin_user
            client = client_type(
                xsoar_host=conf.get("base_url").replace("https://api-", "").replace("/", ""),  # type: ignore[union-attr]
                xsoar_user=xsoar_admin_user.username,
                xsoar_pass=xsoar_admin_user.password,
                tenant_name=cloud_machine,
                project_id=AUTOMATION_GCP_PROJECT,
            )
            client_token = token_map.get(client.tenant_name)
            client.login_using_gsm(client_token)


def generate_tenant_token_map(tenants_data: dict[str, dict]) -> dict:
    """
    Generates a dictionary mapping tenant IDs to their corresponding collection tokens.

    Args:
        tenants_data (dict[str, dict]): A dictionary where keys are tenant identifiers,
                                        and values are dictionaries containing tenant data.

    Returns:
        dict: A dictionary mapping tenant IDs to their corresponding
              collection tokens for tenants with the product type "XSIAM".
    """
    data_dict = {
        f"qa2-test-{item['lcaas_id']}": item["xdr_http_collection_token"]
        for item in tenants_data.values()
        if item["product_type"] == XsiamClient.PRODUCT_TYPE
    }
    if data_dict:
        logging.info(f"Successfully created tenants token dictionary. Found {len(data_dict)} tenants tokens.")
    return data_dict


def get_github_pr_labels(github_client: GithubClient, pr_number: int):
    """
    Fetches the labels of a GitHub pull request using a GithubClient instance.
    Args:
        github_client: An instance of GithubClient to interact with the GitHub API.
        pr_number: Pull request number.

    Returns:
        List of label names if successful, otherwise logs an error message.
    """
    try:
        return github_client.get_github_pr_labels(pr_number)
    except Exception as e:
        if "Failed to fetch labels:" in str(e):
            logging.info(f"Failed to fetch labels to the pr number {pr_number}.")
        else:
            logging.info(f"Got the following error when trying to contact Github: {e!s}")


def get_pr_number(github_client: GithubClient, branch_name: str) -> int | None:
    """
    Retrieves the PR number associated with a given branch using a GithubClient instance.
    Args:
        github_client: An instance of GithubClient to interact with the GitHub API.
        branch_name: The branch name to look up.

    Returns:
        The PR number if found, otherwise None.
    """
    try:
        return github_client.get_pr_number_from_branch_name(branch_name)
    except Exception as e:
        if "Did not find the PR" in str(e):
            logging.info(f"Did not find the associated PR with the branch {branch_name}.")
        else:
            logging.info(f"Got the following error when trying to contact Github: {e!s}")

    return None


def get_pr_author(github_client: GithubClient, pr_number: int):
    """
    Fetches the GitHub username of the author of a given pull request.
    Args:
        github_client: An instance of GithubClient to interact with the GitHub API.
        pr_number: Pull request number.

    Returns:
        The username of the PR author.
    """
    try:
        return github_client.get_pr_author(pr_number)
    except Exception as e:
        if "Failed to fetch PR author" in str(e):
            logging.info(f"Failed to fetch PR author of the pr number {pr_number}.")
        else:
            logging.info(f"Got the following error when trying to contact Github: {e!s}")


def get_chosen_machines_by_labels(github_client: GithubClient, labels: list, pr_number: int, options: argparse.Namespace) -> str:
    """
    Determines the chosen machine's flow type based on GitHub PR labels.
    Checks for specific XSOAR or XSIAM labels and extracts the flow type. If found, maps the GitHub PR author
    to a Slack username and writes the result to a file.

    Args:
        github_client (GithubClient): GitHub client instance.
        labels (list): Labels attached to the pull request.
        pr_number (int): Pull request number.
        options (dict): Config options.

    Returns:
        str: The flow type (Slack username or extracted name), or an empty string if no match is found.
    """
    name_mapping_path = options.name_mapping_path
    server_type = options.server_type
    if server_type == XsoarClient.SERVER_TYPE:
        CHOSEN_MACHINE_USER = "chosen-machine-xsoar-user"
        CHOSEN_MACHINE_FLOW_TYPE = "chosen-machine-xsoar"
    elif server_type == XsiamClient.SERVER_TYPE:
        CHOSEN_MACHINE_USER = "chosen-machine-xsiam-user"
        CHOSEN_MACHINE_FLOW_TYPE = "chosen-machine-xsiam"

    flow_type = ""
    for label in labels:
        if CHOSEN_MACHINE_USER == label:
            logging.info(f"Found custom machine label: {label}")
            github_username = get_pr_author(github_client, pr_number)
            gitlab_username = get_slack_user_name(name=github_username, default="not found", name_mapping_path=name_mapping_path)
            logging.info(f"{github_username=} and {gitlab_username=}")
            if gitlab_username == "not found":
                logging.info(f"gitlab username of github username {github_username} not found.")
            else:
                flow_type = gitlab_username
            break

        elif CHOSEN_MACHINE_FLOW_TYPE in label:
            logging.info(f"Found custom flow type label: {label}")
            parts = label.split("-")
            if len(parts) >= 4:
                flow_type_arr = parts[3:]
                flow_type = "".join(flow_type_arr)
            else:
                logging.info(
                    f"The label {label} is not valid. The correct format is: 'chosen-machine-<MACHINE_TYPE>-<FLOW_TYPE>'."
                )
            break

    if flow_type:
        logging.info(f"Found chosen-machine label. The flow_type is {flow_type}.")
        with open(options.chosen_machine_path, "w") as f:
            f.write(flow_type)

    return flow_type


def get_chosen_machines(options) -> str:
    github_client = GithubClient(options.github_token)
    branch_name = options.branch_name
    if BUCKET_UPLOAD_BRANCH_SUFFIX in branch_name:
        branch_name = branch_name[: branch_name.find(BUCKET_UPLOAD_BRANCH_SUFFIX)]

    pr_number = get_pr_number(github_client, branch_name)
    if not pr_number:
        return ""

    labels = get_github_pr_labels(github_client, pr_number)
    if not labels:
        return ""

    flow_type_by_label: str = get_chosen_machines_by_labels(github_client, labels, pr_number, options)
    return flow_type_by_label


def main():
    start_time = time.time()
    install_logging("lock_cloud_machines.log", logger=logging)
    options = options_handler()
    flow_type = options.flow_type
    flow_type_by_label: str = get_chosen_machines(options)
    if flow_type_by_label:
        flow_type = flow_type_by_label

    logging.info(
        f"Starting to search for a CLOUD machine/s to lock, flow type: {flow_type}, " f"server type: {options.server_type}"
    )
    storage_client = storage.Client.from_service_account_json(options.service_account)
    storage_bucket = storage_client.bucket(LOCKS_BUCKET)

    cloud_servers_path_json = get_json_file(options.cloud_servers_path)
    available_machines = {}
    for machine, machine_details in cloud_servers_path_json.items():
        if (
            machine != COMMENT_FIELD_NAME
            and machine_details["enabled"]
            and machine_details["flow_type"] == flow_type
            and machine_details["server_type"] == options.server_type
        ):
            available_machines[machine] = machine_details

    if not available_machines:
        logging.error(f"No available machines found for the given flow type: {flow_type} and server type: {options.server_type}")
        sys.exit(1)

    if options.lock_machine_name:
        if options.lock_machine_name not in available_machines:
            logging.error(f"The machine name {options.lock_machine_name} is not in the available machines list")
            sys.exit(1)
        logging.info(f"Trying to lock the specific machine: {options.lock_machine_name}")
    else:
        logging.info(f"Available machines: {','.join(available_machines.keys())}")
        logging.info(f"Number of available machines: {len(available_machines)}")

    lock_timeout: float = float(options.lock_timeout)
    if lock_timeout > 0:
        logging.info(f"Lock timeout: {lock_timeout:.2f} seconds")
    else:
        logging.info("Lock timeout is disabled")
        lock_timeout = float("inf")

    logging.info(f"machines_count_timeout_condition: {options.machines_count_timeout_condition}")
    logging.info(f"machines_count_minimum_condition: {options.machines_count_minimum_condition}")

    if not evaluate_condition(len(available_machines), options.machines_count_minimum_condition, len(available_machines)):
        logging.error(
            f"Won't be able to lock the minimum number of machines. Available machines: {len(available_machines)}, "
            f"condition: {options.machines_count_minimum_condition}"
        )
        sys.exit(1)

    logging.info(f"job_id={options.ci_job_id} " f"pipeline_id={options.ci_pipeline_id}")
    if options.ci_job_id:
        options.ci_job_id = f"{options.ci_pipeline_id}_{options.ci_job_id}"
    else:
        options.ci_job_id = options.pipeline_id
    logging.info(f"Adding job_id/pipeline_id:{options.ci_job_id} to the queue")
    adding_build_to_the_queue(storage_bucket, options.gcs_locks_path, options.ci_job_id)
    slack_client: SlackWebClient = SlackWebClient(token=SLACK_TOKEN)

    # running until the build is the first in queue
    wait_for_build_to_be_first_in_queue(
        slack_client,
        storage_client,
        storage_bucket,
        options.gcs_locks_path,
        options.ci_job_id,
        options.gitlab_status_token,
    )

    logging.info("Starting to search for available machine")

    list_machines = create_list_of_machines_to_run(
        options.lock_machine_name,
        available_machines.keys(),
    )

    lock_machine_list = get_and_lock_all_needed_machines(
        storage_client,
        storage_bucket,
        list_machines,
        options.gcs_locks_path,
        options.ci_job_id,
        options.gitlab_status_token,
        lock_timeout,
        options.machines_count_timeout_condition,
        options.machines_count_minimum_condition,
    )

    # remove build from queue
    remove_file(
        storage_bucket,
        file_path=f"{options.gcs_locks_path}/{QUEUE_REPO}/{GITLAB_PROJECT_ID}-queue-{options.ci_job_id}",
    )

    with open(options.response_machine, "w") as f:
        f.write(f"{','.join(lock_machine_list)}")

    tenants = get_viso_tenants()
    tenant_token_map = generate_tenant_token_map(tenants_data=tenants)
    validate_connection_for_machines(lock_machine_list, cloud_servers_path_json, tenant_token_map)

    end_time = time.time()
    duration_minutes = (end_time - start_time) // 60
    send_slack_notification(
        slack_client,
        [
            "Lock Duration:",
            f"{datetime.now().strftime('%Y-%m-%dT%H:%M:%S.%f')}",
            f"{options.gcs_locks_path}",
            f"Job ID: {options.ci_job_id}",
            "Duration:",
            f"{duration_minutes}",
        ],
    )
    send_slack_notification(
        slack_client,
        [
            f"{options.gcs_locks_path}",
            f"{datetime.now().strftime('%Y-%m-%dT%H:%M:%S.%f')}",
            f"Job ID: {options.ci_job_id}",
            "Available machines:",
            f"{len(available_machines)}",
        ],
    )


if __name__ == "__main__":
    main()
