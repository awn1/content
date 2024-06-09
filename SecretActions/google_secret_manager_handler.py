from datetime import datetime
from enum import Enum
import dateparser
import json5
from google.auth import default
from google.cloud import secretmanager
import logging

SPECIAL_CHARS = [" ", "(", "(", ")", ".", "", "+", "="]
GSM_MAXIMUM_LABEL_CHARS = 63
DEV_PROJECT_ID = "269994096945"
DATE_FORMAT = '%Y-%m-%d'


class FilterLabels(Enum):
    IGNORE_SECRET = "ignore"
    SECRET_MERGE_TIME = "merge"
    SECRET_ID = "secret_id"
    IS_DEV_BRANCH = "dev"
    BRANCH_NAME = "branch"

    def __str__(self):
        return self.value


class FilterOperators(Enum):
    NONE = "is None"
    NOT_NONE = "is not None"
    EQUALS = "=="
    NOT_EQUALS = "!="

    def __str__(self):
        return self.value


class ExpirationData:
    DATE_FORMAT = "%Y-%m-%d"
    CREDS_EXPIRATION_LABEL_NAME = "credential_expiration"
    LICENSE_EXPIRATION_LABEL_NAME = "license_expiration"
    CENTRIFY_LABEL_NAME = "centrify"
    SKIP_REASON_LABEL_NAME = "skip_reason"
    JIRA_LINK_LABEL_NAME = "jira_link"
    SECRET_OWNER = 'owner'

    class Status:
        STATUS_LABEL_NAME = "status"
        ACTIVE_STATUS = "active"
        INACTIVE_STATUS = "inactive"


