import logging

import requests
from infra.utils.requests_handler import TimeoutHTTPAdapter, raise_for_status
from urllib3.util import Retry

logger = logging.getLogger(__name__)


class VisoAPI:
    def __init__(self, base_url: str, api_key: str):
        retry_strategy = Retry(
            # allowed_methods=frozenset(["HEAD", "GET", "PUT", "DELETE", "OPTIONS", "TRACE", "POST"]),
            total=5,
            connect=3,
            backoff_factor=0.5,
            respect_retry_after_header=False,
        )  # retry connection errors (not HTTPErrors)
        self.session_timout = 60  # default 1 minute timeout for all API calls
        self.session = requests.Session()
        self.session.mount(prefix="http://", adapter=TimeoutHTTPAdapter(timeout=self.session_timout, max_retries=retry_strategy))
        self.session.headers["Content-Type"] = "application/json"
        self.session.verify = False  # Disable SSL verification since we're working with self-signed certs here.
        self.base_url = base_url
        self.data_api_key = {"api_key": api_key}

    def get_request(self, url, data):
        response = self.session.get(url=f"{self.base_url}/{url}", json=self.data_api_key | data)
        raise_for_status(response)
        return response

    def get_all_tenants(self, group_owner, fields: str | list[str] = "all"):
        """
        Get all tenants for group owner.
        """
        data = {"tenant_filters": {"owner_group": group_owner}, "fields": fields}
        res = self.get_request("api/v4.0/tenants/", data)
        return res.json()

    def get_disposable_token_count(self, group_owner) -> int:
        """
        Get disposable tenants token count for group owner.
        """
        res = self.get_request(f"api/v4.0/disposable/get-disposable-group-max-tokens/{group_owner}", self.data_api_key)
        return res.json()["disposable_max_allowed_tokens"]
