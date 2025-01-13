import argparse
import logging
import os
import re
from collections.abc import Iterable
from datetime import datetime
from enum import Enum

import dateparser
import json5
from google.auth import default
from google.cloud import secretmanager
from google.cloud.secretmanager_v1 import AccessSecretVersionResponse, Secret, SecretVersion

from Tests.scripts.common import BUCKET_UPLOAD_BRANCH_SUFFIX
from Tests.scripts.github_client import GithubClient

SECRETS_FILE_INTEGRATIONS = "integrations"

SECRET_NAME = "secret_name"
LABELS = "labels"

SPECIAL_CHARS = [" ", "(", "(", ")", ".", "", "+", "="]
GSM_MAXIMUM_LABEL_CHARS = 63
DEV_PROJECT_ID = "269994096945"
DATE_FORMAT = "%Y-%m-%d"
SYNC_GSM_LABEL = "sync-gsm"


class SecretLabels(Enum):
    IGNORE_SECRET = "ignore"
    SECRET_MERGE_TIME = "merge"
    DEV_SECRET = "dev"
    PR_NUMBER = "pr_number"
    PACK_ID = "pack_id"
    MACHINE = "machine"
    SHOULD_INSTANCE_TEST = "should_instance_test"

    def __str__(self):
        return self.value


class ExpirationData:
    DATE_FORMAT = "%Y-%m-%d"
    CREDS_EXPIRATION_LABEL_NAME = "credential_expiration"
    LICENSE_EXPIRATION_LABEL_NAME = "license_expiration"
    CENTRIFY_LABEL_NAME = "centrify"
    SKIP_REASON_LABEL_NAME = "skip_reason"
    JIRA_LINK_LABEL_NAME = "jira_link"
    SECRET_OWNER = "owner"

    class Status:
        STATUS_LABEL_NAME = "status"
        ACTIVE_STATUS = "active"
        INACTIVE_STATUS = "inactive"


