import contextlib
import logging
import re
from functools import cached_property
from http.client import HTTPException, RemoteDisconnected
from json import JSONDecodeError
from urllib.parse import unquote

import pendulum
import requests
from _pytest.cacheprovider import Cache
from filelock import FileLock
from google.cloud.exceptions import NotFound
from more_itertools import first
from pendulum import DateTime

# from pydantic import parse_obj_as
from requests import ConnectionError, HTTPError, TooManyRedirects
from urllib3.util import Retry

from SecretActions.add_build_machine import BUILD_MACHINE_GSM_TOKEN
from SecretActions.google_secret_manager_handler import GoogleSecreteManagerModule
from Tests.scripts.infra.enums.papi import KeySecurityLevel
from Tests.scripts.infra.enums.tables import XdrTables
from Tests.scripts.infra.enums.xsiam_alerts import SearchTableField
from Tests.scripts.infra.models import PublicApiKey

# from infra.logger import log
# from infra.logger import session_log
# from infra.metric_client import metrics_client
# from infra.models.audit_trail import AuditTrail
# from infra.models.dashboard import Dashboard
# from infra.models.dashboard import Report
# from infra.models.incident_fields import Attachment
# from infra.models.investigations import Alert
# from infra.models.investigations import Incident
# from infra.models.investigations import NewIncident
# from infra.models.public_api import PublicApiKey
# from infra.models.roles import UserGroup
# from infra.models.roles import XsoarRole
# from infra.models.user import NewUserActivation
# from infra.models.user import NewUserData
# from infra.models.user import User
# from infra.models.xsoar_settings.layout import Layout
from Tests.scripts.infra.resources.constants import (
    AUTOMATION_GCP_PROJECT,
    DEFAULT_USER_AGENT,
    GSM_SERVICE_ACCOUNT,
    OKTA_HEADERS,
    TokenCache,
)
from Tests.scripts.infra.utils.env import is_production

# from infra.enums.layouts import LayoutObjectType
# from infra.enums.papi import KeySecurityLevel
# from infra.enums.tables import XdrTables
# from infra.enums.xsiam_alerts import AlertStatus
# from infra.enums.xsiam_alerts import SearchTableField
# from infra.enums.xsiam_alerts import SearchTableOperator
# from infra.exceptions import GetTableDataException
# from infra.exceptions import InviteUserError
# from infra.exceptions import MissingIncident
# from infra.exceptions import RocketEnvException
# from infra.exceptions import SetupException
# from infra.exceptions import TeardownException
# from infra.firestore_connector import Firestore
from Tests.scripts.infra.utils.firestore_connector import Firestore, lock_and_read
from Tests.scripts.infra.utils.html import find_html_attribute, find_html_form_action
from Tests.scripts.infra.utils.requests_handler import TimeoutHTTPAdapter, raise_for_status
from Tests.scripts.infra.utils.rocket_retry import retry
from Tests.scripts.infra.utils.text import to_list
from Tests.scripts.infra.utils.time_utils import time_now, to_epoch_timestamp
from Tests.scripts.stop_running_pipeline import CI_PIPELINE_ID

logger = logging.getLogger(__name__)


class InvalidAPIKey(Exception):
    def __init__(self, cloud_machine: str, msg: str):
        self.message = f"Invalid API Key for machine {cloud_machine} was provided or generated. {msg}"

    def __str__(self):
        return self.message


