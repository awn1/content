import logging
from datetime import datetime, timezone
from typing import Any

import requests
from urllib3.util import Retry

from Tests.scripts.infra.utils.requests_handler import TimeoutHTTPAdapter, raise_for_status
from Tests.scripts.infra.utils.text import remove_empty_elements
from Tests.scripts.infra.xsoar_api import XsiamClient, XsoarClient

logger = logging.getLogger(__name__)

DEFAULT_TTL = 48  # hours


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
        self.session.mount(
            prefix="http://",
            adapter=TimeoutHTTPAdapter(timeout=self.session_timout, max_retries=retry_strategy),
        )
        self.session.headers["Content-Type"] = "application/json"
        self.session.verify = False  # Disable SSL verification since we're working with self-signed certs here.
        self.base_url = base_url
        self.data_api_key = {"api_key": api_key}

    def get_request(self, url, data):
        response = self.session.get(url=f"{self.base_url}/{url}", json=self.data_api_key | data)
        raise_for_status(response)
        return response

    def post_request(self, url: str, data: dict):
        response = self.session.post(url=f"{self.base_url}/{url}", json=self.data_api_key | data)
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
        res = self.get_request(
            f"api/v4.0/disposable/get-disposable-group-max-tokens/{group_owner}",
            self.data_api_key,
        )
        return res.json()["disposable_max_allowed_tokens"]

    def create_disposable_tenant(
        self,
        owner: str,
        group_owner: str,
        server_type: str,
        viso_version: str = "",
        frontend_version: str = "",
        backend_version: str = "",
        xsoar_version: str = "",
        pipeline_version: str = "",
        storybuilder_version: str = "",
        rocksdb_version: str = "",
        scortex_version: str = "",
        vsg_version: str = "",
        ttl: int = DEFAULT_TTL,
    ) -> dict:
        """
        Create a new disposable tenant with the provided parameters.
        """
        if server_type not in (XsoarClient.SERVER_TYPE, XsiamClient.SERVER_TYPE):
            raise ValueError(f"Invalid server type: {server_type}")

        data = {
            "owner": owner,
            "token_group": group_owner,
            "viso_version": viso_version,
            "fake_license": True,
            "versions": {
                "frontend": frontend_version,
                "backend": backend_version,
                "xsoar": xsoar_version,
                "pipeline": pipeline_version,
                "storybuilder": storybuilder_version,
                "rocksdb": rocksdb_version,
                "scortex": scortex_version,
                "vsg": vsg_version,
            },
            "ttl": ttl,
            "flow_variables_override": {
                "non_pool_provision": True,
                "allow_xdr_gitlab_networks": True,
            },
        }

        if server_type == XsoarClient.SERVER_TYPE:
            data["xsoar_license"] = 1
        elif server_type == XsiamClient.SERVER_TYPE:
            data["xsiam_agents"] = 1
            data["xsiam_gb"] = 1

        res = self.post_request("api/v4.0/disposable/create", remove_empty_elements(data))
        return res.json()

    def get_tenant(self, tenant_id):
        """
        Get information about a specific tenant.
        """
        res = self.get_request(f"api/v4.0/tenants/{tenant_id}", {})
        return res.json()

    def update_config_map(
        self,
        lcaas_ids: list[str],
        config_map_name: str,
        map_dict: dict[str, str] | None = None,
        keys_to_delete: list[str] | None = None,
    ) -> dict:
        """
        Update the configuration map for the given lcaas_ids.
        """
        data = {
            "lcaas_ids": lcaas_ids,
            "deploy_details": {"config_maps": {config_map_name: {"update": map_dict, "delete": keys_to_delete}}},
        }
        res = self.post_request("api/v4.0/soft-deploy/configmap", data)
        return res.json()

    def get_available_tokens_for_group(self, group_owner: str) -> int:
        """
        Get the number of available disposable tokens for the given group owner.
        """
        tokens_count = self.get_disposable_token_count(group_owner)
        disposable_tenants = self.get_all_tenants(group_owner, fields=["ttl"])
        # Filter out expired disposable tenants (logic aligned with DevOps code)
        used_disposable_tenants = [t for t in disposable_tenants if datetime.now(timezone.utc).timestamp() < float(t["ttl"])]
        return tokens_count - len(used_disposable_tenants)

    def local_playbook(
        self, lcaas_ids: list[str], playbook_name: str, run_with_executor_sa: bool, playbook_vars: dict | None
    ) -> dict:
        """
        Run playbook locally.
        """
        data: dict[Any, Any] = {
            "lcaas_ids": lcaas_ids,
            "use_only_lcaas_ids": True,
            "deploy_details": {
                "playbook_name": playbook_name,
                "run_with_executor_sa": run_with_executor_sa,
            },
        }
        if playbook_vars is not None:
            data["deploy_details"]["playbook_vars"] = playbook_vars
        res = self.post_request("api/v4.0/soft-deploy/local-playbook", data)
        return res.json()

    def start_tenants(self, lcaas_ids: list[str]) -> dict:
        """
        Start the given tenants.
        """
        return self.local_playbook(lcaas_ids, "start_stop_tenant", True, {"action": "start"})

    def stop_tenants(self, lcaas_ids: list[str]) -> dict:
        """
        Stop the given tenants.
        """
        return self.local_playbook(lcaas_ids, "start_stop_tenant", True, {"action": "stop"})