class GoogleSecreteManagerModule:
    class GoogleSecretTools:
        @staticmethod
        def calculate_expiration_date(expiration_date: str) -> str | None:
            """Calculating expiration date based on input.

            Args:
                expiration_date (str): a date representing string, such "in 1 day", "3 days", "2024-05-01", etc

            Returns:
                str: a standardized string for the date requested.
            """
            logging.debug(f"Parsing expiration date from: {expiration_date}")
            d = dateparser.parse(expiration_date)
            logging.debug("Parsed successfully.")

            return datetime.strftime(d, DATE_FORMAT) if d else None

    def __init__(self, service_account_file: str | None = None, project_id=DEV_PROJECT_ID):
        self.project_id = project_id
        self.client = self.create_secret_manager_client(service_account_file)

    @staticmethod
    def convert_to_gsm_format(name: str, secret_name: bool = False) -> str:
        """
        Convert a string to comply with GSM labels formatting(A-Z, a-z, 0-9, -, _)
        :param name: the name to transform
        :param secret_name: if it's used as a secret name or not
        return: the name after it's been transformed to a GSM supported format
        """
        name = name.replace(" ", "_")
        for char in SPECIAL_CHARS:
            name = name.replace(char, "")
        if secret_name:
            return name
        # the GSM label cannot be longer than 63 characters
        if len(name) > GSM_MAXIMUM_LABEL_CHARS:
            logging.info(f"Truncated the original value {name} to {name[:GSM_MAXIMUM_LABEL_CHARS]}")
            name = name[:GSM_MAXIMUM_LABEL_CHARS]
        return name.lower()

    def get_secret(
        self, secret_id: str, project_id: str | None = None, version_id: str = "latest", with_version: bool = False
    ) -> dict | tuple[dict, str]:
        """
        Gets a secret from GSM
        :param project_id: the ID of the GCP project
        :param secret_id: the ID of the secret we want to get
        :param version_id: the version of the secret we want to get
        :param with_version: whether to return the version of the secret that we got
        :return: the secret as json5 object
        """
        name = f"projects/{project_id or self.project_id}/secrets/{secret_id}/versions/{version_id}"
        response = self.client.access_secret_version(request={"name": name})
        secret_version_number = self.extract_secret_name_suffix(response)
        try:
            secret_value = json5.loads(response.payload.data.decode("UTF-8"))
        except Exception as e:
            logging.error(f"Secret json is malformed for: {secret_id} version: {secret_version_number}, " f"got error: {e}")
            secret_value = {}
        if with_version:
            return secret_value, secret_version_number
        return secret_value

    def list_secrets(self, query_filter: str, project_id: str, pack_ids: set[str]) -> list[dict]:
        """
        Lists secrets from GSM
        :param project_id: the ID of the GCP project
        :param query_filter: indicates how we want to filter secrets
        :param pack_ids: A list of pack IDs (folder names in lowercase) used to filter and retrieve corresponding secrets.
        :return: the secret as json5 object
        """
        secrets = []

        secrets_list = self.list_secrets_metadata_by_query(query_filter, project_id)
        for secret in secrets_list:
            secret_name = self.extract_secret_name_suffix(secret)
            logging.debug(f"Getting the secret: {secret_name}")
            secret_value = self.get_secret(secret_name, project_id)
            if not secret_value:
                continue
            secret_value.update({SECRET_NAME: secret_name, LABELS: dict(secret.labels)})
            secrets.append(secret_value)
            pack_ids.discard(secret_value[LABELS].get(SecretLabels.PACK_ID.value))

        if pack_ids:
            logging.info(f"Pack IDs requested but not retrieved, since there were no associated secrets: {pack_ids}")
        return secrets

    def add_secret_version(self, secret_id: str, payload: dict, project_id: str | None = None) -> str:
        """
        Add a new secret version to the given secret with the provided payload.
        :param project_id: The project ID for GCP
        :param secret_id: The name of the secret in GSM
        :param payload: The secret value to update
        """
        project_id = project_id or self.project_id
        parent = self.client.secret_path(project_id, secret_id)

        payload = payload.encode("UTF-8")  # type: ignore

        secret_version = self.client.add_secret_version(
            request={
                "parent": parent,
                "payload": {"data": payload},
            }
        )
        secret_version_number = self.extract_secret_name_suffix(secret_version)
        logging.info(
            f"Added a secret version {secret_version_number}: "
            f"https://console.cloud.google.com/security/secret-manager/secret/{secret_id}/versions?project={project_id}"
        )
        return secret_version_number

    @staticmethod
    def extract_secret_name_suffix(secret: Secret | SecretVersion | AccessSecretVersionResponse) -> str:
        return secret.name.split("/")[-1]

    def delete_secret(self, project_id: str, secret_id: str) -> None:
        """
        Delete a secret from GSM
        :param project_id: The project ID for GCP
        :param secret_id: The name of the secret in GSM
        """
        name = self.client.secret_path(project_id, secret_id)
        self.client.delete_secret(request={"name": name})

    def create_secret(self, secret_id: str, project_id: str | None = None, labels: dict[str, str] = None) -> None:
        """
        Creates a secret in GSM
        :param project_id: The project ID for GCP
        :param secret_id: The name of the secret in GSM
        :param labels: A dict with the labels we want to add to the secret
        """
        parent = f"projects/{project_id or self.project_id}"
        self.client.create_secret(
            request={
                "parent": parent,
                "secret_id": secret_id,
                "secret": {"replication": {"automatic": {}}, "labels": labels or {}},
            }
        )

    def create_secret_manager_client(self, service_account: str | None = None) -> secretmanager.SecretManagerServiceClient:
        """
        Creates GSM object using a service account
        :param service_account: the service account json as a string
        :return: the GSM object
        """
        try:
            if service_account:
                client = secretmanager.SecretManagerServiceClient.from_service_account_json(  # type: ignore
                    service_account  # type: ignore
                )
            else:
                credentials, _project_id = default(quota_project_id=self.project_id)
                client = secretmanager.SecretManagerServiceClient(credentials=credentials)
            return client
        except Exception as e:
            logging.error(f"Could not create GSM client, error: {e}")
            raise

    def update_secret(self, secret_id: str, labels: dict[str, str] = None) -> None:
        """
        Update a secret in GSM
        :param secret_id: The name of the secret in GSM
        :param labels: A dict with the labels we want to add to the secret
        When providing labels, the previous ones will be switched.
        """
        labels = labels or {}
        name = self.client.secret_path(self.project_id, secret_id)
        secret = {"name": name, "labels": labels}
        update_mask = {"paths": ["labels"]}
        self.client.update_secret(request={"secret": secret, "update_mask": update_mask})
        logging.info(f"Updated secret {secret_id} with labels {labels}")

    def list_secrets_metadata_by_query(self, query: str, project_id: str | None = None) -> list:
        """
        Lists secrets from GSM by a GSM query
        :param project_id: the ID of the GCP project
        :param query: a query to filter results by
        :return: the secret as json5 object
        """
        parent = f"projects/{project_id or self.project_id}"
        return list(self.client.list_secrets(request={"parent": parent, "filter": query}))

    @staticmethod
    def filter_label_is_set(label: str | SecretLabels, is_set: bool = True):
        return f"({'' if is_set else 'NOT '}labels.{label}:*)"

    @staticmethod
    def filter_label_equals(label: str | SecretLabels, value: str | int, is_equals: bool = True):
        return f"({'' if is_equals else 'NOT '}labels.{label}={value})"

    @staticmethod
    def normalize_pack_id(pack_id: str) -> str:
        return re.sub(r"\s+", "_", pack_id.lower())

    def filter_by_pack_ids(self, pack_ids: Iterable[str] = None) -> tuple[set[str], str] | tuple[set[None], None]:
        if pack_ids:
            target_pack_ids_set = {self.normalize_pack_id(pack_id) for pack_id in pack_ids if pack_id}
            logging.debug(f"Will filter by {len(target_pack_ids_set)} pack_id")
            packs_query_list = [self.filter_label_equals(SecretLabels.PACK_ID, pack_id) for pack_id in target_pack_ids_set]
            if packs_query_list:
                return target_pack_ids_set, f"({' OR '.join(packs_query_list)})"
        return set(), None

    def get_secrets_from_project(
        self,
        project_id: str,
        pr_number: int | None = None,
        is_dev: bool = False,
        is_pr_set: bool | None = None,
        pack_ids: Iterable[str] = None,
    ) -> list[dict]:
        """
        Retrieves secrets from a specified project ID and applies filters based on the provided arguments.

        Args:
            project_id: The project ID to retrieve secrets for, in order to get dev and prod secrets.
            pr_number: The GitHub PR number related with the dev secrets to retrieve.
            is_dev: Indicates if the secrets are from the dev project.
            is_pr_set: Specifies whether a PR should be set, used when retrieving dev secrets.
            pack_ids: A list of pack IDs (folder names in lowercase) used to filter and retrieve corresponding secrets.
        """
        query_components = [
            self.filter_label_is_set(SecretLabels.IGNORE_SECRET, is_set=False),
            self.filter_label_is_set(SecretLabels.SECRET_MERGE_TIME, is_set=False),
            self.filter_label_is_set(SecretLabels.DEV_SECRET, is_set=is_dev),
        ]
        if pr_number:
            query_components.append(self.filter_label_equals(SecretLabels.PR_NUMBER, pr_number))
        if is_pr_set:
            query_components.append(self.filter_label_is_set(SecretLabels.PR_NUMBER, is_set=True))
        target_pack_ids, packs_query = self.filter_by_pack_ids(pack_ids)
        if packs_query:
            query_components.extend([packs_query, self.filter_label_equals(SecretLabels.SHOULD_INSTANCE_TEST, "false", False)])

        query = " AND ".join(query_components)
        logging.debug(f"Will query GSM with {query=}")
        return self.list_secrets(query, project_id, target_pack_ids)