class XsoarOnPremClient:
    XSRF_TOKEN_HEADER = "X-XSRF-TOKEN"
    CSRF_TOKEN_NAME = "XSRF-TOKEN"
    ABOUT_PATH = "about"
    PLATFORM_TYPE = "xsoar"
    PRODUCT_TYPE = "XSOAR"

    def __init__(self, xsoar_host: str, xsoar_user: str, xsoar_pass: str, tenant_name: str, cache: Cache | None = None):
        retry_strategy = Retry(
            # allowed_methods=frozenset(["HEAD", "GET", "PUT", "DELETE", "OPTIONS", "TRACE", "POST"]),
            total=5,
            connect=3,
            backoff_factor=0.5,
            respect_retry_after_header=False,
        )  # retry connection errors (not HTTPErrors)
        self.login_timout = 60  # 1 minute timeout to quickly fail on initial communication issues
        self.session_timout = 600  # default 10 minutes timeout for all API calls
        self.session = requests.Session()
        self.session.mount(prefix="https://", adapter=TimeoutHTTPAdapter(timeout=self.session_timout, max_retries=retry_strategy))
        self.session.headers["User-Agent"] = DEFAULT_USER_AGENT
        self.session.verify = False  # Disable SSL verification since we're working with self-signed certs here.
        self.xsoar_base_url = f"https://{xsoar_host}:443"
        self.xsoar_webapp_url: str | None = None
        self.xsoar_user = xsoar_user
        self.xsoar_pass = xsoar_pass
        # self.inc_metric = partial(metrics_client.incr, self.PLATFORM_TYPE, tenant_name)
        self.cache = cache
        self.tenant_name = tenant_name

    def _set_xsrf_header(self):
        if not (xsrf_token := self.session.cookies.get(name=self.CSRF_TOKEN_NAME)):
            raise KeyError("Failed to extract XSRF token from session cookies")
        self.session.headers[self.XSRF_TOKEN_HEADER] = xsrf_token

    def login_auth(self, **kwargs):
        tries = kwargs.get("tries", 10)

        @retry(
            (ConnectionError, RemoteDisconnected, HTTPException, Exception, IOError),
            delay=10,
            tries=tries,
            backoff=1.5,
            raise_original_exception=True,
        )
        # As OnPrem tenant can be "under upgrade condition" on nightlys (and we don't have pods to check) - timeout set to ±19min
        def login_auth_with_retry():
            # self.inc_metric('login')
            self.session.get(self.xsoar_base_url, timeout=self.login_timout)
            self._set_xsrf_header()
            login_res = self.session.post(
                f"{self.xsoar_base_url}/login",
                timeout=self.login_timout,
                json={"user": self.xsoar_user, "password": self.xsoar_pass},
            )
            raise_for_status(login_res)

        login_auth_with_retry()

    def logout_auth(self):
        # self.inc_metric('logout')
        logout_res = self.session.post(f"{self.xsoar_base_url}/logout")
        raise_for_status(logout_res)

    def search_api_keys(self) -> list[PublicApiKey]:
        """Search for API keys"""
        res = self.session.get(url=f"{self.xsoar_base_url}/apikeys")
        raise_for_status(res)
        keys = [PublicApiKey(id=key["id"], key="cant see real key") for key in res.json()]
        return keys

    # def create_api_key(self, key_name: str, key_value: str, **kwargs) -> PublicApiKey:
    #     """
    #     Calls XSOAR API to create an API key, returns a Dict of format::
    #     {"name":"my_name", "id":"1fa9e9b9-bccf-4c38-8a75-d4fc7575d343", "key": "056692B32F4BD6CAF790B1239B7F5412"}
    #     return tuple of key ID and the key value
    #     """
    #     res = self.session.post(url=f'{self.xsoar_base_url}/apikeys', json={"name": key_name, "apikey": key_value})
    #     raise_for_status(res)
    #     if not (key_id := first([key['id'] for key in res.json() if key.get('name') == key_name], default=None)):
    #         raise Exception(f'Create api key action failed, the response was {res.text}')
    #     return PublicApiKey(id=key_id, key=key_value)

    def revoke_api_key(self, key_id: str):
        """Call XSOAR API to revoke an API key"""
        res = self.session.delete(url=f"{self.xsoar_base_url}/apikeys/{key_id}")
        raise_for_status(res)
        if first([key["id"] for key in res.json() if key.get("id") == key_id], default=None):
            raise Exception(f"api key {key_id=} revoke action failed, the response was {res.text}")

    def edit_api_key(self, comment: str, new_roles: list[str], key_id: int):
        """Edit API key"""
        raise NotImplementedError("Not implemented by rocket on this env")

    def get_version_info(self) -> dict:
        """Call XSOAR /about endpoint to fetch version info"""
        # self.inc_metric('get_version_info')
        res = self.session.get(url=f"{self.xsoar_base_url}/{self.ABOUT_PATH}")
        raise_for_status(res)
        return res.json()

    def set_log_level(self, xsoar_log_level: str = "debug"):
        """Set XSOAR server log level"""
        # self.inc_metric('set_log_level')
        params = {"level": xsoar_log_level}
        res = self.session.post(f"{self.xsoar_base_url}/log", params=params)
        raise_for_status(res)

    # def get_invited_users(self) -> list[User]:
    #     """Call XSOAR invited users API to get info about invited users (Only)"""
    #     self.inc_metric('get_invited_users')
    #     data = {"page": 0, "size": 10000, "query": ""}
    #     res = self.session.post(f'{self.xsoar_base_url}/invites/search', json=data)
    #     raise_for_status(res)
    #     invited = res.json().get("invites")
    #
    #     users = [
    #         User(**user, username=user.get("email", ""), invitation_url=user.get("url", ""), disabled=True)
    #         for user in invited
    #         if not user["accepted"]
    #     ]
    #     return users
    #
    # def get_users(self, show_invites: bool = False) -> list[User]:
    #     """Call XSOAR users API to get info about users"""
    #     self.inc_metric('get_users')
    #     res = self.session.get(f'{self.xsoar_base_url}/users')
    #     raise_for_status(res)
    #     accepted_users = parse_obj_as(list[User], res.json())
    #
    #     if show_invites:
    #         accepted_users.extend(self.get_invited_users())
    #
    #     return accepted_users
    #
    # def edit_user(self, user_name: list[str], new_role: Optional[XsoarRole] = None,
    # new_group: Optional[UserGroup] = None) -> dict:
    #     """Edit user"""
    #     if new_group:
    #         raise TypeError("User groups are not supported by on OnPrem")
    #     data = {"id": user_name[0], "roles": {"roles": [new_role.name], "defaultAdmin": False}}
    #     rsp = self.session.post(f"{self.xsoar_base_url}/users/update", json=data)
    #     raise_for_status(rsp)
    #     return rsp.json()
    #
    # def set_user_details(self, user: User, first_name: Optional[str], last_name: Optional[str], phone: Optional[str]):
    #     raise NotImplementedError('Not implemented by rocket on this env')
    #
    # def set_user_pref_details(
    #     self, user: User, first_name: Optional[str], last_name: Optional[str], phone: Optional[str], password: Optional[str]
    # ):
    #     raise NotImplementedError('Not implemented by rocket on this env')

    def send_invitation_only(self, data: dict) -> dict:
        """Invite user to XSOAR"""
        raise NotImplementedError("Not implemented by rocket on this env")

    def send_forgot_my_password(self, email: str):
        """Send Forgot My Password"""
        raise NotImplementedError("Not implemented by rocket on this env")

    def reset_password_confirm(self, email: str, reset_link: str, password: str):
        """Reset Password Confirm"""
        raise NotImplementedError("Not implemented by rocket on this env")

    # def invite_user(self, user_data: NewUserData) -> str:
    #     """Invite user to XSOAR"""
    #     data = {'email': user_data.email, 'roles': user_data.roles}
    #     res = self.session.post(f'{self.xsoar_base_url}/invite', json=data)
    #     raise_for_status(res)
    #     return res.json()['url']
    #
    # def reset_invite_user(self, ids: list[str]):
    #     """Reset invite User"""
    #     data = {'ids': ids}
    #     res = self.session.post(f'{self.xsoar_base_url}/invites/resetExpiration', json=data)
    #     raise_for_status(res)
    #
    # def _extract_invite_user_id(self, invitation_url) -> str:
    #     invite_id = re.search(pattern=r'/invite/([0-9a-fA-F-]+)', string=invitation_url)
    #     assert invite_id, f'Failed to extract id from {invitation_url=}'
    #     return invite_id.group(1)
    #
    # def accept_invitation(self, activate_data: NewUserActivation) -> User:
    #     new_user_session = requests.session()
    #     new_user_session.headers = self.session.headers.copy()
    #     new_user_session.cookies = self.session.cookies.copy()
    #     data = {'username': activate_data.username, 'password': activate_data.password, 'existing': False}
    #     invite_id = self._extract_invite_user_id(activate_data.invitation_url)
    #     res = new_user_session.post(f'{self.xsoar_base_url}/invite/{invite_id}/utilize', json=data, verify=False)
    #     raise_for_status(res)
    #     try:
    #         return User.parse_obj(res.json())
    #     except JSONDecodeError:
    #         res.status_code = 400
    #         raise HTTPError(f'Failed to accept invitation for {activate_data.invitation_url}', response=res)
    #
    # def resend_users_invitation(self, users: list[User]):
    #     ids = [user.id for user in users]
    #     data = {"ids": ids}
    #     rsp = self.session.post(f'{self.xsoar_base_url}/invites/resendInvite', json=data)
    #     raise_for_status(rsp)
    #
    # def cancel_users_invitation(self, users: list[User]):
    #     ids = [user.id for user in users]
    #     data = {"ids": ids}
    #     rsp = self.session.post(f'{self.xsoar_base_url}/invites/delete', json=data)
    #     raise_for_status(rsp)
    #
    # def activate_user(self, email: str):
    #     """Enable User"""
    #     data = {"id": email}  # ONPREM: we can activate only 1 user
    #     rsp = self.session.post(f'{self.xsoar_base_url}/users/enable', json=data)
    #     raise_for_status(rsp)
    #
    # def deactivate_user(self, email: str):
    #     """Disable User"""
    #     data = {"id": email}  # ONPREM: we can deactivate only 1 user
    #     rsp = self.session.post(f'{self.xsoar_base_url}/users/disable', json=data)
    #     raise_for_status(rsp)
    #
    # def delete_users(self, emails: list[str]):
    #     data = {"ids": emails}
    #     rsp = self.session.post(f'{self.xsoar_base_url}/users/delete', json=data)
    #     raise_for_status(rsp)

    def delete_user_role(self, user_name: str):
        """Delete roles from user"""
        raise NotImplementedError("Not implemented by rocket on this env")

    def sync_user_permission(self, user_name: str) -> dict:  # type:ignore[empty-body]
        pass

    def add_role(self, data: dict):
        """Add new role"""
        res = self.session.post(f"{self.xsoar_base_url}/roles/update", json=data)
        raise_for_status(res)

    def edit_role(self, data: dict):
        """Edit role"""
        raise NotImplementedError("Not implemented by rocket on this env")

    def delete_role(self, role_id: str):
        """Delete role"""
        res = self.session.delete(f"{self.xsoar_base_url}/roles/{role_id}")
        raise_for_status(res)

    def get_permissions(self) -> dict:
        """Get existing permissions"""
        raise NotImplementedError("Not implemented by rocket on this env")

    def add_group(self, data: dict) -> dict:
        """Add user group"""
        raise NotImplementedError("Not implemented by rocket on this env")

    def update_group(self, data: dict) -> dict:
        """Update user group"""
        raise NotImplementedError("Not implemented by rocket on this env")

    def delete_group(self, group_id: str):
        """Delete user group"""
        raise NotImplementedError("Not implemented by rocket on this env")

    def get_user_groups(self) -> dict:
        """Get all user groups"""
        raise NotImplementedError("Not implemented by rocket on this env")

    #
    # def get_roles(self) -> list[XsoarRole]:
    #     """Call XSOAR roles API to get info about user roles"""
    #     self.inc_metric('get_roles')
    #     res = self.session.get(f'{self.xsoar_base_url}/roles')
    #     raise_for_status(res)
    #     roles = parse_obj_as(list[XsoarRole], res.json())
    #     return roles

    def update_user_data(self, body: dict):
        """Set user data"""
        res = self.session.post(f"{self.xsoar_base_url}/user/update", json=body)
        raise_for_status(res)

    #
    # def load_incident(self, incident_id: str, account: str = None, **kwargs) -> Incident:
    #     """
    #     Search for incident by its internal_id field value, raise exception if it doesn't exist
    #     **kwargs here to allow XSIAM client to call this method directly - for specific needs like playbook debugger
    #     """
    #
    #     self.inc_metric('load_incident')
    #     account_prefix = f'/acc_{account}' if account else ""  # Handle MSSP use case
    #     try:
    #         res = self.session.get(f"{self.xsoar_base_url}{account_prefix}/incident/load/{incident_id}")
    #         raise_for_status(res)
    #     except HTTPError as e:
    #         raise MissingIncident(e) from e
    #     incident = Incident.parse_obj(res.json())
    #     return incident
    #
    # def close_incident(self, incident_id: str, resolution_comment: Optional[str] = "", **kwargs) -> dict:
    #     """Close specific incident"""
    #     rsp = self.session.post(
    #         f"{self.xsoar_base_url}/incident/close",
    #         json={"CustomFields": {}, "id": incident_id, 'closeNotes': resolution_comment}
    #     )
    #     raise_for_status(rsp)
    #     return rsp.json()

    def start_investigation(self, incident_id: str, version: int = 1) -> dict:
        """Start incident investigation"""
        rsp = self.session.post(f"{self.xsoar_base_url}/incident/investigate", json={"id": incident_id, "version": version})
        raise_for_status(rsp)
        return rsp.json()

    #
    # def find_incidents_by_name(self, name: str, query_size: int = 100) -> list[Incident]:
    #     """Find incidents by name"""
    #     query = f'name:"{name}"'
    #     return self.find_incidents_using_query(query=query, query_size=query_size)
    #
    # def find_incidents_using_query(self, query: str, query_size: int = 100, from_days_ago=2) -> list[Incident]:
    #     """Find incidents using query"""
    #     find_filter = {"filter": {"query": query, "period": {"by": "day", "fromValue": from_days_ago}, 'size': query_size}}
    #     res = self.session.post(f"{self.xsoar_base_url}/incidents/search", json=find_filter)
    #     raise_for_status(res)
    #     if not (incidents := parse_obj_as(list[Incident], res.json()['data'])):
    #         raise MissingIncident(f'No incidents found with {query=}')
    #     return incidents

    def search_in_incident(self, query: str, query_size: int = 50, last_days: int = 2) -> dict:
        """Search data IN incidents"""
        find_filter = {
            "filter": {"query": query, "period": {"by": "day", "fromValue": last_days}, "size": query_size},
            "investigationId": "",
        }
        res = self.session.post(f"{self.xsoar_base_url}/search", json=find_filter)
        raise_for_status(res)
        return res.json()

    #
    # def find_incidents_using_query_raw(self, query: dict) -> list[dict]:
    #     """
    #     Find incidents using query
    #     Note:
    #         1. This is different from find_incidents_using_query because it doesn't return modeled incidents!
    #         2. This method does not build the filter for you, you have to build the entire filter dict yourself
    #     """
    #     res = self.session.post(f"{self.xsoar_base_url}/incidents/search", json=query)
    #     raise_for_status(res)
    #     incidents = res.json()['data']
    #     if not incidents:
    #         raise MissingIncident(f'No incidents found with {query=}')
    #     return incidents
    #
    # def find_incidents_by_integration_source_instance(self, source_instance: str, query_size: int = 100) -> list[Incident]:
    #     """Find incidents by integration source instance"""
    #     query = f'sourceInstance:"{source_instance}"'
    #     return self.find_incidents_using_query(query=query, query_size=query_size)
    #
    # def generate_incident(self, incident_data: NewIncident) -> Incident:
    #     data = incident_data.dict(by_alias=True)
    #     self.session.headers.update({'accept': 'application/json'})
    #     res = self.session.post(url=f'{self.xsoar_base_url}/incident', json=data)
    #     raise_for_status(res)
    #     if not res.text:
    #         raise MissingIncident(f'Incident {incident_data.name} was not created')
    #     new_incident = Incident.parse_obj(res.json())
    #     return new_incident
    #
    # def edit_incident(self, incident_data: Incident) -> Incident:
    #     return self.generate_incident(incident_data=incident_data)
    #
    # def download_attachment(self, attachment: Attachment) -> bytes:
    #     """Download attachments"""
    #     self.inc_metric('download_attachment')
    #     path = attachment.path.split(f'_{attachment.name}')[0]
    #     artifact_path = f'{path}/{attachment.name}'
    #     res_download = self.session.get(url=f'{self.xsoar_base_url}/artifact/download/{artifact_path}', stream=True)
    #     raise_for_status(res_download)
    #     return res_download.content
    #
    # def get_all_dashboards(self) -> list[Dashboard]:
    #     """Get all dashboards"""
    #     rsp = self.session.get(f'{self.xsoar_base_url}/dashboards')
    #     raise_for_status(rsp)
    #     data = rsp.json().values()
    #     return parse_obj_as(list[Dashboard], list(data))

    def get_all_reports(self) -> list[dict]:
        """Get all reports"""
        rsp = self.session.get(f"{self.xsoar_base_url}/reports")
        raise_for_status(rsp)
        return rsp.json()
        #
        # def get_all_report_templates(self) -> list[Report]:
        #     """Get all report templates"""
        #     rsp = self.get_all_reports()  # on OnPrem/NG reports and templates located at the same place
        #     return parse_obj_as(list[Report], rsp)
        #
        # def get_audit_trail(self, description: Optional[str] = None,
        # audit_email: Optional[str] = None, **kwargs) -> list[AuditTrail]:
        #     """Get audit trail"""
        #     user_query = f'user:{audit_email}' if audit_email else ''
        #     query = f'{description} and {user_query}'.strip() if (description and audit_email) else description or user_query
        #     body = {"page": 0, "size": 200, "query": query}
        #     rsp = self.session.post(f'{self.xsoar_base_url}/settings/audits', json=body)
        #     raise_for_status(rsp)
        #     data = rsp.json()['audits']
        #     return parse_obj_as(list[AuditTrail], data)
        #
        # def export_data(self, **kwargs) -> str:
        # raise NotImplementedError("Export data is not implemented at this env yet")

    #
    # def get_all_layouts(self, **kwargs) -> list[Layout]:
    #     """
    #     Get all layouts
    #     Note that this brings layouts for incidents, indicators and threat intel reports
    #     """
    #     res = self.session.get(url=f'{self.xsoar_base_url}/layouts')
    #     raise_for_status(res)
    #     layouts = [Layout(**layout, original_rsp=layout) for layout in res.json()]
    #     return layouts

    def get_all_layout_rules(self) -> dict:
        raise NotImplementedError("Layout rules is not implemented at this env")