class GoogleSecreteManagerModule:

    class GoogleSecretTools:
        def calculate_expiration_date(expiration_date: str) -> str:
            """Calculating expiration date based on input.

            Args:
                expiration_date (str): a date representing string, such "in 1 day", "3 days", "2024-05-01", etc

            Returns:
                str: a standardized string for the date requested.
            """
            logging.debug(f"Parsing expiration date from: {expiration_date}")
            d = dateparser.parse(expiration_date)
            logging.debug("Parsed successfully.")

            return datetime.strftime(d, DATE_FORMAT)


    def __init__(self, service_account_file: str = None, project_id=DEV_PROJECT_ID):
        self.client = self.create_secret_manager_client(
            project_id, service_account_file
        )

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
            logging.info(
                f"Truncated the original value {name} to {name[:GSM_MAXIMUM_LABEL_CHARS]}"
            )
            name = name[:GSM_MAXIMUM_LABEL_CHARS]
        return name.lower()

    def get_secret(
        self, project_id: str, secret_id: str, version_id: str = "latest"
    ) -> dict:
        """
        Gets a secret from GSM
        :param project_id: the ID of the GCP project
        :param secret_id: the ID of the secret we want to get
        :param version_id: the version of the secret we want to get
        :return: the secret as json5 object
        """
        name = f"projects/{project_id}/secrets/{secret_id}/versions/{version_id}"
        response = self.client.access_secret_version(request={"name": name})
        try:
            return json5.loads(response.payload.data.decode("UTF-8"))
        except Exception as e:
            logging.error(
                f'Secret json is malformed for: {secret_id} version: {response.name.split("/")[-1]}, got error: {e}'
            )
            return {}

    def list_secrets(
        self,
        project_id: str,
        labels_filter: dict,
        name_filter=None,
        with_secrets: bool = False,
    ) -> list:
        """
        Lists secrets from GSM
        :param project_id: the ID of the GCP project
        :param name_filter: a secret name to filter results by
        :param with_secrets: indicates if we want to bring the secret value(will need another API call per scret or just metadata)
        :param labels_filter: indicates how we want to filer secrets according to labels
        :return: the secret as json5 object
        """
        if name_filter is None:
            name_filter = []
        secrets = []
        parent = f"projects/{project_id}"
        for secret in self.client.list_secrets(request={"parent": parent}):
            secret.name = str(secret.name).split("/")[-1]
            labels = {}
            try:
                labels = dict(secret.labels)
            except Exception as e:
                logging.error(
                    f"Error: The secret {secret.name} has no labels, got the error: {e}"
                )
            secret_id = labels.get("secret_id", "no_secret_id").split("__")[0]
            logging.debug(f"Getting the secret: {secret.name}")
            search_ids = [self.convert_to_gsm_format(s.lower()) for s in name_filter]
            try:
                # Check if the secret comply to the function filter params
                filter = [
                    eval(f'{labels}.get("{k}"){v}') for k, v in labels_filter.items()
                ]
            except Exception as e:
                logging.error(
                    f"Eval function failed for the secret {secret.name}, error: {e}"
                )
                filter = [False]
            if not all(filter) or (search_ids and secret_id not in search_ids):
                continue
            if with_secrets:
                try:
                    secret_value = self.get_secret(project_id, secret.name)
                    if not secret_value:
                        continue
                    secret_value["secret_name"] = secret.name
                    secret_value["labels"] = labels
                    secrets.append(secret_value)
                except Exception as e:
                    logging.error(
                        f"Error getting the secret: {secret.name}, got the error: {e}"
                    )
            else:
                secret.labels = labels
                secrets.append(secret)

        return secrets

    def add_secret_version(
        self, project_id: str, secret_id: str, payload: dict
    ) -> None:
        """
        Add a new secret version to the given secret with the provided payload.
        :param project_id: The project ID for GCP
        :param secret_id: The name of the secret in GSM
        :param payload: The secret value to update
        """
        parent = self.client.secret_path(project_id, secret_id)

        payload = payload.encode("UTF-8")  # type: ignore

        self.client.add_secret_version(
            request={
                "parent": parent,
                "payload": {"data": payload},
            }
        )
        logging.info(
            f"Added a secret version: "
            f"https://console.cloud.google.com/security/secret-manager/secret/{secret_id}/versions?project={project_id}"
        )

    def delete_secret(self, project_id: str, secret_id: str) -> None:
        """
        Delete a secret from GSM
        :param project_id: The project ID for GCP
        :param secret_id: The name of the secret in GSM
        """

        name = self.client.secret_path(project_id, secret_id)
        self.client.delete_secret(request={"name": name})

    def create_secret(self, project_id: str, secret_id: str, labels=None) -> None:
        """
        Creates a secret in GSM
        :param project_id: The project ID for GCP
        :param secret_id: The name of the secret in GSM
        :param labels: A dict with the labels we want to add to the secret

        """

        if labels is None:
            labels = {}
        parent = f"projects/{project_id}"
        self.client.create_secret(
            request={
                "parent": parent,
                "secret_id": secret_id,
                "secret": {"replication": {"automatic": {}}, "labels": labels},
            }
        )

    @staticmethod
    def create_secret_manager_client(
        project_id, service_account: str = None
    ) -> secretmanager.SecretManagerServiceClient:
        """
        Creates GSM object using a service account
        :param project_id: The Google project ID to connect to
        :param service_account: the service account json as a string
        :return: the GSM object
        """
        try:
            if service_account:
                client = secretmanager.SecretManagerServiceClient.from_service_account_json(  # type: ignore
                    service_account  # type: ignore
                )
            else:
                credentials, _project_id = default(quota_project_id=project_id)
                client = secretmanager.SecretManagerServiceClient(
                    credentials=credentials
                )
            return client
        except Exception as e:
            logging.error(f"Could not create GSM client, error: {e}")
            raise

    def update_secret(self, project_id: str, secret_id: str, labels=None) -> None:
        """
        Update a secret in GSM
        :param project_id: The project ID for GCP
        :param secret_id: The name of the secret in GSM
        :param labels: A dict with the labels we want to add to the secret
        When providing labels, the previous ones will be switched.
        """
        if labels is None:
            labels = {}
        name = self.client.secret_path(project_id, secret_id)
        secret = {"name": name, "labels": labels}
        update_mask = {"paths": ["labels"]}
        self.client.update_secret(
            request={"secret": secret, "update_mask": update_mask}
        )
        logging.info(f"Updated secret {secret_id} with labels {labels}")

    def list_secrets_metadata_by_query(self, project_id: str, query: str) -> list:
        """_summary_
        Lists secrets from GSM by a GSM query
        :param project_id: the ID of the GCP project
        :param query: a query to filter results by
        :return: the secret as json5 object
        """
        parent = f"projects/{project_id}"
        return list(
            self.client.list_secrets(request={"parent": parent, "filter": query})
        )
