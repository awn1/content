import argparse
import logging
from collections.abc import Iterable

import json5
import requests
from google.api_core.exceptions import NotFound

from SecretActions.google_secret_manager_handler import (
    LABELS,
    SECRET_NAME,
    SYNC_GSM_LABEL,
    GoogleSecreteManagerModule,
    SecretLabels,
)

CONTENT_REPO_URL = "https://api.github.com/repos/demisto/content"
# The max limit for the PRs API is 100, we use this variable to get more if it's 5 for example will get the last 500 PRs
GET_PRS_ITERATIONS = 3


def get_latest_merged() -> tuple[list[int], list[int]]:
    """
    Get the latest merged PR numbers, divided into 2 lists
    :return: A list of the latest PRs from Github
    """
    latest_prs = []
    url = f"{CONTENT_REPO_URL}/pulls"
    # page starts at 1 for Github API
    for i in range(1, GET_PRS_ITERATIONS + 1):
        params = {
            "sort": "updated",
            "direction": "desc",
            "per_page": 100,
            "page": i,
            "state": "closed",
        }
        try:
            response = requests.request("GET", url, params=params, verify=False)  # type: ignore
            response.raise_for_status()
        except Exception as exc:
            raise Exception(f"Could not get merged PRs from Git API, error: {exc}")
        latest_prs.extend(response.json())
    pr_numbers_with_label, pr_numbers_without_label = filter_pr_by_label(latest_prs)
    return pr_numbers_with_label, pr_numbers_without_label


def filter_pr_by_label(latest_prs: list[dict]):
    """Filter the pr list by a the SYNC_GSM_LABEL label

    Args:
        latest_prs (list[dict]): A list of the latest PRs

    """
    pr_numbers_with_label = []
    pr_numbers_without_label = []
    for pr in latest_prs:
        pr_number = pr.get("number")
        if does_pr_contain_gsm_label(pr):
            pr_numbers_with_label.append(pr_number)
        else:
            pr_numbers_without_label.append(pr_number)

    return pr_numbers_with_label, pr_numbers_without_label


def does_pr_contain_gsm_label(pr: dict):
    """Returns true if pr contains the 'sync-gsm' label, else false
    Args:
        pr (dict): pr details
    """
    labels = pr.get("labels", [])
    for label_details in labels:
        if label_details.get("name") == SYNC_GSM_LABEL:
            return True

    return False


def merge_dev_secrets(
    dev_secrets_to_merge: list[dict],
    project_id_prod: str,
    secret_conf: GoogleSecreteManagerModule,
) -> list[str]:
    """
    Merges dev secrets to the main store
    :param dev_secrets_to_merge: A list of dev secrets to add to the main store
    :param project_id_prod: The project ID in GSM we want to push secrets to.
    :param secret_conf: The GSM object to handle GSM API operations
    :return: A list of names of secrets that were merged
    """
    merged_dev_secrets_names = []
    for dev_secret in dev_secrets_to_merge:
        dev_secret_name = dev_secret.pop(SECRET_NAME)
        dev_secret_labels = dev_secret.pop(LABELS)

        merged_dev_secrets_names.append(dev_secret_name)
        main_secret_name = dev_secret_name.split("__", 1)[-1]
        labels_to_remove = [SecretLabels.DEV_SECRET.value, SecretLabels.PR_NUMBER.value]
        main_secret_labels = {key: value for key, value in dev_secret_labels.items() if key not in labels_to_remove}
        try:
            # Checks if the main secret exist in our store
            secret_conf.get_secret(main_secret_name, project_id_prod)
        except NotFound:
            # Adding new secret to main store
            secret_conf.create_secret(main_secret_name, project_id_prod, main_secret_labels)
            logging.debug(f'Adding a new secret to prod: "{main_secret_name}"')

        # Add a new version to master secret
        secret_conf.add_secret_version(main_secret_name, json5.dumps(dev_secret, quote_keys=True), project_id_prod)
        logging.info(f'dev secret "{dev_secret_name}" was merged to "{main_secret_name}" on prod')
    return merged_dev_secrets_names