class XsoarClient(XsoarOnPremClient):
    XSRF_TOKEN_HEADER = "X-CSRF-TOKEN"
    CSRF_TOKEN_NAME = "csrf_token"
    PLATFORM_TYPE = "xsoar-ng"
    PRODUCT_TYPE = "XSOAR"
    SERVER_TYPE = "XSOAR SAAS"

    def __init__(
        self, xsoar_host: str, xsoar_user: str, xsoar_pass: str, tenant_name: str, project_id: str, cache: Cache | None = None
    ):
        super().__init__(xsoar_host, xsoar_user, xsoar_pass, tenant_name, cache)
        self.xsoar_host_base = xsoar_host.replace("https://", "").replace("http://", "").replace("/", "")

        self.xsoar_host_url = f"https://{self.xsoar_host_base}"
        self.xsoar_base_url = f"https://{self.xsoar_host_base}/xsoar"
        self.xsoar_api_url = f"https://{self.xsoar_host_base}/api"
        self.xsoar_webapp_url = f"https://{self.xsoar_host_base}/api/webapp"
        self.token_cache = Firestore(project_id)

    def update_user_data(self, body: dict):
        raise NotImplementedError("Update user data is not implemented at this env")

    def get_gsm_cloud_machine_details(self) -> tuple[dict, str]:
        secret_manager = GoogleSecreteManagerModule(GSM_SERVICE_ACCOUNT, AUTOMATION_GCP_PROJECT)  # type: ignore[arg-type]
        return secret_manager.get_secret(secret_id=self.tenant_name, with_version=True)  # type: ignore[return-value]

    def check_api_key_validity(self, cloud_machine_details: dict, secret_version: str):
        from SecretActions.add_build_machine import BUILD_MACHINE_GSM_API_KEY, BUILD_MACHINE_GSM_AUTH_ID

        required_api_fields = {BUILD_MACHINE_GSM_API_KEY, BUILD_MACHINE_GSM_AUTH_ID}
        if not required_api_fields.issubset(set(cloud_machine_details.keys())):
            raise InvalidAPIKey(
                self.tenant_name, f"Required fields {required_api_fields} are missing from secret version {secret_version}."
            )

        try:
            headers = {
                BUILD_MACHINE_GSM_AUTH_ID: str(cloud_machine_details[BUILD_MACHINE_GSM_AUTH_ID]),
                "Authorization": cloud_machine_details[BUILD_MACHINE_GSM_API_KEY],
                "Content-Type": "application/json",
            }
            machine_health_response = requests.get(f"https://api-{self.xsoar_host_base}/xsoar/health", headers=headers)
            health_check_success = machine_health_response.ok
        except requests.exceptions.ConnectionError:
            health_check_success = False
        if not health_check_success:
            raise InvalidAPIKey(
                self.tenant_name, f"Health check was unsuccessful with the API key provided from secret version {secret_version}."
            )
        logger.info(f"Health check passed successfully for {self.tenant_name} with secret version {secret_version}.")

    def create_and_save_api_key(self, token: str | None = None) -> tuple[dict, str]:
        from SecretActions.add_build_machine import add_build_machine_secret_to_gsm

        public_api_key = self.create_api_key(
            expiration=time_now().add(years=1),
            comment=f"Created by content build{f' (pipeline #{CI_PIPELINE_ID})' if CI_PIPELINE_ID else ''}",
        )
        logger.info(f"Created API key for {self.tenant_name}")
        cloud_machine_details, secret_version = add_build_machine_secret_to_gsm(
            server_id=self.tenant_name, machine_type=self.PLATFORM_TYPE, public_api_key=public_api_key, token_value=token
        )
        return cloud_machine_details, secret_version

    def login_using_gsm(self, token: str | None = None) -> tuple[dict, str]:
        """
        Gets the cloud machine API key from GSM and checks it.
        If it is not valid or doesn't exist, creates one and saves it to GSM.
        When providing a token for XsiamClient, also saves the token.
        """
        try:
            cloud_machine_details, secret_version = self.get_gsm_cloud_machine_details()
            self.check_api_key_validity(cloud_machine_details, secret_version)
        except (NotFound, InvalidAPIKey) as e:
            logger.error(f"Got an error while fetching API key for {self.tenant_name} from GSM: {e}")
            logger.info(f"Generating a new API key for {self.tenant_name}.")
            self.login_auth(force_login=True)
            cloud_machine_details, secret_version = self.create_and_save_api_key(token)
            self.check_api_key_validity(cloud_machine_details, secret_version)

        return cloud_machine_details, secret_version

    def login_via_okta(self, is_prod: bool):
        # self.inc_metric('login')

        self.session.cookies.clear()
        # Get SSO details
        res = self.session.get(url=self.xsoar_host_url)
        if "CSP credentials" in res.text:  # workaround for production CSP login
            logger.info("login using CSP credentials")
            logger.debug(f"{res.url=}\n{self.session.cookies=}\n{self.session.headers=}")
            res = self.session.post(res.url, data=dict(sso_type="csp"))

        # Extract token
        pattern = re.compile(r'"stateToken":"(.*?)"')
        login_page = res.text.replace("\\x", "%")  # JS escape sequences interfere with regex parsing of the contents
        if not (matches := re.findall(pattern, login_page)):
            raise Exception(f"Failed extracting stateToken for {self.xsoar_user=} on {self.xsoar_base_url}\n{res.text}")
        state_token = unquote(matches[0])  # Replace %xx escapes by their single-character equivalent

        OKTA_IDENTIFY_URL = "https://ssopreview.paloaltonetworks.com/idp/idx/identify"  # TODO move to constants
        OKTA_PROD_IDENTIFY_URL = "https://ssopreview.paloaltonetworks.com/idp/idx/identify"  # TODO GABI PRODUCTION?
        identify_url = OKTA_PROD_IDENTIFY_URL if is_prod else OKTA_IDENTIFY_URL
        identify_params = {"identifier": self.xsoar_user, "stateHandle": state_token}
        identify_res = self.session.post(identify_url, json=identify_params, headers=OKTA_HEADERS, verify=False)
        raise_for_status(identify_res)
        identify_json = identify_res.json()
        answer_params = {"credentials": {"passcode": self.xsoar_pass}, "stateHandle": identify_json.get("stateHandle")}
        answer_res = self.session.post(
            "https://ssopreview.paloaltonetworks.com/idp/idx/challenge/answer",
            json=answer_params,
            headers=OKTA_HEADERS,
            verify=False,
        )
        raise_for_status(answer_res)
        credentials_res_json = answer_res.json()
        okta_redirect = credentials_res_json["success"].get("href")
        # Do login
        # okta_params = {
        #     "username": self.xsoar_user,
        #     "password": self.xsoar_pass,
        #     "stateToken": state_token,
        #     "options": {"multiOptionalFactorEnroll": True, "warnBeforePasswordExpired": True},
        # }
        # okta_path = OKTA_PROD_AUTH_URL if is_prod else OKTA_AUTH_URL
        # okta_res = self.session.post(url=okta_path, json=okta_params, headers=OKTA_HEADERS)
        # raise_for_status(okta_res)
        # if not (okta_redirect := okta_res.json().get("_links", {}).get("next", {}).get("href")):
        #     raise SetupException(f'Failed extracting okta redirect link from {okta_res.json()}')

        # Follow redirect
        res = self.session.get(okta_redirect)
        raise_for_status(res)
        tenant_url = find_html_attribute(res.text, name="RelayState")
        saml_request = find_html_attribute(res.text, name="SAMLResponse")
        proxy_url = find_html_form_action(res.text)
        params = {"RelayState": tenant_url, "SAMLResponse": saml_request}

        # Complete login by sending SAML response to proxy url
        res = self.session.post(url=proxy_url, data=params, verify=False)  # type: ignore[arg-type]
        raise_for_status(res)

        # Imitate request sent by UI, to get csrf_token cookie
        res = self.session.get(f"{self.xsoar_api_url}/jwt/")
        raise_for_status(res)
        self._set_xsrf_header()

    def _cache_cookies(self):
        """Caches user's cookies in pytest.Cache object only"""
        if isinstance(self.cache, Cache):
            self.cache.set("cached_cookies", {self.xsoar_user: self.session.cookies.get_dict()})

    @retry(
        (ConnectionError, RemoteDisconnected, HTTPException, Exception, IOError),
        delay=3,
        tries=2,
        backoff=2,
        raise_original_exception=True,
    )
    def login_auth(self, force_login=False, **kwargs):
        """Try using cached login cookies to reduce amount of logins into the test systems"""
        is_prod = is_production()
        if force_login:
            self.login_via_okta(is_prod=is_prod)
            return

        collection = TokenCache.TOKEN_MGMT
        region = self.xsoar_base_url.split(".")[2] if is_prod else None
        document = f"{TokenCache.PROD_DOCUMENT}_{region}" if is_prod else TokenCache.DOCUMENT

        # lock to reduce race condition of several sessions running via xdist
        with FileLock(f"{self.xsoar_user}.lock", timeout=300):
            cached_cookies = self.cache.get("cached_cookies", {}) if isinstance(self.cache, Cache) else {}
            if cached_cookie := cached_cookies.get(self.xsoar_user):
                if self.is_cached_cookies_valid(cookies=cached_cookie):
                    return
            # lock to reduce race condition of several tenants running in parallel
            with lock_and_read(
                fs_client=self.token_cache, collection=collection, document=document, field=self.xsoar_user
            ) as cookies:
                # Check validity of received cookies
                if self.is_cached_cookies_valid(cookies=cookies):
                    self._cache_cookies()
                    return
                logger.info("Cached login cookies are not valid. Going to execute the login and update cache.")
                self.login_via_okta(is_prod=is_prod)

                # Add ttl info to newly generated cookies
                new_ttl = str(time_now().add(hours=TokenCache.MAX_TTL_HOURS).timestamp())
                logger.debug(f"Updating cookies with {new_ttl=}")
                self.session.cookies.update({"ttl": new_ttl})

                # Update the cookies in firestore - for other test runs to use
                self.token_cache.update_document_field(
                    collection=collection,
                    document=document,
                    field_name=self.xsoar_user,
                    field_value=self.session.cookies.get_dict(),
                )
                self._cache_cookies()

    def unlock_user(self, emails: list[str]):
        """Unlock locked users"""
        raise Exception("Users can't be unlocked on this env")

    def is_cached_cookies_valid(self, cookies: dict) -> bool:
        """Check whether current cookies are valid to use for test session by calling get versions api"""
        cookies_ttl = pendulum.from_timestamp(float(cookies.get("ttl", "0")))
        cookies_ttl_str = cookies_ttl.to_iso8601_string()
        logger.debug(
            f"Verify cookies ttl is far enough in the future (more than {TokenCache.MIN_TTL_ALLOWED} hours). {cookies_ttl_str=}"
        )
        if cookies_ttl > time_now().add(hours=TokenCache.MIN_TTL_ALLOWED):
            self.session.cookies.update(cookies)
            self._set_xsrf_header()
            with contextlib.suppress(JSONDecodeError, HTTPError, TooManyRedirects):
                self.get_version_info()
                logger.info(f"Using cached login cookies (valid until {cookies_ttl_str})")
                return True
            logger.info("Existing cookies are invalid")
        return False

    def logout_auth(self):
        # DO NOT logout at NG envs (SSO), as this will invalidate another active session
        pass

    def get_version_info(self) -> dict:
        # self.inc_metric('get_version_info')
        response = self.session.get(f"{self.xsoar_webapp_url}/version/")
        raise_for_status(response)
        versions = response.json()
        demisto_version = versions.pop("automation")
        versions.update(demisto_version)
        return versions

    def get_configuration(self) -> dict:
        response = self.session.get(f"{self.xsoar_api_url}/get_config")
        raise_for_status(response)
        return response.json()

    def set_log_level(self, xsoar_log_level: str | None = None):
        logger.debug("Not setting log level for XSOAR NG environment.")

    def search_api_keys(self) -> list[PublicApiKey]:
        """Search for API keys"""

        table_filter: dict = {
            "extraData": None,
            "filter_data": {
                "sort": [{"FIELD": "API_KEY_CREATION_TIME", "ORDER": "DESC"}],
                "filter": {},
                "free_text": "",
                "visible_columns": None,
                "locked": None,
                "paging": {"from": 0, "to": 100},
            },
            "jsons": [],
        }
        data = self.get_table_data(table_name=XdrTables.API_KEYS_TABLE, table_filter=table_filter)["DATA"]
        keys = [PublicApiKey.parse_api_key_from_table_data(key=key) for key in data]
        return keys

    def create_api_key(
        self, rbac_roles: list[str] | None = None, expiration: DateTime | None = None, comment: str | None = None, **kwargs
    ) -> PublicApiKey:
        """
        Calls XSOAR API to create an API key
        """
        rbac_roles = rbac_roles or ["app_superuser"]
        expiration = expiration or time_now().add(days=1)
        timestamp = to_epoch_timestamp(expiration)
        data = {
            "security_level": KeySecurityLevel.STANDARD.internal_name,
            "comment": comment,
            "rbac_roles": rbac_roles,
            "rbac_permissions": None,
            "expiration": timestamp,
        }
        res = self.session.post(url=f"{self.xsoar_webapp_url}/api_keys/generate", json=data)
        raise_for_status(res)
        key = res.json()["reply"]
        return PublicApiKey(id=key["id"], key=key["key"])

    def revoke_api_key(self, key_id: str):
        """Call XSOAR API to revoke an API key"""
        data = {"filter_data": {"filter": {"OR": [SearchTableField.API_KEY_ID.create_search_filter(search_value=key_id)]}}}
        res = self.session.post(url=f"{self.xsoar_webapp_url}/api_keys/delete", json=data)
        raise_for_status(res)

    def edit_api_key(self, comment: str, new_roles: list[str], key_id: int):
        """Edit API key"""
        body = {
            "filter_data": {"filter": {"OR": [{"SEARCH_FIELD": "API_KEY_ID", "SEARCH_TYPE": "EQ", "SEARCH_VALUE": key_id}]}},
            "update_data": {
                "API_KEY_SECURITY_LEVEL": KeySecurityLevel.STANDARD.internal_name,
                "API_KEY_COMMENT": comment,
                "API_KEY_RBAC_PERMISSIONS": None,
                "API_KEY_RBAC_ROLES": new_roles,
                "API_KEY_EXPIRATION_TIME": None,
            },
        }
        res = self.session.post(url=f"{self.xsoar_webapp_url}/api_keys/edit", json=body)
        raise_for_status(res)

    # def get_users(self, additional_extra_data: Optional[dict] = None, show_invites: bool = False) -> list[User]:
    #     """Call XSOAR users API to get info about users"""
    #     #self.inc_metric('get_users')
    #     extra_data = {"include_hidden_users": False, "show_invites": show_invites}
    #     if additional_extra_data:
    #         extra_data.update(additional_extra_data)
    #     data = {"filter_data": {"sort": [{"FIELD": "PRETTY_USER_NAME", "ORDER": "ASC"}]}, "extraData": extra_data}
    #     params = {'type': 'grid', 'table_name': XdrTables.USERS.value}
    #     res = self.session.post(url=f'{self.xsoar_webapp_url}/get_data', json=data, params=params)
    #     raise_for_status(res)
    #
    #     # Fetch recently seen users, since only login action triggers playground id initialization
    #     xsoar_active_users = super().get_users()
    #
    #     def parse_xsoar_ng_user(user: dict) -> User:
    #         return User(
    #             id=user['USERNAME'],
    #             name=user['PRETTY_USER_NAME'],
    #             email=user['USERNAME'],
    #             username=user['USERNAME'],
    #             roles=user['PRETTY_ROLE_NAME'],
    #             invitationUrl=user.get('INVITATION_URL'),
    #             disabled=user.get('LOCAL_USER_STATUS', None),
    #             groups=user.get('GROUPS', None),
    #             phone=user.get('PHONE_NUMBER', None),
    #             playgroundId=first([u.playground_id for u in xsoar_active_users if u.id == user['USERNAME']], None),
    #         )
    #
    #     return [parse_xsoar_ng_user(user) for user in res.json()['reply']['DATA']]
    #
    # def edit_user(self, user_name: list[str], new_role: Optional[XsoarRole] = None,
    # new_group: Optional[UserGroup] = None) -> dict:
    #     """Edit user"""
    #     data = {"user_emails": user_name}
    #     if new_group:
    #         data["groups"] = [new_group.group_id]
    #     if new_role:
    #         data["role_name"] = new_role.id
    #     rsp = self.session.post(f"{self.xsoar_webapp_url}/rbac/edit_user", json=data)
    #     raise_for_status(rsp)
    #     return rsp.json()
    #
    # def invite_user(self, user_data: NewUserData):
    #     """Invite user to XSOAR"""
    #     raise NotImplementedError('Not implemented by rocket on this env')
    #
    # def reset_invite_user(self, ids: list[str]):
    #     raise NotImplementedError('Not implemented by rocket on this env')
    #
    # def accept_invitation(self, activate_data: NewUserActivation):
    #     raise NotImplementedError('Not implemented by rocket on this env')

    def activate_user(self, email: str):
        data = {"user_emails": to_list(email)}
        rsp = self.session.post(f"{self.xsoar_webapp_url}/rbac/activate_users", json=data)
        raise_for_status(rsp)

    def deactivate_user(self, email: str):
        data = {"user_emails": to_list(email)}
        rsp = self.session.post(f"{self.xsoar_webapp_url}/rbac/inactivate_users", json=data)
        raise_for_status(rsp)

    def delete_users(self, emails: list[str]):
        raise NotImplementedError("Not implemented by rocket on this env")

    def delete_user_role(self, user_name: str):
        """Delete roles from user"""
        data = {"user_emails": [user_name]}
        rsp = self.session.post(f"{self.xsoar_webapp_url}/rbac/delete_users_role", json=data)
        raise_for_status(rsp)

    def sync_user_permission(self, user_name: str):
        """Immediately sync user permission, GENERIC_ALLOW_EXTERNAL_CONFIG_SETTING flag is required"""
        data = {"username": user_name}
        rsp = self.session.post(f"{self.xsoar_webapp_url}/rbac/reset_user_permissions", json=data)
        raise_for_status(rsp)

    def add_role(self, data: dict):
        """Add new role"""
        rsp = self.session.post(f"{self.xsoar_webapp_url}/rbac/add_role", json=data)
        raise_for_status(rsp)

    def edit_role(self, data: dict):
        """Edit role"""
        rsp = self.session.post(f"{self.xsoar_webapp_url}/rbac/edit_role", json=data)
        raise_for_status(rsp)

    def delete_role(self, role_id: str):
        """Delete role"""
        data = {"role_name": role_id}
        rsp = self.session.post(f"{self.xsoar_webapp_url}/rbac/delete_role", json=data)
        raise_for_status(rsp)

    def get_permissions(self) -> dict:
        """Get existing permissions"""
        data = {"include_roles": False}
        rsp = self.session.post(f"{self.xsoar_webapp_url}/rbac/get_permissions", json=data)
        raise_for_status(rsp)
        return rsp.json()["reply"]

    def add_group(self, data: dict):
        """Add user group"""
        rsp = self.session.post(f"{self.xsoar_webapp_url}/rbac/groups/add", json=data)
        raise_for_status(rsp)

    def update_group(self, data: dict):
        """Update user group"""
        rsp = self.session.post(f"{self.xsoar_webapp_url}/rbac/groups/update", json=data)
        raise_for_status(rsp)

    def delete_group(self, group_id: str):
        """Delete user group"""
        data = {"group_ids": [group_id]}
        rsp = self.session.post(f"{self.xsoar_webapp_url}/rbac/groups/delete", json=data)
        raise_for_status(rsp)

    #
    # def get_user_groups(self) -> dict:
    #     """Get all user groups"""
    #     return self.get_table_data(table_name=XdrTables.RBAC_GROUPS_TABLE)['DATA']
    #
    # def get_roles(self) -> list[XsoarRole]:
    #     """Call XSOAR roles API to get info about user roles"""
    #     data = self.get_table_data(table_name=XdrTables.ROLES)['DATA']
    #     roles = [
    #         XsoarRole(
    #             id=role['ROLE_NAME'],
    #             name=role['PRETTY_NAME'],
    #             permissions=role['PERMISSIONS'],
    #             pages_access=role.get('PAGES_ACCESS'),
    #             description=role['DESCRIPTION'],
    #             is_multi_tenant=role['IS_MULTI_TENANT'],
    #             is_custom=role['IS_CUSTOM'],
    #             created_by=role['CREATED_BY'],
    #         )
    #         for role in data
    #     ]
    #     return roles
    #

    def get_table_data(self, table_name: XdrTables, table_filter: dict | None = None) -> dict:
        """Fetch table data from XDR/XSIAM/XSOAR-NG"""
        table_filter = table_filter or {"filter_data": {}}
        # self.inc_metric('get_table_data', table_name)
        params = {"type": "grid", "table_name": table_name.value}
        res = self.session.post(url=f"{self.xsoar_webapp_url}/get_data", json=table_filter, params=params)
        raise_for_status(res)
        try:
            result = res.json()["reply"]
        except JSONDecodeError as e:
            raise Exception(
                f"Failed parsing get_table_data response: {e.msg}\n{table_name=}, {table_filter=}\nRaw response: {res.text}"
            )
        if (count := result.get("FILTER_COUNT")) and count < len(result["DATA"]):
            logger.warning(
                f"Not all results were returned - {len(result['DATA'])} "
                f"instead of {result['FILTER_COUNT']}. Consider pagination."
            )
        return result

    #
    # def get_audit_trail(
    #     self, description: Optional[str] = None, audit_email: Optional[str] = None, sort_descending: bool = True
    # ) -> list[AuditTrail]:
    #     """Get audit trail"""
    #     sort_order = 'DESC' if sort_descending else 'ASC'
    #     filters = []
    #     if description:
    #         filters.append(SearchTableField.AUDIT_DESCRIPTION.create_search_filter(search_value=description))
    #     if audit_email:
    #         filters.append(SearchTableField.AUDIT_OWNER_EMAIL.create_search_filter(search_value=audit_email))
    #     table_filter = {
    #         "extraData": None,
    #         "filter_data": {
    #             "sort": [{"FIELD": "AUDIT_INSERT_TIME", "ORDER": sort_order}],
    #             "filter": {"AND": filters},
    #             "free_text": "",
    #             "visible_columns": None,
    #             "locked": None,
    #             "paging": {"from": 0, "to": 100},
    #         },
    #         "jsons": [],
    #     }
    #     rsp = self.get_table_data(table_name=XdrTables.AUDIT_TRAIL, table_filter=table_filter)['DATA']
    #     return parse_obj_as(list[AuditTrail], rsp)

    def export_data(self, body: dict, table_name: str) -> str:
        """Export data"""
        rsp = self.session.post(f"{self.xsoar_webapp_url}/prepare_link?type=grid&table_name={table_name}", json=body)
        raise_for_status(rsp)
        key_uuid = rsp.json()["reply"]
        download_rsp = self.session.get(f"{self.xsoar_webapp_url}/get_data_by_key?key_uuid={key_uuid}")
        raise_for_status(download_rsp)
        return download_rsp.content.decode("utf-8")

    #
    # def get_all_layouts(self, object_type: LayoutObjectType) -> list[Layout]:
    #     """Get all layouts"""
    #     raw_data = []
    #
    #     def _get_layouts_from_tenant(from_page: int = 0, to_page: int = 100):
    #         table_filter = {
    #             "extraData": {"world": object_type.value},
    #             "filter_data": {
    #                 "sort": [],
    #                 "filter": {},
    #                 "free_text": "",
    #                 "visible_columns": None,
    #                 "locked": None,
    #                 "paging": {"from": from_page, "to": to_page},
    #             },
    #             "jsons": [],
    #         }
    #         rsp = self.get_table_data(table_name=XdrTables.LAYOUTS, table_filter=table_filter)
    #         raw_data.extend(rsp['DATA'])
    #
    #         total_fetched = len(raw_data)
    #         if rsp['TOTAL_COUNT'] > total_fetched:
    #             _get_layouts_from_tenant(from_page=total_fetched, to_page=total_fetched + 100)
    #
    #     _get_layouts_from_tenant()
    #
    #     def parse_layouts(layout: dict) -> Layout:
    #         return Layout(
    #             id=layout['LAYOUT_ID'],
    #             name=layout['LAYOUT_NAME'],
    #             version=layout['LAYOUT_DETAILS']['version'],
    #             modified=layout['LAYOUT_MODIFY_TIME'],
    #             group=layout['LAYOUT_DETAILS']['group'],
    #             definition_id=layout['LAYOUT_DETAILS']['definitionId'],
    #             description=layout['LAYOUT_DESCRIPTION'],
    #             original_rsp=layout,
    #         )
    #
    #     layouts = [parse_layouts(dashboard) for dashboard in raw_data]
    #     return layouts
    #
    # def get_all_layout_rules(self) -> dict:
    #     return self.get_table_data(table_name=XdrTables.LAYOUT_RULES)['DATA']