def normalize_branch_name(branch_name: str):
    """normalizing the branch name if it contains the upload bucket suffix"""
    if BUCKET_UPLOAD_BRANCH_SUFFIX in branch_name:
        branch_name = branch_name.split(BUCKET_UPLOAD_BRANCH_SUFFIX)[0]
    return branch_name


def create_github_client(gsm_object: GoogleSecreteManagerModule, project_id: str, github_token: str = ""):
    if not github_token:
        github_token = gsm_object.get_secret("Github_Content_Token", project_id).get("GITHUB_TOKEN", "")

    return GithubClient(github_token)


def get_secrets_from_gsm(options: argparse.Namespace, branch_name: str = "", filter_by_pack_ids: list[str] | None = None) -> dict:
    """
    Gets the dev secrets and main secrets from GSM and merges them.
    :param branch_name: the name of the branch of the PR.
    :param options: the parsed parameter for the script.
    :param filter_by_pack_ids: a list of pack_ids to filter secrets by. If None, no filtering is applied.
    :return: the list of secrets from GSM to use in the build.
    """
    secret_conf = GoogleSecreteManagerModule(options.gsm_service_account)  # no project_id because it is used for 2 projects

    logging.info("Getting secrets from prod project")
    master_secrets = secret_conf.get_secrets_from_project(options.gsm_project_id_prod, pack_ids=filter_by_pack_ids)
    logging.info(f"Finished getting needed secrets from prod, got {len(master_secrets)} master secrets")
    branch_secrets = get_branch_secrets(
        branch_name, options.github_token, options.gsm_project_id_dev, secret_conf, filter_by_pack_ids
    )
    logging.info(f"Finished getting needed branch secrets, got {len(branch_secrets)} branch secrets")

    merged_secrets = merge_dev_prod_secrets(branch_secrets, master_secrets)
    secret_file = {"username": options.user, "userPassword": options.password, SECRETS_FILE_INTEGRATIONS: merged_secrets}
    logging.debug(
        f"Using {len(secret_file[SECRETS_FILE_INTEGRATIONS])} secrets."
        f"\nThe secrets that are used are: {[s.get(SECRET_NAME) for s in secret_file[SECRETS_FILE_INTEGRATIONS]]}"
    )

    # saving the secrets file will be removed when test-content will be moved to infra (CIAC-11081)
    if "json_path_file" in options and options.json_path_file:
        write_secrets_to_file(options.json_path_file, secret_file)
    else:
        logging.info("Cloud not find 'json_path_file' argument, not saving secrets to file.")
    return secret_file