def filter_secrets_by_pr_label(
    dev_secrets: list[dict], merged_pr_numbers_with_label: list[int], merged_pr_numbers_without_label: list[int]
):
    """Returns two lists of dev secrets that should be merged to prod, and dev secrets that should be deleted"""

    secrets_to_update = []
    secrets_to_delete = []
    for secret in dev_secrets:
        try:
            pr_number = int(secret.get(LABELS, {}).get(SecretLabels.PR_NUMBER.value))
            if pr_number in merged_pr_numbers_with_label and validate_secret(
                secret,
                ("name", "params"),  # type: ignore
            ):
                secrets_to_update.append(secret)
                logging.info(
                    f"Collected the secret '{secret.get(SECRET_NAME)}' from dev in order to "
                    "merge it to prod and to delete it from dev"
                )

            if pr_number in merged_pr_numbers_without_label:
                secrets_to_delete.append(secret)
                logging.info(f"Collected the secret '{secret.get(SECRET_NAME)}' from dev in order to delete it from dev")
        except TypeError:
            logging.info(f"No label of '{SecretLabels.PR_NUMBER}' was found, skipping the secret {secret.get(SECRET_NAME)}.")
    return secrets_to_update, secrets_to_delete


def get_secrets_name(dev_secrets: list[dict]):
    """Returns a list of the secrets name from a list of secrets"""
    secrets_name = []
    for dev_secret in dev_secrets:
        secrets_name.append(dev_secret.get(SECRET_NAME))

    return secrets_name


def delete_dev_secrets(
    secrets_to_delete: Iterable[str],
    secret_conf: GoogleSecreteManagerModule,
    project_id: str,
):
    """
    Deletes the merged dev secret from our dev store
    :param secrets_to_delete: An iterable of secret names that need to be deleted
    :param secret_conf: The GSM object to handle GSM API operations
    :param project_id: The GCP project ID
    """
    for secret_name in secrets_to_delete:
        logging.info(f"Deleting the following dev secret: {secret_name}")
        secret_conf.delete_secret(project_id, secret_name)


def validate_secret(secret: dict, attr_validation: ()) -> bool:  # type: ignore
    """
    Validate that the secret comply to our format
    :param secret: The secret json as a string
    :param attr_validation: A list of properties we expect the secret to have
    :return: A boolean value if the secret is valid or not
    """

    # Validate file exist and json 5 format
    try:
        json5.dumps(secret)
    except Exception as e:
        logging.error(
            f"Could not convert the secret '{secret.get(SECRET_NAME)}' to json5,\ngot the following error: {e!s}"  # type: ignore
        )
        return False
    # Validate mandatory properties in the secret
    missing_attrs = [attr for attr in attr_validation if attr not in secret]
    if missing_attrs:
        logging.error(
            f"Missing mandatory properties: {','.join(missing_attrs)} for the secret '{secret.get(SECRET_NAME)}'"  # type: ignore
        )
        return False
    return True


def run(options: argparse.Namespace):
    try:
        secret_conf = GoogleSecreteManagerModule(options.service_account, project_id=options.gsm_project_id_dev)

        pr_numbers_with_label, pr_numbers_without_label = get_latest_merged()
        logging.info(f"The latest closed PR numbers are: {pr_numbers_with_label + pr_numbers_without_label}")
        dev_secrets = secret_conf.get_secrets_from_project(options.gsm_project_id_dev, is_dev=True, is_pr_set=True)
        dev_secrets_to_merge, dev_secrets_to_delete = filter_secrets_by_pr_label(
            dev_secrets, pr_numbers_with_label, pr_numbers_without_label
        )
        if len(dev_secrets_to_merge) == 0:
            logging.info("No secrets to merge for this master build")
        secrets_to_delete = merge_dev_secrets(dev_secrets_to_merge, options.gsm_project_id_prod, secret_conf)
        secrets_to_delete.extend(get_secrets_name(dev_secrets_to_delete))
        delete_dev_secrets(secrets_to_delete, secret_conf, options.gsm_project_id_dev)  # type: ignore
    except Exception as e:
        logging.error(f"Could not merge secrets, got the error: {e}")
        raise e


def options_handler(args=None) -> argparse.Namespace:
    """
    Parse the passed parameters for the script
    :param args: A list of arguments to add
    :return: The parsed arguments that were passed to the script
    """
    parser = argparse.ArgumentParser(description="Utility for Importing secrets from Google Secret Manager.")
    parser.add_argument("-gpidd", "--gsm_project_id_dev", help="The project id for the GSM dev.")
    parser.add_argument("-gpidp", "--gsm_project_id_prod", help="The project id for the GSM prod.")
    # disable-secrets-detection-start
    parser.add_argument(
        "-sa",
        "--service_account",
        help=(
            "Path to gcloud service account, for circleCI usage. "
            "For local development use your personal account and "
            "authenticate using Google Cloud SDK by running: "
            "`gcloud auth application-default login` and leave this parameter blank. "
            "For more information see: "
            "https://googleapis.dev/python/google-api-core/latest/auth.html"
        ),
        required=False,
    )
    # disable-secrets-detection-end
    options = parser.parse_args(args)

    return options


if __name__ == "__main__":
    options = options_handler()
    run(options)