class OppClient(XsoarClient):
    XSRF_TOKEN_HEADER = "Cookie"
    PLATFORM_TYPE = "opp"
    PRODUCT_TYPE = "XSOAR"

    def _set_xsrf_header(self):
        auth_headers = "; ".join(f"{k}={v}" for k, v in self.session.cookies.get_dict().items())
        self.session.headers[self.XSRF_TOKEN_HEADER] = auth_headers

    def login_auth(self, **kwargs):
        tries = kwargs.get("tries", 2)

        @retry(
            (ConnectionError, RemoteDisconnected, HTTPException, Exception, IOError),
            delay=3,
            tries=tries,
            backoff=1.5,
            raise_original_exception=True,
        )
        def login_auth_with_retry():
            # self.inc_metric('login')
            self.session.get(f"{self.xsoar_base_url}/login", timeout=self.login_timout)
            login_res = self.session.post(
                f"{self.xsoar_api_url}/users/public/login",
                timeout=self.login_timout,
                json={"email": self.xsoar_user, "password": self.xsoar_pass},
            )
            raise_for_status(login_res)
            if not (token := login_res.json()):
                raise KeyError("Failed to extract token from login request")
            self._set_xsrf_header()
            callback_rsp = self.session.post(f"{self.xsoar_host_url}/login/local/callback", data=token)
            raise_for_status(callback_rsp)

        login_auth_with_retry()

    def unlock_user(self, emails: list[str]):
        """Unlock locked users"""
        data = {"user_emails": emails}
        rsp = self.session.post(f"{self.xsoar_webapp_url}/users/local/unlock", json=data)
        raise_for_status(rsp)

    def send_invitation_only(self, data: dict) -> dict:
        """
        Send invitation to users
        """
        res = self.session.post(f"{self.xsoar_webapp_url}/users/invite_users", json=data)
        raise_for_status(res)
        return res.json()["reply"]

    def send_forgot_my_password(self, email: str):
        """Send Forgot My Password"""
        data = {"email": email}
        res = requests.post(f"{self.xsoar_api_url}/users/public/password/reset", json=data, verify=False)
        raise_for_status(res)

    # def reset_password_confirm(self, email: str, reset_link: str, password: str):
    #     """Reset Password Confirm"""
    #     token = self._extract_invite_user_token(reset_link)
    #     data = {
    #         "email": email,
    #         "password": password,
    #         "password_verification": password,
    #         "token": token,
    #     }
    #     res = requests.post(f'{self.xsoar_api_url}/users/public/password/reset/confirm', json=data, verify=False)
    #     raise_for_status(res)
    #
    # def invite_user(self, user_data: NewUserData) -> str:
    #     """Invite user to XSOAR"""
    #     users = [{"email": user_data.email, "first_name": user_data.firstname, "last_name": user_data.lastname}]
    #     data = {"csv_data": None, "role": user_data.roles, "groups": [], "users_data": users}
    #     res = self.send_invitation_only(data=data)
    #     if not res.get('succeeded_count'):
    #         raise InviteUserError(res)
    #     all_users = self.get_users(show_invites=True)
    #     invitation_url = first(user for user in all_users if user.email == user_data.email).invitation_url
    #     assert invitation_url, f'Missing invitation url for {user_data.email}'
    #     return invitation_url
    #
    # def _extract_invite_user_token(self, invitation_url) -> str:
    #     token = re.search(pattern=r'token=(.*)', string=invitation_url)
    #     assert token, f'Failed to extract token from {invitation_url=}'
    #     return token.group(1)
    #
    # def resend_users_invitation(self, users: list[User]):
    #     emails = [user.email for user in users]
    #     data = {"user_emails": emails}
    #     res = self.session.post(f'{self.xsoar_webapp_url}/users/invitation/resend', json=data)
    #     raise_for_status(res)
    #
    # def accept_invitation(self, activate_data: NewUserActivation) -> User:
    #     token = self._extract_invite_user_token(activate_data.invitation_url)
    #     data = {
    #         "first_name": activate_data.username,
    #         "last_name": activate_data.username,
    #         "password": activate_data.password,
    #         "password_verification": activate_data.password,
    #         "email": activate_data.username,
    #         "token": token,
    #     }
    #
    #     res = requests.post(f'{self.xsoar_api_url}/users/public/invitation/accept', json=data, verify=False)
    #     raise_for_status(res)
    #     return first(user for user in self.get_users() if user.email == activate_data.username)
    #
    # def cancel_users_invitation(self, users: list[User]):
    #     emails = [user.email for user in users]
    #     data = {"user_emails": emails}
    #     res = self.session.post(f'{self.xsoar_webapp_url}/users/invitation/cancel', json=data)
    #     raise_for_status(res)
    #
    # def delete_users(self, emails: list[str]):
    #     data = {"user_emails": emails}
    #     rsp = self.session.post(f'{self.xsoar_webapp_url}/users/local/delete', json=data)
    #     raise_for_status(rsp)
    #
    # def set_user_details(self, user: User, first_name: Optional[str], last_name: Optional[str], phone: Optional[str]):
    #     """Set user details"""
    #     data = {
    #         "user_first_name": first_name or user.username,
    #         "user_last_name": last_name or user.username,
    #         "user_email": user.email,
    #         "phone_number": phone or user.phone,
    #     }
    #     rsp = self.session.post(f"{self.xsoar_webapp_url}/rbac/set_user_data", json={"user_data": data})
    #     raise_for_status(rsp)
    #
    # def set_user_pref_details(
    #     self, user: User, first_name: Optional[str], last_name: Optional[str], phone: Optional[str], password: Optional[str]
    # ):
    #     """Set user preferences details"""
    #     data = {
    #         "email": user.email,
    #         "firstname": first_name or user.username,
    #         "lastname": last_name or user.username,
    #         "password": password or "",
    #         "password_verification": password or "",
    #         "phone_number": phone or user.phone,
    #     }
    #     rsp = self.session.post(f"{self.xsoar_webapp_url}/users/local/update", json=data)
    #     raise_for_status(rsp)