def write_secrets_to_file(json_path_file: str, secrets: dict):
    """
    Writes the secrets we got from GSM to a file for the build
    :param json_path_file: the path to the wanted file
    :param secrets: a list of secrets to be used in the build
    """
    try:
        with open(json_path_file) as secrets_existing_file:
            existing_file = json5.load(secrets_existing_file)
            logging.debug(f"Loaded the existing file from {os.path.abspath(json_path_file)}")
    except (FileNotFoundError, ValueError):
        logging.debug("Setting the existing file to an empty dict")
        existing_file = {}

    if integrations := existing_file.get(SECRETS_FILE_INTEGRATIONS):
        # checking based on SECRET_NAME, because other values are brought from the same place and should not differ
        existing_secrets_names = {integration_secret[SECRET_NAME] for integration_secret in integrations}
        logging.info(f"The number of secrets in the secret file is {len(integrations)}")
        logging.debug(f"From the secret file, the {existing_secrets_names=}")
        for integration in secrets[SECRETS_FILE_INTEGRATIONS]:
            if integration[SECRET_NAME] not in existing_secrets_names:
                integrations.append(integration)
        secrets[SECRETS_FILE_INTEGRATIONS] = integrations

    with open(json_path_file, "w") as secrets_out_file:
        try:
            secrets_out_file.write(json5.dumps(secrets, quote_keys=True))
            logging.info(
                f"Saved the secrets json file to: {os.path.abspath(json_path_file)}, "
                f"with {len(secrets[SECRETS_FILE_INTEGRATIONS])} secrets in it."
            )
        except Exception as e:
            logging.error(f"Could not save secrets file, malformed json5 format, the error is: {e}")


def merge_dev_prod_secrets(branch_secrets: list[dict], master_secrets: list[dict]) -> list[dict]:
    for dev_secret in branch_secrets:
        secret_index = next(
            (
                i
                for i, master_secret in enumerate(master_secrets)
                if master_secret["name"] == dev_secret["name"]
                and master_secret.get("instance_name", "no_instance_name") == dev_secret.get("instance_name", "no_instance_name")
            ),
            None,
        )
        if secret_index:
            logging.info(f"Replacing prod secret with the following dev secret: {dev_secret[SECRET_NAME]}")
            master_secrets[secret_index] = dev_secret
        else:
            logging.info(f"Appending the following dev secret (no replacement needed): {dev_secret[SECRET_NAME]}")
            master_secrets.append(dev_secret)

    return master_secrets


def get_branch_secrets(
    branch_name: str,
    github_token: str,
    project_id_dev: str,
    secret_conf: GoogleSecreteManagerModule,
    filter_by_pack_ids: list[str] = None,
) -> list[dict]:
    if branch_name and branch_name != "master":
        branch_name = normalize_branch_name(branch_name)
        if pr_number := get_pr_number(branch_name, github_token):
            logging.info(f"Getting secrets for the {branch_name} branch with PR number: {pr_number}")
            return secret_conf.get_secrets_from_project(project_id_dev, pr_number, is_dev=True, pack_ids=filter_by_pack_ids)
    return []


def get_pr_number(branch_name: str, github_token: str) -> int | None:
    try:
        github_client = GithubClient(github_token)
        return github_client.get_pr_number_from_branch_name(branch_name)
    except Exception as e:
        if "Did not find the PR" in str(e):
            logging.info(
                f"Did not find the associated PR with the branch {branch_name}, you may be running from infra."
                " Will only use the secrets from prod."
            )
        else:
            logging.info(f"Got the following error when trying to contact Github: {e!s}")
