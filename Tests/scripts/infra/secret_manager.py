import logging
import os

from google.api_core.exceptions import GoogleAPICallError
from google.api_core.exceptions import PermissionDenied
from google.cloud.exceptions import NotFound
from google.cloud.secretmanager import SecretManagerServiceClient


from infra.resources.constants import AUTOMATION_GCP_PROJECT, GCP_SERVICE_ACCOUNT


class SecretManager:
    """Google Secret Manager connector"""

    # connector_name = ConnectorName()

    def __init__(self, project_id: str = AUTOMATION_GCP_PROJECT):
        # self.log = log
        self.project_id = project_id
        # self.log.debug('Instantiate GCP Secret Manager client')
        if GCP_SERVICE_ACCOUNT is not None:
            self.client = SecretManagerServiceClient.from_service_account_file(GCP_SERVICE_ACCOUNT)
        else:
            self.client = SecretManagerServiceClient()
        logging.getLogger('google.auth.transport.requests').setLevel(logging.WARNING)
        logging.getLogger('google.auth._default').setLevel(logging.WARNING)
        # self.inc_metric = partial(metrics_client.incr, self.connector_name)

    def get_secret(self, secret_id: str) -> str:
        """Retrieves a secret identified by `secret_id` either from environment variables or from GCP Secret Manager"""
        if env_var := os.getenv(secret_id):
            # self.log.debug(f'{secret_id=} found as env variable')
            return env_var
        try:
            # self.log.debug(f'Fetching {secret_id=} from GCP Secret Manager')
            # self.inc_metric('get')
            response = self.client.access_secret_version(name=self._build_path(secret_id))  # $0.03 per 10000 operations
        except PermissionDenied:
            # self.inc_metric('error', 'permission')
            # self.log.critical(
            #     f'GCP secrets permission denied for {secret_id=}, verify role "roles/secretmanager.secretAccessor" exists:\n{e}'
            # )
            raise
        except NotFound:
            # self.inc_metric('error', 'not_found')
            # self.log.critical(f'GCP Secret {secret_id=} is missing:\n{e}')
            raise
        except GoogleAPICallError:
            # self.inc_metric('error', 'general_error')
            # self.log.critical(f'Failed to get GCP secret {secret_id=}:\n{e}')
            raise
        payload = response.payload.data.decode("UTF-8")
        os.environ[secret_id] = payload  # save secret to env to reduce future calls
        return payload

    def _build_path(self, secret_id) -> str:
        secret_path = self.client.secret_path(project=self.project_id, secret=secret_id)
        return f'{secret_path}/versions/latest'