class XsiamClient(XsoarClient):
    PLATFORM_TYPE = "xsiam"
    PRODUCT_TYPE = "XSIAM"
    SERVER_TYPE = "XSIAM"

    def __init__(
        self, xsoar_host: str, xsoar_user: str, xsoar_pass: str, tenant_name: str, project_id: str, cache: Cache | None = None
    ):
        super().__init__(xsoar_host, xsoar_user, xsoar_pass, tenant_name, project_id, cache)
        self.public_api_url_prefix = f"https://api-{self.xsoar_host_base}/public_api/v1"
        self._public_api_key = None

    def logout_auth(self):
        # DO NOT logout at NG envs (SSO), as this will invalidate another active session;
        # Delete session PAPI used to generate incidents if exists
        if self._public_api_key:
            self.revoke_api_key(key_id=self.public_api_key.id)

    @cached_property
    def public_api_key(self):
        self._public_api_key = self.create_api_key(comment="Session key")  # type: ignore[assignment]
        return self._public_api_key

    def save_tenant_token_to_gsm(self, token: str | None = None) -> tuple[dict, str]:
        from SecretActions.add_build_machine import add_build_machine_secret_to_gsm

        logger.info(f"Saving token of {self.tenant_name} to GSM.")
        cloud_machine_details, secret_version = add_build_machine_secret_to_gsm(
            server_id=self.tenant_name, machine_type=self.PLATFORM_TYPE, token_value=token
        )
        return cloud_machine_details, secret_version  # includes XSIAM token

    def login_using_gsm(self, token: str | None = None):
        cloud_machine_details, secret_version = super().login_using_gsm(token)
        if BUILD_MACHINE_GSM_TOKEN not in cloud_machine_details:
            cloud_machine_details, secret_version = self.save_tenant_token_to_gsm(token)

        return cloud_machine_details, secret_version

    #
    # def load_incident(self, incident_id: str, direct_load_from_xsoar: bool = False, **kwargs) -> Incident:
    #     """
    #     Search for incident by its internal_id field value, raise exception if it doesn't exist
    #     @param incident_id: incident id to load
    #     @param direct_load_from_xsoar: for specific use cases, like playbook debug, we have to use "legacy" xsoar api endpoint
    #     """
    #     if direct_load_from_xsoar:
    #         return super().load_incident(incident_id=incident_id, direct_load_from_xsoar=direct_load_from_xsoar)
    #     table_filter = {"filter_data": {"filter":
    #     {"AND": [SearchTableField.ALERT_ID.create_search_filter(search_value=incident_id)]}}}
    #     if not (data := self.get_table_data(table_name=XdrTables.ALERTS, table_filter=table_filter)['DATA']):
    #         raise MissingIncident(msg=f'Could not find {incident_id=}')
    #     alert = Alert.parse_obj(data[0])
    #     log.debug(f'Parsed alert: {alert}')
    #     incident = Incident.parse_alert_as_incident(alert)
    #     return incident
    #
    # def find_incidents_by_name(self, name: str, query_size: int = 100) -> list[Incident]:
    #     """Find incidents by name"""
    #     query = {"AND": [SearchTableField.ALERT_NAME.create_search_filter(search_value=name,
    #     search_type=SearchTableOperator.EQ)]}
    #     return self.find_incidents_using_query(query=query, query_size=query_size)
    #
    # def find_incidents_using_query(self, query: dict, query_size: int = 100, **kwargs) -> list[Incident]:
    #     """Find incidents using query"""
    #     table_filter = {"filter_data": {"filter": query, "paging": {"from": 0, "to": query_size}}}
    #     alerts_raw = self.get_table_data(table_name=XdrTables.ALERTS, table_filter=table_filter)['DATA']
    #     if not (alerts_parsed := parse_obj_as(list[Alert], alerts_raw)):
    #         raise MissingIncident(f'No incidents found with {query=}')
    #     incidents = [Incident.parse_alert_as_incident(alert) for alert in alerts_parsed]
    #     return incidents

    def search_in_incident(self, query: str, query_size: int = 50, last_days: int = 2) -> dict:
        """Search data IN incidents"""
        raise NotImplementedError("Not implemented by rocket on this env")

    #
    # def find_incidents_using_query_raw(self, query: dict) -> list[dict]:
    #     """
    #     Find incidents using query
    #     Note: This is different from find_incidents_using_query because it doesn't return modeled incidents!
    #     """
    #     table_filter = {"filter_data": query}
    #     incidents = self.get_table_data(table_name=XdrTables.ALERTS, table_filter=table_filter)['DATA']
    #     if not incidents:
    #         raise MissingIncident(f'No incidents found with {query=}')
    #     return incidents
    #
    # def find_incidents_by_integration_source_instance(self, source_instance: str, query_size: int = 100) -> list[Incident]:
    #     """Find incidents by integration source instance"""
    #     query = {"AND": [SearchTableField.SOURCE_INSTANCE.create_search_filter(search_value=source_instance)]}
    #     return self.find_incidents_using_query(query=query, query_size=query_size)
    #
    # def generate_incident(self, incident_data: NewIncident) -> Incident:
    #     """Generate new incident(alert) in XSIAM tenant using parsed alert public API"""
    #
    #     @retry(exceptions=HTTPError, tries=5, delay=2, backoff=2, jitter=(1, 3), raise_original_exception=True)
    #     def insert_incident():
    #         # in case XSIAM gets to many requests to this PAPI, it will return 429 error, so we will retry on HTTPError
    #         headers = {
    #             "Authorization": self.public_api_key.key,
    #             "x-xdr-auth-id": self.public_api_key.id,
    #             "Content-Type": "application/json",
    #         }
    #         alert_payload = {"request_data": {"alerts": [incident_data.to_xsiam_alert_dict]}}
    #         res = requests.post(url=f'{self.public_api_url_prefix}/alerts/insert_parsed_alerts/',
    #         headers=headers, json=alert_payload)
    #         raise_for_status(res)
    #
    #     @retry(exceptions=MissingIncident, tries=12, delay=10, raise_original_exception=True)
    #     def wait_for_incident():
    #         to = incident_data.created.add(minutes=1) if incident_data.created > time_now() else time_now()
    # allow future incidents
    #         query = {
    #             "AND": [
    #                 SearchTableField.ALERT_NAME.create_search_filter(search_value=incident_data.name,
    #                 search_type=SearchTableOperator.EQ),
    #                 SearchTableField.SOURCE_INSERT_TS.create_search_filter(
    #                     search_value={
    #                         'from': to_epoch_timestamp(incident_data.created.subtract(microseconds=100)),
    #                         'to': to_epoch_timestamp(to),
    #                     },
    #                     search_type=SearchTableOperator.RANGE,
    #                 ),
    #             ]
    #         }
    #         return first(self.find_incidents_using_query(query=query))
    #
    #     insert_incident()
    #     incident_id = wait_for_incident().id
    #
    #     data = {
    #         "request_data": {
    #             "alerts": {
    #                 incident_id: {
    #                     "alert_fields": {"alert_type": incident_data.type, **incident_data.custom_fields},
    #                     "incident_fields": {},
    #                 }
    #             }
    #         }
    #     }
    #
    #     # Update the alert using internal api to propagate type and custom fields
    #     res = self.session.post(url=f'{self.xsoar_webapp_url}/xsiam/alerts/update_alerts', json=data)
    #     raise_for_status(res)
    #
    #     incident = self.load_incident(incident_id=incident_id)
    #     return incident
    #
    # def close_incident(
    #     self, incident_id: str, resolution_status: AlertStatus = AlertStatus.RESOLVED_KNOWN_ISSUE, resolution_comment: str = ""
    # ) -> dict:
    #     """Change specific incident status, by default will close incident"""
    #     data = {
    #         "filter_data": {"filter": {"AND": [SearchTableField.ALERT_ID.create_search_filter(search_value=incident_id)]}},
    #         "filter_type": "static",
    #         "update_data": {"resolution_status": resolution_status.value, "resolution_comment": resolution_comment},
    #     }
    #     rsp = self.session.post(f"{self.xsoar_webapp_url}/alerts/update_alerts", json=data)
    #     raise_for_status(rsp)
    #     return rsp.json()
    #
    # def start_investigation(self, incident_id: str, **kwargs) -> dict:
    #     """Start incident investigation"""
    #     rsp = self.session.post(f"{self.xsoar_base_url}/incident/investigate/v2", json={"id": incident_id, "version": 0})
    #     raise_for_status(rsp)
    #     return rsp.json()
    #
    # def download_attachment(self, attachment: Attachment) -> bytes:
    #     """Download attachments"""
    #     #self.inc_metric('download_attachment')
    #     path = attachment.path.split(f'_{attachment.name}')[0]
    #     artifact_path = f'{path}_{attachment.name}/{attachment.name}'
    #     res_download = self.session.get(url=f'{self.xsoar_base_url}/artifact/download/{artifact_path}', stream=True)
    #     raise_for_status(res_download)
    #     return res_download.content
    #
    # def get_all_dashboards(self) -> list[Dashboard]:
    #     """Get all dashboards"""
    #     table_filter = {
    #         "extraData": None,
    #         "filter_data": {
    #             "sort": [{"FIELD": "DASHBOARDS_TIME_GENERATED", "ORDER": "DESC"}],
    #             "filter": {},
    #             "free_text": "",
    #             "visible_columns": None,
    #             "locked": None,
    #             "paging": {"from": 0, "to": 100},
    #         },
    #         "jsons": [],
    #     }
    #     raw_data = self.get_table_data(table_name=XdrTables.DASHBOARDS, table_filter=table_filter)['DATA']
    #
    #     def parse_dashboard(dashboard: dict) -> Dashboard:
    #         return Dashboard(
    #             id=dashboard['DASHBOARDS_ID'],
    #             name=dashboard['DASHBOARDS_NAME'],
    #             pack_id=dashboard['DASHBOARDS_PACKAGE_ID'],
    #         )
    #
    #     return [parse_dashboard(dashboard) for dashboard in raw_data]

    def get_all_reports(self) -> list[dict]:
        raise NotImplementedError("Reports response was not modeled yet")

    #
    # def get_all_report_templates(self) -> list[Report]:
    #     """Get all report templates"""
    #     table_filter = {
    #         "extraData": None,
    #         "filter_data": {
    #             "sort": [{"FIELD": "REPORTS_TEMPLATES_TIME_CREATED", "ORDER": "DESC"}],
    #             "filter": {},
    #             "free_text": "",
    #             "visible_columns": None,
    #             "locked": None,
    #             "paging": {"from": 0, "to": 200},
    #         },
    #         "jsons": [],
    #     }
    #     raw_data = self.get_table_data(table_name=XdrTables.REPORTS_TEMPLATES, table_filter=table_filter)['DATA']
    #
    #     def parse_report_template(report: dict) -> Report:
    #         return Report(
    #             id=report['REPORTS_TEMPLATES_ID'],
    #             name=report['REPORTS_TEMPLATES_REPORT_NAME'],
    #             description=report['REPORTS_TEMPLATES_REPORT_DESCRIPTION'],
    #             pack_name=report['REPORTS_TEMPLATES_PRETTY_USER'],
    #         )
    #
    #     return [parse_report_template(report) for report in raw_data]


class XsoarBaseConnector:
    def __init__(self, xsoar_client: XsoarClient):
        self.session = xsoar_client.session
        # #self.inc_metric = xsoar_client.inc_metric
        self.base_url = xsoar_client.xsoar_base_url
        self.webapp_url = xsoar_client.xsoar_webapp_url
        self.client = xsoar_client


SERVER_TYPE_TO_CLIENT_TYPE: dict[str | None, type[XsoarClient]] = {
    XsoarClient.SERVER_TYPE: XsoarClient,
    XsiamClient.SERVER_TYPE: XsiamClient,
}
