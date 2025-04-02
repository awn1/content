import argparse
import json
import os
import subprocess
import sys
import uuid
import zipfile
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from enum import IntEnum
from pathlib import Path
from pprint import pformat
from time import sleep
from typing import Any
from urllib.parse import quote_plus

import demisto_client
import json5
from demisto_sdk.commands.common.constants import FileType, MarketplaceVersions
from demisto_sdk.commands.common.git_util import GitUtil
from demisto_sdk.commands.common.tools import find_type, format_version, get_yaml, listdir_fullpath, run_command, str2bool
from demisto_sdk.commands.test_content.constants import SSH_USER
from demisto_sdk.commands.test_content.tools import is_redhat_instance, update_server_configuration
from packaging.version import Version
from ruamel import yaml

from SecretActions.add_build_machine import BUILD_MACHINE_GSM_API_KEY, BUILD_MACHINE_GSM_AUTH_ID
from SecretActions.google_secret_manager_handler import get_secrets_from_gsm
from Tests.Marketplace.common import get_json_file, get_packs_with_higher_min_version
from Tests.Marketplace.marketplace_services import get_last_commit_from_index
from Tests.Marketplace.search_and_install_packs import search_and_install_packs_and_their_dependencies, upload_zipped_packs
from Tests.scripts.collect_tests.constants import TEST_PLAYBOOKS
from Tests.scripts.infra.secret_manager import SecretManager
from Tests.scripts.infra.xsoar_api import XsiamClient, XsoarClient
from Tests.scripts.utils import logging_wrapper as logging
from Tests.scripts.utils.log_util import install_logging
from Tests.test_content import get_server_numeric_version
from Tests.test_integration import __get_integration_config as get_integration_config
from Tests.test_integration import disable_all_integrations, test_integration_instance

MARKET_PLACE_MACHINES = ("master",)
SKIPPED_PACKS = ["NonSupported", "ApiModules"]
NO_PROXY = ",".join(
    [
        "oproxy.demisto.ninja",
        "oproxy-dev.demisto.ninja",
    ]
)
NO_PROXY_CONFIG = {"python.pass.extra.keys": f"--env##no_proxy={NO_PROXY}"}  # noqa: E501
DOCKER_HARDENING_CONFIGURATION = {
    "docker.cpu.limit": "1.0",
    "docker.run.internal.asuser": "true",
    "limit.docker.cpu": "true",
    "python.pass.extra.keys": f"--memory=1g##--memory-swap=-1##--pids-limit=256##--ulimit=nofile=1024:8192##--env##no_proxy={NO_PROXY}",  # noqa: E501
    "powershell.pass.extra.keys": f"--env##no_proxy={NO_PROXY}",
    "monitoring.pprof": "true",
    "enable.pprof.memory.dump": "true",
    "limit.memory.dump.size": "14000",
    "memdump.debug.level": "1",
}
DOCKER_HARDENING_CONFIGURATION_FOR_PODMAN = {"docker.run.internal.asuser": "true"}
MARKET_PLACE_CONFIGURATION = {
    "content.pack.verify": "false",
    "marketplace.initial.sync.delay": "0",
    "content.pack.ignore.missing.warnings.contentpack": "true",
}
AVOID_DOCKER_IMAGE_VALIDATION = {"content.validate.docker.images": "false"}
ID_SET_PATH = "./artifacts/id_set.json"
XSOAR_SERVER_TYPE = "XSOAR"
SERVER_TYPES = [XSOAR_SERVER_TYPE, XsoarClient.SERVER_TYPE, XsiamClient.SERVER_TYPE]
MARKETPLACE_TEST_BUCKET = {
    "xsoar": "marketplace-ci-build-xsoar-dev/content/builds",
    "marketplacev2": "marketplace-ci-build-v2-dev/content/builds",
    "xpanse": "marketplace-ci-build-xpanse-dev/content/builds",
    "xsoar_saas": "marketplace-ci-build-xsoar-saas-dev/content/builds",
}
MARKETPLACE_XSIAM_BUCKETS = "marketplace-v2-dist-dev/upload-flow/builds-xsiam"
ARTIFACTS_FOLDER_MPV2 = os.getenv("ARTIFACTS_FOLDER_MPV2", "/builds/xsoar/content/artifacts/marketplacev2")
ARTIFACTS_FOLDER = os.getenv("ARTIFACTS_FOLDER")
ARTIFACTS_FOLDER_SERVER_TYPE = os.getenv("ARTIFACTS_FOLDER_SERVER_TYPE")
ENV_RESULTS_PATH = os.getenv("ENV_RESULTS_PATH", f"{ARTIFACTS_FOLDER_SERVER_TYPE}/env_results.json")
SET_SERVER_KEYS = True
SERVER_HOST_PLACEHOLDER = "%%SERVER_HOST%%"


# -------------------------------------- Helper methods ----------------------------------------------
def get_custom_user_agent(build_number):
    return f"content-build/dev (Build:{build_number})"


def filepath_to_integration_name(integration_file_path):
    """Load an integration file and return the integration name.

    Args:
        integration_file_path (str | Path): The path to an integration yml file.

    Returns:
        (str): The name of the integration.
    """
    integration_yaml = get_yaml(integration_file_path)
    integration_name = integration_yaml.get("name")
    return integration_name


def get_integration_names_from_files(integration_files_list: list[Path]):
    integration_names_list = [filepath_to_integration_name(path) for path in integration_files_list]
    return [name for name in integration_names_list if name]  # remove empty values


def packs_names_to_integrations_names(turned_non_hidden_packs_names: set[str]) -> list[str]:
    """
    Convert packs names to the integrations names contained in it.
    Args:
        turned_non_hidden_packs_names (Set[str]): The turned non-hidden pack names (e.g. "AbnormalSecurity")
    Returns:
        List[str]: The turned non-hidden integrations names list.
    """
    hidden_integrations = []
    hidden_integrations_paths = [f"Packs/{pack_name}/Integrations" for pack_name in turned_non_hidden_packs_names]
    # extract integration names within the turned non-hidden packs.
    for hidden_integrations_path in hidden_integrations_paths:
        if os.path.exists(hidden_integrations_path):
            pack_integrations_paths = listdir_fullpath(hidden_integrations_path)
            for integration_path in pack_integrations_paths:
                hidden_integrations.append(integration_path.split("/")[-1])
    hidden_integrations_names = [integration for integration in hidden_integrations if not str(integration).startswith(".")]
    return hidden_integrations_names


def check_test_version_compatible_with_server(test, server_version):
    """
    Checks if a given test is compatible wis the given server version.
    Arguments:
        test: (dict)
            Test playbook object from content conf.json. May contain the following fields: "playbookID",
            "integrations", "instance_names", "timeout", "nightly", "fromversion", "toversion.
        server_version: (int)
            The server numerical version.
    Returns:
        (bool) True if test is compatible with server version or False otherwise.
    """
    test_from_version = format_version(test.get("fromversion", "0.0.0"))
    test_to_version = format_version(test.get("toversion", "99.99.99"))
    server_version = format_version(server_version)

    if not Version(test_from_version) <= Version(server_version) <= Version(test_to_version):
        playbook_id = test.get("playbookID")
        logging.debug(
            f"Test Playbook: {playbook_id} was ignored in the content installation test due to version mismatch "
            f"(test versions: {test_from_version}-{test_to_version}, server version: {server_version})"
        )
        return False
    return True


def filter_tests_with_incompatible_version(tests, server_version):
    """
    Filter all tests with incompatible version to the given server.
    Arguments:
        tests: (list)
            List of test objects.
        server_version: (int)
            The server numerical version.
    Returns:
        (lst): List of filtered tests (compatible version)
    """

    filtered_tests = [test for test in tests if check_test_version_compatible_with_server(test, server_version)]
    logging.debug(f"Filtered tests (compatible version): {filtered_tests}")
    return filtered_tests


def change_placeholders_to_values(placeholders_map, config_item):
    """Replaces placeholders in the object to their real values

    Args:
        placeholders_map: (dict)
             Dict that holds the real values to be replaced for each placeholder.
        config_item: (json object)
            Integration configuration object.

    Returns:
        dict. json object with the real configuration.
    """
    item_as_string = json.dumps(config_item)
    for key, value in placeholders_map.items():
        item_as_string = item_as_string.replace(key, str(value))
    return json.loads(item_as_string)


def test_pack_metadata():
    now = datetime.now().isoformat().split(".")[0]
    now = f"{now}Z"
    metadata = {
        "name": "test pack",
        "id": str(uuid.uuid4()),
        "description": "test pack (all test playbooks and scripts).",
        "created": now,
        "updated": now,
        "legacy": True,
        "support": "Cortex XSOAR",
        "supportDetails": {},
        "author": "Cortex XSOAR",
        "authorImage": "",
        "certification": "certified",
        "price": 0,
        "serverMinVersion": "6.0.0",
        "serverLicense": "",
        "currentVersion": "1.0.0",
        "general": [],
        "tags": [],
        "categories": ["Forensics & Malware Analysis"],
        "contentItems": {},
        "integrations": [],
        "useCases": [],
        "keywords": [],
        "dependencies": {},
    }
    return json.dumps(metadata, indent=4)


def get_test_playbooks_in_dir(path):
    playbooks = filter(lambda x: x.is_file(), os.scandir(path))
    for playbook in playbooks:
        yield playbook.path, playbook


def test_files(content_path, packs_to_install: list | None = None):
    packs_root = f"{content_path}/Packs"
    packs_to_install = packs_to_install or []

    # if is given a list of packs to install then collect the test playbook only for those packs (in commit/push build)
    if packs_to_install:
        packs = filter(lambda x: x.is_dir() and x.name in packs_to_install, os.scandir(packs_root))
    else:
        # else collect the test playbooks for all content packs (in nightly)
        packs = filter(lambda x: x.is_dir(), os.scandir(packs_root))

    for pack_dir in packs:
        if pack_dir in SKIPPED_PACKS:
            continue
        playbooks_root = f"{pack_dir.path}/TestPlaybooks"
        if os.path.isdir(playbooks_root):
            for playbook_path, playbook in get_test_playbooks_in_dir(playbooks_root):
                yield playbook_path, playbook
            if os.path.isdir(f"{playbooks_root}/NonCircleTests"):
                for playbook_path, playbook in get_test_playbooks_in_dir(f"{playbooks_root}/NonCircleTests"):
                    yield playbook_path, playbook


def get_env_conf():
    if Build.run_environment == Running.CI_RUN:
        return get_json_file(Build.env_results_path)

    if Build.run_environment == Running.WITH_LOCAL_SERVER:
        # START CHANGE ON LOCAL RUN #
        return [
            {
                "InstanceDNS": "http://localhost:8080",
                "Role": "Server Master",  # e.g. 'Server Master'
            }
        ]
    if Build.run_environment == Running.WITH_OTHER_SERVER:
        return [
            {
                "InstanceDNS": "DNS NAME",  # without http prefix
                "Role": "DEMISTO EVN",  # e.g. 'Server Master'
            }
        ]

    #  END CHANGE ON LOCAL RUN  #
    return None


def get_servers(env_results, instance_role):
    """
    Arguments:
        env_results: (dict)
            env_results.json in server
        instance_role: (str)
            The amazon machine image environment whose IP we should connect to.

    Returns:
        (lst): The server url list to connect to
    """

    return [env.get("InstanceDNS") for env in env_results if instance_role in env.get("Role")]


# ------------------------------------------------ Server Classes -------------------------------------------


class Running(IntEnum):
    CI_RUN = 0
    WITH_OTHER_SERVER = 1
    WITH_LOCAL_SERVER = 2


class Server:
    def __init__(self):
        self.internal_ip = None
        self.user_name = None
        self.password = None
        self.name = ""
        self.build_number = "unknown"
        self.pack_ids_to_install = []
        self.tests_to_run = []
        self.build = None
        self.__client = None
        self.test_pack_path = None
        self._server_numeric_version = None
        self.secret_conf = None
        self.options = None

    @abstractmethod
    def install_packs(self, pack_ids: list | None = None, install_packs_in_batches=False, production_bucket: bool = True) -> bool:
        pass

    @property
    def client(self):
        if self.__client is None:
            self.__client = self.reconnect_client()

        return self.__client

    @abstractmethod
    def reconnect_client(self):
        pass

    @property
    @abstractmethod
    def server_numeric_version(self) -> str:
        return self._server_numeric_version

    # ------------------------- Calculate Pre packs to install ----------------------------------

    def get_non_added_packs_ids(self):
        """
        In this step we want to get only updated packs (not new packs).
        :return: all non added packs i.e. unchanged packs (dependencies) and modified packs
        """
        compare_against = "master~1" if self.build.branch_name == "master" else "origin/master"
        added_files = run_command(
            f"git diff --name-only --diff-filter=A "
            f"{compare_against}..refs/heads/{self.build.branch_name} -- Packs/*/pack_metadata.json"
        )
        if os.getenv("CONTRIB_BRANCH"):
            added_contrib_files = run_command('git status -uall --porcelain -- Packs/*/pack_metadata.json | grep "?? "').replace(
                "?? ", ""
            )
            added_files = added_files if not added_contrib_files else "\n".join([added_files, added_contrib_files])

        added_files = filter(lambda x: x, added_files.split("\n"))
        added_pack_ids = (x.split("/")[1] for x in added_files)
        # pack_ids_to_install contains new packs and modified. added_pack_ids contains new packs only.
        return set(self.pack_ids_to_install) - set(added_pack_ids)

    def run_git_diff(self, pack_name: str) -> str:
        """
        Run git diff command with the specific pack id.
        Args:
            pack_name (str): The pack name.
        Returns:
            (str): The git diff output.
        """
        compare_against = f"origin/master{'' if self.build.branch_name != 'master' else '~1'}"
        return run_command(f"git diff {compare_against}..{self.build.branch_name} -- Packs/{pack_name}/pack_metadata.json")

    def check_hidden_field_changed(self, pack_name: str) -> bool:
        """
        Check if pack turned from hidden to non-hidden.
        Args:
            pack_name (str): The pack name.
        Returns:
            (bool): True if the pack transformed to non-hidden.
        """
        diff = self.run_git_diff(pack_name)
        return any('"hidden": false' in diff_line and diff_line.split()[0].startswith("+") for diff_line in diff.splitlines())

    def get_turned_non_hidden_packs(self, modified_packs_names: set[str]) -> set[str]:
        """
        Return a set of packs which turned from hidden to non-hidden.
        Args:
            modified_packs_names (Set[str]): The set of packs to install.
        Returns:
            (Set[str]): The set of packs names which are turned non-hidden.
        """
        hidden_packs = set()
        for pack_name in modified_packs_names:
            # check if the pack turned from hidden to non-hidden.
            if self.check_hidden_field_changed(pack_name):
                hidden_packs.add(pack_name)
        return hidden_packs

    def check_if_new_to_marketplace(self, diff: str) -> bool:
        """
        Args:
            diff: the git diff for pack_metadata file, between master and branch
        Returns:
            (bool): whether new (current) marketplace was added to the pack_metadata or not
        """
        spaced_diff = " ".join(diff.split())
        return (f'+ "{self.build.marketplace_name}"' in spaced_diff) and f'- "{self.build.marketplace_name}"' not in spaced_diff

    def filter_new_to_marketplace_packs(self, modified_pack_names: set[str]) -> set[str]:
        """
        Return a set of packs that is new to the marketplace.
        Args:
            modified_pack_names (Set[str]): The set of packs to install.
        Returns:
            (Set[str]): The set of the pack names that should not be installed.
        """
        first_added_to_marketplace = set()
        for pack_name in modified_pack_names:
            diff = self.run_git_diff(pack_name)
            if self.check_if_new_to_marketplace(diff):
                first_added_to_marketplace.add(pack_name)
        return first_added_to_marketplace

    def get_packs_to_install(self) -> tuple[set[str], set[str]]:
        """
        Return a set of packs to install only in the pre-update, and set to install in post-update.

        Returns:
            (Set[str]): The set of the pack names that should not be installed.
            (Set[str]): The set of the pack names that should be installed only in post update. (non-hidden packs or packs
                                                    that new to current marketplace)
        """
        modified_packs_names = self.get_non_added_packs_ids()

        non_hidden_packs = self.get_turned_non_hidden_packs(modified_packs_names)

        packs_with_higher_min_version = get_packs_with_higher_min_version(
            set(self.pack_ids_to_install), self.server_numeric_version
        )

        # packs to install used in post update
        self.pack_ids_to_install = list(set(self.pack_ids_to_install) - packs_with_higher_min_version)

        first_added_to_marketplace = self.filter_new_to_marketplace_packs(
            modified_packs_names - non_hidden_packs - packs_with_higher_min_version
        )

        packs_not_to_install_in_pre_update = set().union(
            *[packs_with_higher_min_version, non_hidden_packs, first_added_to_marketplace]
        )
        packs_to_install_in_pre_update = modified_packs_names - packs_not_to_install_in_pre_update
        return packs_to_install_in_pre_update, non_hidden_packs

    def get_new_and_modified_integration_files(self):
        """Return 2 lists - list of new integrations and list of modified integrations since the first commit of the branch.

        Returns:
            (tuple): Returns a tuple of two lists, the file paths of the new integrations and modified integrations.
        """

        # get changed yaml files (filter only added and modified files)
        git_util = GitUtil()
        if str2bool(os.getenv("IS_NIGHTLY")) or os.getenv("IFRA_ENV_TYPE") == "Bucket-Upload":
            prev_ver = get_last_commit_from_index(MarketplaceVersions(self.build.marketplace_name))
        else:
            prev_ver = "origin/master"

        logging.info(f"get_new_and_modified_integration_files, {prev_ver=}")
        modified_files = git_util.modified_files(prev_ver=prev_ver)
        added_files = git_util.added_files(prev_ver=prev_ver)

        logging.info(f"{modified_files=},\n{added_files=}")
        new_integration_files = [
            file_path
            for file_path in added_files
            if find_type(str(file_path)) in [FileType.INTEGRATION, FileType.BETA_INTEGRATION]
        ]

        modified_integration_files = [
            file_path
            for file_path in modified_files
            if find_type(str(file_path)) in [FileType.INTEGRATION, FileType.BETA_INTEGRATION]
        ]
        return new_integration_files, modified_integration_files

    @staticmethod
    def update_integration_lists(
        new_integrations_names: list[str], packs_not_to_install: set[str] | None, modified_integrations_names: list[str]
    ) -> tuple[list[str], list[str]]:
        """
        Add the turned non-hidden integrations names to the new integrations names list and
         remove it from modified integrations names.
        Args:
            new_integrations_names (List[str]): The new integration name (e.g. "AbnormalSecurity").
            packs_not_to_install (Set[str]): The turned non-hidden packs names.
            modified_integrations_names (List[str]): The modified integration name (e.g. "AbnormalSecurity").
        Returns:
            Tuple[List[str], List[str]]: The updated lists after filtering the turned non-hidden integrations.
        """
        if not packs_not_to_install:
            return new_integrations_names, modified_integrations_names

        hidden_integrations_names = packs_names_to_integrations_names(packs_not_to_install)
        # update the new integration and the modified integration with the non-hidden integrations.
        for hidden_integration_name in hidden_integrations_names:
            if hidden_integration_name in modified_integrations_names:
                modified_integrations_names.remove(hidden_integration_name)
                new_integrations_names.append(hidden_integration_name)
        return list(set(new_integrations_names)), modified_integrations_names

    def get_changed_integrations(self, packs_not_to_install: set[str] | None = None) -> tuple[list[str], list[str]]:
        """
        Return 2 lists - list of new integrations names and list of modified integrations names since the commit of the git_sha1.
        The modified list is exclude the packs_not_to_install and the new list is including it
        in order to ignore the turned non-hidden tests in the pre-update stage.
        Args:
            self: the server object.
            packs_not_to_install (Set[str]): The set of packs names which are turned to non-hidden.
        Returns:
            Tuple[List[str], List[str]]: The list of new integrations names and list of modified integrations names.
        """
        new_integrations_files, modified_integrations_files = self.get_new_and_modified_integration_files()
        new_integrations_names, modified_integrations_names = [], []

        if new_integrations_files:
            new_integrations_names = get_integration_names_from_files(new_integrations_files)
            logging.info(f"New Integrations Since Last Release:\n{new_integrations_names}")

        if modified_integrations_files:
            modified_integrations_names = get_integration_names_from_files(modified_integrations_files)
            logging.info(f"Updated Integrations Since Last Release:\n{modified_integrations_names}")
        return self.update_integration_lists(new_integrations_names, packs_not_to_install, modified_integrations_names)

    # ------------------------------ Configure and test integrations ----------------------------------------------

    def get_tests(self) -> list[dict]:
        """
        Selects the tests from that should be run in this execution and filters those that cannot run in this server version
        Args:
            self: Server object

        Returns:
            Test configurations from conf.json that should be run in this execution
        """
        server_numeric_version: str = self.server_numeric_version
        tests: dict = self.build.tests
        tests_for_iteration: list[dict]
        if Build.run_environment == Running.CI_RUN:
            tests_for_iteration = list(filter(lambda test: test.get("playbookID", "") in self.tests_to_run, tests))
            tests_for_iteration = filter_tests_with_incompatible_version(tests_for_iteration, server_numeric_version)
            return tests_for_iteration

        # START CHANGE ON LOCAL RUN #
        return [
            {"playbookID": "Docker Hardening Test", "fromversion": "5.0.0"},
            {
                "integrations": "SplunkPy",
                "playbookID": "SplunkPy-Test-V2",
                "memory_threshold": 500,
                "instance_names": "use_default_handler",
            },
        ]
        #  END CHANGE ON LOCAL RUN  #

    @staticmethod
    def get_integrations_for_test(test, skipped_integrations_conf):
        """Return a list of integration objects that are necessary for a test (excluding integrations on the skip list).

        Args:
            test (dict): Test dictionary from the conf.json file containing the playbookID, integrations and
                instance names.
            skipped_integrations_conf (dict): Skipped integrations dictionary with integration names as keys and
                the skip reason as values.

        Returns:
            (list): List of integration objects to configure.
        """
        integrations_conf = test.get("integrations", [])

        if not isinstance(integrations_conf, list):
            integrations_conf = [integrations_conf]

        integrations = [
            {"name": integration, "params": {}}
            for integration in integrations_conf
            if integration not in skipped_integrations_conf
        ]
        return integrations

    def group_integrations(self, integrations, new_integrations_names, modified_integrations_names):
        """
        Filter integrations into their respective lists - new, modified or unchanged. if it's on the skip list, then
        skip if random tests were chosen then we may be configuring integrations that are neither new nor modified.

        Args:
            integrations (list): The integrations to categorize.
            new_integrations_names (list): The names of new integrations.
            modified_integrations_names (list): The names of modified integrations.

        Returns:
            (tuple): Lists of integrations objects as well as an Integration-to-Status dictionary useful for logs.
        """
        new_integrations = []
        modified_integrations = []
        unchanged_integrations = []
        integration_to_status = {}
        for integration in integrations:
            integration_name = integration.get("name", "")
            if integration_name in self.build.skipped_integrations_conf:
                continue

            if integration_name in new_integrations_names:
                new_integrations.append(integration)
            elif integration_name in modified_integrations_names:
                modified_integrations.append(integration)
                integration_to_status[integration_name] = "Modified Integration"
            else:
                unchanged_integrations.append(integration)
                integration_to_status[integration_name] = "Unchanged Integration"
        return new_integrations, modified_integrations, unchanged_integrations, integration_to_status

    @abstractmethod
    def add_core_pack_params(self, integration_params):
        """
        For cloud build we need to add core rest api params differently
        """

    def set_integration_params(self, integrations, secret_params, instance_names, placeholders_map, logging_module=logging):
        """
        For each integration object, fill in the parameter values needed to configure an instance from
        the secret_params taken from our secret configuration file. Because there may be a number of
        configurations for a single integration (if there are values provided in our secret conf for
        multiple different instances of the same integration) then selects the parameter values for the
        configuration of the instance whose instance is in 'instance_names' (will take the last one listed
        in 'secret_params'). Note that this function does not explicitly return the modified 'integrations'
        object but rather it modifies the 'integrations' object since it is passed by reference and not by
        value, so the 'integrations' object that was passed to this function will have been changed once
        this function has completed execution and gone out of scope.

        Arguments:
            integrations: (list of dicts)
                List of integration objects whose 'params' attribute will be populated in this function.
            secret_params: (list of dicts)
                List of secret configuration values for all of our integrations (as well as specific
                instances of said integrations).
            instance_names: (list)
                The names of particular instances of an integration to use the secret_params of as the
                configuration values.
            placeholders_map: (dict)
                 Dict that holds the real values to be replaced for each placeholder.
            logging_module (Union[ParallelLoggingManager,logging]): The logging module to use

        Returns:
            (bool): True if integrations params were filled with secret configuration values, otherwise false
        """
        for integration in integrations:
            integration_params = [
                change_placeholders_to_values(placeholders_map, item)
                for item in secret_params
                if item["name"] == integration["name"]
            ]
            if integration["name"] == "Core REST API":
                # Relevant only for cloud
                self.add_core_pack_params(integration_params)

            if integration_params:
                matched_integration_params = integration_params[0]
                # if there are more than one integration params, it means that there are configuration
                # values in our secret conf for multiple instances of the given integration, and now we
                # need to match the configuration values to the proper instance as specified in the
                # 'instance_names' list argument
                if len(integration_params) != 1:
                    found_matching_instance = False
                    for item in integration_params:
                        if item.get("instance_name", "Not Found") in instance_names:
                            matched_integration_params = item
                            found_matching_instance = True

                    if not found_matching_instance:
                        optional_instance_names = [
                            optional_integration.get("instance_name", "None") for optional_integration in integration_params
                        ]
                        failed_match_instance_msg = (
                            "There are {} instances of {}, please select one of them by using"
                            " the instance_name argument in conf.json. The options are:\n{}"
                        )
                        logging_module.error(
                            failed_match_instance_msg.format(
                                len(integration_params), integration["name"], "\n".join(optional_instance_names)
                            )
                        )
                        return False

                integration["params"] = matched_integration_params.get("params", {})
                integration["byoi"] = matched_integration_params.get("byoi", True)
                integration["instance_name"] = matched_integration_params.get("instance_name", integration["name"])
                integration["validate_test"] = matched_integration_params.get("validate_test", True)

        return True

    def __set_server_keys(self, integration_params, integration_name):
        """Adds server configuration keys using the demisto_client.

        Args:
            integration_params (dict): The values to use for an integration's parameters to configure an instance.
            integration_name (str): The name of the integration which the server configurations keys are related to.

        """
        if "server_keys" not in integration_params or not SET_SERVER_KEYS:
            return

        logging.info(f"Setting server keys for integration: {integration_name}")

        data: dict = {"data": {}, "version": -1}

        for key, value in integration_params.get("server_keys").items():
            data["data"][key] = value

        update_server_configuration(client=self.client, server_configuration=data, error_msg="Failed to set server keys")

    @staticmethod
    def set_module_params(param_conf, integration_params):
        """Configure a parameter object for use in a module instance.

        Each integration parameter is actually an object with many fields that together describe it. E.g. a given
        parameter will have all of the following fields - "name", "display", "value", "hasvalue", "defaultValue",
        etc. This function fills the "value" field for a parameter configuration object and returns it for use in
        a module instance.

        Args:
            param_conf (dict): The parameter configuration object.
            integration_params (dict): The values to use for an integration's parameters to configure an instance.

        Returns:
            (dict): The configured parameter object
        """
        if param_conf["display"] in integration_params or param_conf["name"] in integration_params:
            # param defined in conf
            key = param_conf["display"] if param_conf["display"] in integration_params else param_conf["name"]
            if key == "credentials" or key == "creds_apikey":
                credentials = integration_params[key]
                param_value = {
                    "credential": "",
                    "identifier": credentials.get("identifier", ""),
                    "password": credentials["password"],
                    "passwordChanged": False,
                }
            else:
                param_value = integration_params[key]

            param_conf["value"] = param_value
            param_conf["hasvalue"] = True
        elif param_conf["defaultValue"]:
            # if the parameter doesn't have a value provided in the integration's configuration values
            # but does have a default value then assign it to the parameter for the module instance
            param_conf["value"] = param_conf["defaultValue"]
        return param_conf

    def set_integration_instance_parameters(
        self, integration_configuration, integration_params, integration_instance_name, is_byoi, integration_name
    ):
        """Set integration module values for integration instance creation

        The integration_configuration and integration_params should match, in that
        they are for the same integration

        Arguments:
            integration_configuration: (dict)
                dictionary of the integration configuration parameters/keys that need
                filling to instantiate an instance of a given integration
            integration_params: (dict)
                values for a given integration taken from the configuration file in
                which the secret values are stored to configure instances of various
                integrations
            integration_instance_name: (str)
                The name of the integration instance being configured if there is one
                provided in the conf.json
            is_byoi: (bool)
                If the integration is byoi or not
            integration_name: (str)
                The name of the integration being configured


        Returns:
            (dict): The configured module instance to send to the Demisto server for
            instantiation.
        """
        module_configuration = integration_configuration.get("configuration", {})
        if not module_configuration:
            module_configuration = []

        instance_name = integration_params.get("integrationInstanceName") or "{}_test_{}".format(
            (integration_instance_name or integration_name).replace(" ", "_"), str(uuid.uuid4())
        )

        # define module instance
        module_instance = {
            "brand": integration_configuration["name"],
            "category": integration_configuration["category"],
            "configuration": integration_configuration,
            "data": [],
            "enabled": "true",
            "engine": "",
            "id": "",
            "isIntegrationScript": is_byoi,
            "name": instance_name,
            "passwordProtected": False,
            "version": 0,
        }

        # set server keys
        self.__set_server_keys(integration_params, integration_configuration["name"])

        # set module params
        for param_conf in module_configuration:
            configured_param = self.set_module_params(param_conf, integration_params)
            module_instance["data"].append(configured_param)

        return module_instance

    def configure_integration_instance(self, integration, placeholders_map):
        """
        Configure an instance for an integration

        Arguments:
            integration: (dict)
                Integration object whose params key-values are set
            placeholders_map: (dict)
                 Dict that holds the real values to be replaced for each placeholder.

        Returns:
            (dict): Configured integration instance
        """
        integration_name = integration.get("name")
        logging.info(f'Configuring instance for integration "{integration_name}"')
        integration_instance_name = integration.get("instance_name", "")
        integration_params = change_placeholders_to_values(placeholders_map, integration.get("params"))
        is_byoi = integration.get("byoi", True)
        validate_test = integration.get("validate_test", True)

        integration_configuration = get_integration_config(self.client, integration_name)
        if not integration_configuration:
            return None

        # In the integration configuration in content-test-conf conf.json, the test_validate flag was set to false
        if not validate_test:
            logging.debug(f"Skipping configuration for integration: {integration_name} (it has test_validate set to false)")
            return None
        module_instance = self.set_integration_instance_parameters(
            integration_configuration, integration_params, integration_instance_name, is_byoi, integration_name
        )
        return module_instance

    def configure_modified_and_new_integrations(
        self, modified_integrations_to_configure: list, new_integrations_to_configure: list
    ) -> tuple:
        """
        Configures old and new integrations in the server configured in the demisto_client.
        Args:
            self: The server object.
            modified_integrations_to_configure: Integrations to configure that already exist.
            new_integrations_to_configure: Integrations to configure that were created in this build.

        Returns:
            A tuple with two lists:
            1. List of configured instances of modified integrations.
            2. List of configured instances of new integrations.
        """

        def configure_instances(integrations: list[dict[str, Any]]) -> list[dict[str, Any]]:
            placeholders_map = {SERVER_HOST_PLACEHOLDER: self}
            configured_instances = []
            for integration in integrations:
                instance = self.configure_integration_instance(integration, placeholders_map)
                if instance:
                    configured_instances.append(instance)
            return configured_instances

        # Configure modified and new integrations
        modified_modules_instances = configure_instances(modified_integrations_to_configure)
        new_modules_instances = configure_instances(new_integrations_to_configure)

        return modified_modules_instances, new_modules_instances

    def configure_server_instances(self, tests_for_iteration, all_new_integrations, modified_integrations):
        modified_module_instances = []
        new_module_instances = []
        configured_integrations_set = set()  # Track all configured integrations
        for test in tests_for_iteration:
            integrations = self.get_integrations_for_test(test, self.build.skipped_integrations_conf)

            playbook_id = test.get("playbookID")

            new_integrations, modified_integrations, unchanged_integrations, integration_to_status = self.group_integrations(
                integrations, all_new_integrations, modified_integrations
            )

            integration_to_status_string = "\n\t\t\t\t\t\t".join(
                [f'"{key}" - {val}' for key, val in integration_to_status.items()]
            )
            if integration_to_status_string:
                logging.info(f'All Integrations for test "{playbook_id}":\n\t\t\t\t\t\t{integration_to_status_string}')
            else:
                logging.info(f'No Integrations for test "{playbook_id}"')
            instance_names_conf = test.get("instance_names", [])
            if not isinstance(instance_names_conf, list):
                instance_names_conf = [instance_names_conf]

            integrations_to_configure = modified_integrations[:]
            integrations_to_configure.extend(unchanged_integrations)
            placeholders_map = {SERVER_HOST_PLACEHOLDER: self}
            new_ints_params_set = self.set_integration_params(
                new_integrations, self.secret_conf["integrations"], instance_names_conf, placeholders_map
            )
            ints_to_configure_params_set = self.set_integration_params(
                integrations_to_configure, self.secret_conf["integrations"], instance_names_conf, placeholders_map
            )
            if not new_ints_params_set:
                logging.error(f"failed setting parameters for integrations: {new_integrations}")
            if not ints_to_configure_params_set:
                logging.error(f"failed setting parameters for integrations: {integrations_to_configure}")
            if not (new_ints_params_set and ints_to_configure_params_set):
                continue

            modified_module_instances_for_test, new_module_instances_for_test = self.configure_modified_and_new_integrations(
                integrations_to_configure, new_integrations
            )

            # Add to the set of configured integrations
            configured_integrations_set.update(
                integration.get("name") for integration in integrations_to_configure + new_integrations
            )

            modified_module_instances.extend(modified_module_instances_for_test)
            new_module_instances.extend(new_module_instances_for_test)

        # After looping through tests, handle instance_test_only instances
        unconfigured_integrations = [
            integration
            for integration in self.secret_conf["integrations"]
            if integration.get("name") not in configured_integrations_set
        ]

        logging.info(f"Configured integrations: {configured_integrations_set}")

        # Configure the unconfigured integrations directly
        instance_test_only_instances = []
        unconfigured_integration_names = [integration["name"] for integration in unconfigured_integrations]
        logging.info(f'Found unconfigured integration instances are: "{", ".join(unconfigured_integration_names)}"')
        if unconfigured_integrations:
            placeholders_map = {SERVER_HOST_PLACEHOLDER: self}
            instance_test_only_instances = []
            for integration in unconfigured_integrations:
                configured_instance = self.configure_integration_instance(integration, placeholders_map)
                if configured_instance:
                    instance_test_only_instances.append(configured_instance)

        return modified_module_instances, new_module_instances, instance_test_only_instances

    @abstractmethod
    def configure_and_test_integrations_pre_update(self, new_integrations, modified_integrations) -> tuple:
        pass

    def instance_testing(
        self, all_module_instances: list, pre_update: bool, use_mock: bool = True, first_call: bool = True
    ) -> tuple[set, set]:
        """
        Runs 'test-module' command for the instances detailed in `all_module_instances`
        Args:
            self: An object containing the current server info.
            all_module_instances: The integration instances that should be tested
            pre_update: Whether this instance testing is before or after the content update on the server.
            use_mock: Whether to use mock while testing mockable integrations.
            first_call: indicates if it's the first time the function is called from the same place

        Returns:
            A set of the successful tests containing the instance name and the integration name
            A set of the failed tests containing the instance name and the integration name
        """
        update_status = "Pre" if pre_update else "Post"
        failed_tests = set()
        successful_tests = set()
        # Test all module instances (of modified + unchanged integrations) pre-updating content
        if all_module_instances:
            # only print start message if there are instances to configure
            logging.info(f'Start of Instance Testing ("Test" button) ({update_status}-update)')
        else:
            logging.info(f"No integrations to configure for the chosen tests. ({update_status}-update)")
        failed_instances = []
        for instance in all_module_instances:
            integration_of_instance = instance.get("brand", "")
            instance_name = instance.get("name", "")
            logging.info(f"Start of Instance Testing {instance_name=}")

            # If there is a failure, test_integration_instance will print it
            testing_client = self.reconnect_client()
            success, _ = test_integration_instance(testing_client, instance)
            if not success:
                failed_tests.add((instance_name, integration_of_instance))
                failed_instances.append(instance)
            else:
                successful_tests.add((instance_name, integration_of_instance))

        # in case some tests failed post update, wait 15 secs, runs the tests again
        if failed_instances and not pre_update and first_call:
            logging.info("Sleep - some post-update tests failed, sleeping for 15 seconds, then running the failed tests again")
            sleep(15)
            _, failed_tests = self.instance_testing(failed_instances, pre_update=False, first_call=False)

        return successful_tests, failed_tests

    def set_marketplace_url(self, marketplace_name, artifacts_folder, marketplace_buckets) -> bool:
        raise NotImplementedError

    def update_content_on_servers(self) -> bool:
        """
        Changes marketplace bucket to new one that was created for current branch.
        Updates content on the build's server according to the server version.
        Args:
            self: Server object

        Returns:
            A boolean that indicates whether the content installation was successful.
            If the server version is lower than 5.9.9 will return the 'installed_content_packs_successfully' parameter as is
            If the server version is higher or equal to 6.0 - will return True if the packs installation was successful
            both before that update and after the update.
        """
        installed_content_packs_successfully = self.set_marketplace_url(
            self.build.marketplace_tag_name, self.build.artifacts_folder, self.build.marketplace_buckets
        )
        if installed_content_packs_successfully:
            installed_content_packs_successfully &= self.install_packs(production_bucket=False)
        return installed_content_packs_successfully

    @abstractmethod
    def test_integrations_post_update(self, new_module_instances: list, modified_module_instances: list) -> tuple:
        pass

    def create_and_upload_test_pack(self):
        """Creates and uploads a test pack that contains the test playbook of the specified packs to install list."""
        self.test_pack_zip()

        upload_zipped_packs(
            client=self.client,
            host=self.name or self.internal_ip,
            pack_path=f"{Build.test_pack_target}/{self.test_pack_path}.zip",
        )

    def test_pack_zip(self):
        """
        Iterates over all TestPlaybooks folders and adds all files from there to test_pack_path.zip file.
        """
        packs = self.pack_ids_to_install or []
        with zipfile.ZipFile(f"{self.build.test_pack_target}/{self.test_pack_path}.zip", "w", zipfile.ZIP_DEFLATED) as zip_file:
            zip_file.writestr(f"{self.test_pack_path}/metadata.json", test_pack_metadata())
            for test_path, test in test_files(Build.content_path, packs):
                if not test_path.endswith(".yml"):
                    continue
                test = test.name
                with open(test_path) as test_file:
                    if not (test.startswith(("playbook-", "script-"))):
                        test_type = find_type(_dict=yaml.safe_load(test_file), file_type="yml", path=test_path).value
                        test_file.seek(0)
                        # we need to convert to the regular filetype if we get a test type, because that what the server expects
                        if test_type == FileType.TEST_PLAYBOOK.value:
                            test_type = FileType.PLAYBOOK.value
                        if test_type == FileType.TEST_SCRIPT.value:
                            test_type = FileType.SCRIPT.value
                        test_target = f"{self.test_pack_path}/TestPlaybooks/{test_type}-{test}"
                    else:
                        test_target = f"{self.test_pack_path}/TestPlaybooks/{test}"
                    zip_file.writestr(test_target, test_file.read())

    # ---------------------------------------- Success report flow ----------------------------------------------

    def report_tests_status(
        self, preupdate_fails, postupdate_fails, preupdate_success, postupdate_success, new_integrations_names
    ):
        """Prints errors and/or warnings if there are any and returns whether testing was successful or not.

        Args:
            preupdate_fails (set): List of tuples of integrations that failed the "Test" button prior to content
                being updated on the demisto instance where each tuple consists of the integration name and the
                name of the instance that was configured for that integration which failed.
            postupdate_fails (set): List of tuples of integrations that failed the "Test" button after content was
                updated on the demisto instance where each tuple consists of the integration name and the name
                of the instance that was configured for that integration which failed.
            preupdate_success (set): List of tuples of integrations that succeeded the "Test" button prior to content
                being updated on the demisto instance where each tuple consists of the integration name and the
                name of the instance that was configured for that integration which failed.
            postupdate_success (set): List of tuples of integrations that succeeded the "Test" button after content was
                updated on the demisto instance where each tuple consists of the integration name and the name
                of the instance that was configured for that integration which failed.
            new_integrations_names (list): List of the names of integrations that are new since the last official
                content release and that will only be present on the demisto instance after the content update is
                performed.

        Returns:
            (bool): False if there were integration instances that succeeded prior to the content update and then
                failed after content was updated, otherwise True.
        """
        testing_status = True

        # a "Test" can be either successful both before and after content update(succeeded_pre_and_post variable),
        # fail on one of them(mismatched_statuses variable), or on both(failed_pre_and_post variable)
        succeeded_pre_and_post = preupdate_success.intersection(postupdate_success)
        if succeeded_pre_and_post:
            succeeded_pre_and_post_string = "\n".join(
                [
                    f'Integration: "{integration_of_instance}", Instance: "{instance_name}"'
                    for instance_name, integration_of_instance in succeeded_pre_and_post
                ]
            )
            logging.success(
                'Integration instances that had ("Test" Button) succeeded both before and after the content update:\n'
                f"{succeeded_pre_and_post_string}"
            )

        failed_pre_and_post = preupdate_fails.intersection(postupdate_fails)
        mismatched_statuses = postupdate_fails - preupdate_fails
        failed_only_after_update = []
        failed_but_is_new = []
        for instance_name, integration_of_instance in mismatched_statuses:
            if integration_of_instance in new_integrations_names:
                failed_but_is_new.append((instance_name, integration_of_instance))
            else:
                failed_only_after_update.append((instance_name, integration_of_instance))

        # warnings but won't fail the build step
        if failed_but_is_new:
            failed_but_is_new_string = "\n".join(
                [
                    f'Integration: "{integration_of_instance}", Instance: "{instance_name}"'
                    for instance_name, integration_of_instance in failed_but_is_new
                ]
            )
            logging.warning(f'New Integrations ("Test" Button) Failures:\n{failed_but_is_new_string}')
        if failed_pre_and_post:
            failed_pre_and_post_string = "\n".join(
                [
                    f'Integration: "{integration_of_instance}", Instance: "{instance_name}"'
                    for instance_name, integration_of_instance in failed_pre_and_post
                ]
            )
            logging.warning(
                f'Integration instances that had ("Test" Button) failures '
                f"both before and after the content update"
                f'(No need to handle ERROR messages for these "test-module" failures):'
                f"\n{pformat(failed_pre_and_post_string)}."
            )
        # fail the step if there are instances that only failed after content was updated
        if failed_only_after_update:
            failed_only_after_update_string = "\n".join(
                [
                    f'Integration: "{integration_of_instance}", Instance: "{instance_name}"'
                    for instance_name, integration_of_instance in failed_only_after_update
                ]
            )
            logging.critical(
                'Integration instances that had ("Test" Button) failures only after content was updated:\n'
                f"{pformat(failed_only_after_update_string)}.\n"
                f"This indicates that your updates introduced breaking changes to the integration."
            )
        else:
            # creating this file to indicates that this instance passed post update tests,
            # uses this file in XSOAR destroy instances
            if self.build and self.build.__class__ == XSOARBuild:
                with open(f"{ARTIFACTS_FOLDER}/is_post_update_passed_{self.build.ami_env.replace(' ', '')}.txt", "a"):
                    pass

        return testing_status

    # ---------------------------------------- Test flow ----------------------------------------------

    def perform_single_server_test_flow(self):
        """
        Calculate pre and post update packs to install, install them and test them

        """

        logging.info(f"Start performing test flow on server {self.name}")
        packs_to_install_in_pre_update, packs_to_install_in_post_update = self.get_packs_to_install()

        logging.info("Installing packs in pre-update step")
        self.install_packs(pack_ids=packs_to_install_in_pre_update)  # type: ignore[arg-type]

        new_integrations_names, modified_integrations_names = self.get_changed_integrations(packs_to_install_in_post_update)

        pre_update_configuration_results = self.configure_and_test_integrations_pre_update(
            new_integrations_names, modified_integrations_names
        )
        modified_module_instances, new_module_instances, failed_tests_pre, successful_tests_pre = pre_update_configuration_results

        logging.info("Installing packs in post-update step")
        success = self.update_content_on_servers()
        if success:
            successful_tests_post, failed_tests_post = self.test_integrations_post_update(
                new_module_instances, modified_module_instances
            )
            if not str2bool(os.getenv("BUCKET_UPLOAD")):  # Don't need to upload test playbooks in upload flow
                self.create_and_upload_test_pack()

            success &= self.report_tests_status(
                failed_tests_pre, failed_tests_post, successful_tests_pre, successful_tests_post, new_integrations_names
            )

        return success


class XSOARServer(Server):
    def __init__(self, internal_ip, pack_ids_to_install, tests_to_run, build, options, build_number=""):
        super().__init__()
        self.__client = None
        self.internal_ip: str = internal_ip
        self.pack_ids_to_install = pack_ids_to_install
        self.options = options
        self.secret_conf = get_secrets_from_gsm(self.options, options.branch, self.pack_ids_to_install)
        self.user_name = options.user if options.user else self.secret_conf.get("username")
        self.password = options.password if options.password else self.secret_conf.get("userPassword")
        self.pack_ids_to_install = pack_ids_to_install
        self.tests_to_run = tests_to_run
        self.build = build
        self.build_number = build_number
        self.test_pack_path = f"test_pack_{internal_ip}"

    def __str__(self):
        return self.internal_ip

    @property
    def server_numeric_version(self) -> str:
        return get_server_numeric_version(self.client)

    def reconnect_client(self):
        self.__client = demisto_client.configure(
            f"https://{self.internal_ip}", verify_ssl=False, username=self.user_name, password=self.password
        )
        custom_user_agent = get_custom_user_agent(self.build_number)
        logging.debug(f"Setting user-agent on client to '{custom_user_agent}'.")
        self.__client.api_client.user_agent = custom_user_agent
        return self.__client

    def add_server_configuration(self, config_dict, error_msg, restart=False):
        _, status_code, _ = update_server_configuration(self.client, config_dict, error_msg)
        logging.debug(f"Updated server configuration with status_code: {status_code=}")
        if restart:
            try:
                self.exec_command("sudo systemctl restart demisto")
            except subprocess.CalledProcessError:
                logging.critical("Can't restart server.")

    def exec_command(self, command):
        subprocess.check_output(f"ssh {SSH_USER}@{self.internal_ip} {command}".split(), stderr=subprocess.STDOUT)

    def configure_and_test_integrations_pre_update(self, new_integrations, modified_integrations) -> tuple:
        """
        Configures integration instances that exist in the current version and for each integration runs 'test-module'.
        Args:
            self: Server object
            new_integrations: A list containing new integrations names
            modified_integrations: A list containing modified integrations names

        Returns:
            A tuple consists of:
            * A list of modified module instances configured
            * A list of new module instances configured
            * A list of integrations that have failed the 'test-module' command execution
            * A list of integrations that have succeeded the 'test-module' command execution
            * A list of new integrations names
        """
        tests_for_iteration = self.get_tests()
        modified_module_instances, new_module_instances, instance_test_only = self.configure_server_instances(
            tests_for_iteration, new_integrations, modified_integrations
        )
        logging.info(f'Found instance_test_only instances are: "{instance_test_only}"')
        successful_tests_pre, failed_tests_pre = self.instance_testing(
            modified_module_instances + instance_test_only, pre_update=True
        )
        return modified_module_instances, new_module_instances, failed_tests_pre, successful_tests_pre

    def install_packs(self, pack_ids: list | None = None, install_packs_in_batches=False, production_bucket: bool = True) -> bool:
        """
        Install packs using 'pack_ids' or "$ARTIFACTS_FOLDER_SERVER_TYPE/content_packs_to_install.txt" file,
        and their dependencies.
        Args:
            install_packs_in_batches: Whether to install packs in batches
            pack_ids (list | None, optional): Packs to install on the server.
                If no packs provided, installs packs that were provided by the previous step of the build.
            production_bucket (bool): Whether the installation is using production bucket for packs metadata. Defaults to True.

        Returns:
            bool: Whether packs installed successfully
        """
        pack_ids = self.pack_ids_to_install if pack_ids is None else pack_ids
        logging.info(f"IDs of packs to install: {pack_ids}")
        installed_content_packs_successfully = True
        try:
            _, flag = search_and_install_packs_and_their_dependencies(
                pack_ids=pack_ids,
                client=self.client,
                hostname="",
                install_packs_in_batches=install_packs_in_batches,
                production_bucket=production_bucket,
            )
            if not flag:
                raise Exception("Failed to search and install packs and their dependencies.")
        except Exception:
            logging.exception("Failed to search and install packs")
            installed_content_packs_successfully = False

        return installed_content_packs_successfully

    def set_marketplace_url(self, marketplace_name=None, artifacts_folder=None, marketplace_buckets=None):
        from Tests.Marketplace.search_and_uninstall_pack import sync_marketplace

        url_suffix = f"{quote_plus(self.build.branch_name)}/{self.build.ci_build_number}"
        config_path = "marketplace.bootstrap.bypass.url"
        config = {config_path: f"https://xdr-xsoar-content-dev-01.uc.r.appspot.com/content/builds/{url_suffix}"}
        self.add_server_configuration(config, "failed to configure marketplace custom url ", True)
        logging.info("Syncing marketplace")
        result = sync_marketplace(client=self.client)
        if not result:
            logging.critical("Failed to sync marketplace")
            return False
        logging.success("Updated marketplace url and restarted servers")
        logging.info("sleeping for 120 seconds")
        sleep(120)
        return True

    def test_integrations_post_update(self, new_module_instances: list, modified_module_instances: list) -> tuple:
        """
        Runs 'test-module on all integrations for post-update check
        Args:
            self: A server object
            new_module_instances: A list containing new integrations instances to run test-module on
            modified_module_instances: A list containing old (existing) integrations instances to run test-module on

        Returns:
            * A list of integration names that have failed the 'test-module' execution post update
            * A list of integration names that have succeeded the 'test-module' execution post update
        """
        modified_module_instances.extend(new_module_instances)
        successful_tests_post, failed_tests_post = self.instance_testing(modified_module_instances, pre_update=False)
        return successful_tests_post, failed_tests_post


class CloudServer(Server):
    def __init__(
        self,
        api_key,
        server_numeric_version,
        base_url,
        xdr_auth_id,
        name,
        pack_ids_to_install,
        tests_to_run,
        build,
        build_number,
        options,
    ):
        super().__init__()
        self.name = name
        self.api_key = api_key
        self._server_numeric_version = server_numeric_version
        self.base_url = base_url
        self.xdr_auth_id = xdr_auth_id
        self.pack_ids_to_install = pack_ids_to_install
        self.options = options
        self.secret_conf = get_secrets_from_gsm(self.options, options.branch, self.pack_ids_to_install)
        self.tests_to_run = tests_to_run
        self.build = build
        self.build_number = build_number
        self.__client = None
        # we use client without demisto username
        os.environ.pop("DEMISTO_USERNAME", None)
        self.test_pack_path = f"test_pack_{name}"

    def __str__(self):
        return self.name

    @property
    def server_numeric_version(self) -> str:
        return self._server_numeric_version

    def reconnect_client(self):
        self.__client = demisto_client.configure(
            base_url=self.base_url, verify_ssl=False, api_key=self.api_key, auth_id=self.xdr_auth_id
        )
        custom_user_agent = get_custom_user_agent(self.build_number)
        logging.debug(f"Setting user-agent on client to '{custom_user_agent}'.")
        self.__client.api_client.user_agent = custom_user_agent
        return self.__client

    def install_packs(self, pack_ids: list | None = None, install_packs_in_batches=False, production_bucket: bool = True) -> bool:
        """
        Install packs using 'pack_ids' or  packs from splitting algorithm,
        and their dependencies.
        Args:
            pack_ids (list | None, optional): Packs to install on the server.
                If no packs provided, installs packs that were provided by the previous step of the build.
            install_packs_in_batches: Whether to install packs in batches.
            production_bucket (bool): Whether the installation is using production bucket for packs metadata. Defaults to True.

        Returns:
            bool: Whether packs installed successfully
        """
        pack_ids = self.pack_ids_to_install if pack_ids is None else pack_ids
        logging.info(f"IDs of packs to install: {pack_ids}")
        installed_content_packs_successfully = True
        try:
            _, flag = search_and_install_packs_and_their_dependencies(
                pack_ids=pack_ids,
                client=self.client,
                hostname=self.name,
                install_packs_in_batches=True,
                production_bucket=production_bucket,
            )
            if not flag:
                raise Exception("Failed to search and install packs.")
        except Exception:
            logging.exception("Failed to search and install packs")
            installed_content_packs_successfully = False

        return installed_content_packs_successfully

    def add_core_pack_params(self, integration_params):
        """
        For cloud build we need to add core rest api params differently
        """
        integration_params[0]["params"] = {  # type: ignore
            "url": self.base_url,
            "creds_apikey": {
                "identifier": str(self.xdr_auth_id),
                "password": self.api_key,
            },
            "auth_method": "Standard",
            "insecure": True,
            "proxy": False,
        }

    def configure_and_test_integrations_pre_update(self, new_integrations, modified_integrations) -> tuple:
        """
        Configures integration instances that exist in the current version and for each integration runs 'test-module'.
        Args:
            self: Server object
            new_integrations: A list containing new integrations names
            modified_integrations: A list containing modified integrations names

        Returns:
            A tuple consists of:
            * A list of modified module instances configured
            * A list of new module instances configured
            * A list of integrations that have failed the 'test-module' command execution
            * A list of integrations that have succeeded the 'test-module' command execution
            * A list of new integrations names
        """
        tests_for_iteration = self.get_tests()
        modified_module_instances, new_module_instances, instance_test_only = self.configure_server_instances(
            tests_for_iteration, new_integrations, modified_integrations
        )
        instance_test_only_names = [integration["name"] for integration in instance_test_only]
        logging.info(f'Found the following instance_test_only instance: "{", ".join(instance_test_only_names)}"')
        successful_tests_pre, failed_tests_pre = self.instance_testing(
            modified_module_instances + instance_test_only, pre_update=True, use_mock=False
        )
        return modified_module_instances, new_module_instances, failed_tests_pre, successful_tests_pre

    def set_marketplace_url(
        self,
        marketplace_name="marketplacev2",
        artifacts_folder=ARTIFACTS_FOLDER_MPV2,
        marketplace_buckets=MARKETPLACE_XSIAM_BUCKETS,
    ):
        from Tests.Marketplace.search_and_uninstall_pack import sync_marketplace

        logging.info("Copying custom build bucket to cloud_instance_bucket.")
        marketplace_name = marketplace_name
        from_bucket = f"{MARKETPLACE_TEST_BUCKET[marketplace_name]}/{self.build.branch_name}/{self.build.ci_build_number}/content"
        output_file = f"{artifacts_folder}/Copy_custom_bucket_to_cloud_machine.log"
        success = True
        to_bucket = f"{marketplace_buckets}/{self.name}"
        cmd = f"gsutil -m -q cp -r gs://{from_bucket} gs://{to_bucket}/"
        with open(output_file, "w") as outfile:
            try:
                subprocess.run(cmd.split(), stdout=outfile, stderr=outfile, check=True)
                logging.info("Finished copying successfully.")
            except subprocess.CalledProcessError as exc:
                logging.exception(f"Failed to copy custom build bucket to cloud_instance_bucket. {exc}")
                success = False

        success &= sync_marketplace(self.client)

        if success:
            logging.info("Finished copying successfully.")
        else:
            logging.error("Failed to copy or sync marketplace bucket.")
        sleep_time = 360
        logging.info(f"sleeping for {sleep_time} seconds")
        sleep(sleep_time)
        return success

    def test_integrations_post_update(self, new_module_instances: list, modified_module_instances: list) -> tuple:
        """
        Runs 'test-module on all integrations for post-update check
        Args:
            self: Server object
            new_module_instances: A list containing new integrations instances to run test-module on
            modified_module_instances: A list containing old (existing) integrations instances to run test-module on

        Returns:
            * A list of integration names that have failed the 'test-module' execution post update
            * A list of integration names that have succeeded the 'test-module' execution post update
        """
        modified_module_instances.extend(new_module_instances)
        successful_tests_post, failed_tests_post = self.instance_testing(
            modified_module_instances, pre_update=False, use_mock=False
        )
        return successful_tests_post, failed_tests_post


# ------------------------------------------ Build Objects ---------------------------------------------------------


class Build(ABC):
    # START CHANGE ON LOCAL RUN #
    content_path = f'{os.getenv("HOME")}/project' if os.getenv("CIRCLECI") else os.getenv("CI_PROJECT_DIR")
    test_pack_target = f'{os.getenv("HOME")}/project/Tests' if os.getenv("CIRCLECI") else f'{os.getenv("CI_PROJECT_DIR")}/Tests'  # noqa
    key_file_path = "Use in case of running with non local server"
    run_environment = Running.CI_RUN
    env_results_path = ENV_RESULTS_PATH
    DEFAULT_SERVER_VERSION = "99.99.98"

    #  END CHANGE ON LOCAL RUN  #

    def __init__(self, options):
        self._proxy = None
        self.is_cloud = False
        self.servers = []
        self.server_numeric_version = ""
        self.git_sha1 = options.git_sha1
        self.branch_name = options.branch
        self.ci_build_number = options.build_number
        conf = get_json_file(options.conf)
        self.tests = conf["tests"]
        self.skipped_integrations_conf = conf["skipped_integrations"]
        self.service_account = options.service_account
        self.marketplace_tag_name = None
        self.artifacts_folder = None
        self.marketplace_buckets = None
        self.machine_assignment_json = get_json_file(options.machine_assignment)

    @property
    @abstractmethod
    def marketplace_name(self) -> str:
        pass

    @abstractmethod
    def configure_servers_and_restart(self):
        pass

    @abstractmethod
    def create_servers(self, options):
        pass

    # ---------------------------- Instance management --------------------------------------------

    def disable_instances(self):
        for server in self.servers:
            disable_all_integrations(server.client)

    def concurrently_run_function_on_servers(
        self, function=None, pack_path=None, service_account=None, packs_to_install=None
    ) -> tuple[bool, list[Any]]:
        if not function:
            raise Exception("Install method was not provided.")

        with ThreadPoolExecutor(max_workers=len(self.servers)) as executor:
            kwargs = {}
            if service_account:
                kwargs["service_account"] = service_account
            if pack_path:
                kwargs["pack_path"] = pack_path
            if packs_to_install:
                kwargs["pack_ids_to_install"] = packs_to_install

            futures = [
                executor.submit(
                    function, client=server.client, host=server.internal_ip if self.is_cloud else server.name, **kwargs
                )
                for server in self.servers
            ]

            # Wait for all tasks to complete
            results: list[Any] = []
            success = True
            for future in as_completed(futures):
                try:
                    results.append(future.result())
                except Exception as e:
                    logging.exception(f"Failed to run function with error: {e!s}")
                    success = False
            return success, results


class XSOARBuild(Build):
    DEFAULT_SERVER_VERSION = "6.99.99"

    def __init__(self, options):
        super().__init__(options)
        self.ami_env = options.ami_env
        self.servers = self.create_servers(options)
        self.server_numeric_version = (
            self.servers[0].server_numeric_version if self.run_environment == Running.CI_RUN else self.DEFAULT_SERVER_VERSION
        )

    @property
    def marketplace_name(self) -> str:
        return "xsoar"

    def configure_servers_and_restart(self):
        manual_restart = Build.run_environment == Running.WITH_LOCAL_SERVER
        for server in self.servers:
            configurations = {}
            if is_redhat_instance(server.internal_ip):
                configurations.update(DOCKER_HARDENING_CONFIGURATION_FOR_PODMAN)
                configurations.update(NO_PROXY_CONFIG)
                configurations["python.pass.extra.keys"] += "##--network=slirp4netns:cidr=192.168.0.0/16"
            else:
                configurations.update(DOCKER_HARDENING_CONFIGURATION)
            configure_types = ["docker hardening", "marketplace"]
            configurations.update(MARKET_PLACE_CONFIGURATION)

            error_msg = f"failed to set {' and '.join(configure_types)} configurations"
            server.add_server_configuration(configurations, error_msg=error_msg, restart=not manual_restart)

        if manual_restart:
            input("restart your server and then press enter.")
        else:
            logging.info("Done restarting servers. Sleeping for 1 minute")
            sleep(60)

    @staticmethod
    def get_servers(ami_env):
        env_conf = get_env_conf()
        return get_servers(env_conf, ami_env)

    def create_servers(self, options):
        logging.info("Starting server creation")
        servers = []

        packs_to_install = self.machine_assignment_json.get("xsoar-machine").get("packs_to_install")
        tests_to_run = self.machine_assignment_json.get("xsoar-machine").get("tests", {}).get(TEST_PLAYBOOKS, [])
        logging.info(f"{packs_to_install=}")
        logging.info(f"{tests_to_run=}")

        servers = [
            XSOARServer(
                internal_ip=internal_ip,
                pack_ids_to_install=packs_to_install,
                tests_to_run=tests_to_run,
                build=self,
                options=options,
                build_number=self.ci_build_number,
            )
            for internal_ip in self.get_servers(self.ami_env)
        ]

        logging.info("Done working on servers")
        return servers


class CloudBuild(Build):
    def __init__(self, options):
        global SET_SERVER_KEYS
        SET_SERVER_KEYS = False
        super().__init__(options)
        self.is_cloud = True
        self.servers = self.create_servers(options)
        self.marketplace_tag_name: str = options.marketplace_name
        self.artifacts_folder = options.artifacts_folder
        self.marketplace_buckets = options.marketplace_buckets

    @staticmethod
    def get_cloud_configuration(cloud_machine: str, cloud_servers_path):
        logging.info("getting cloud configuration")

        cloud_servers = get_json_file(cloud_servers_path)
        conf = cloud_servers.get(cloud_machine)
        cloud_machine_details = CloudBuild.get_cloud_machine_from_gsm(cloud_machine)
        logging.info(f"Got '{cloud_machine}' details from GSM")
        api_key = cloud_machine_details.get(BUILD_MACHINE_GSM_API_KEY)
        auth_id = cloud_machine_details.get(BUILD_MACHINE_GSM_AUTH_ID)
        return api_key, conf.get("demisto_version"), conf.get("base_url"), auth_id, conf.get("ui_url")

    @staticmethod
    def get_cloud_machine_from_gsm(cloud_machine) -> dict:
        secret_manager = SecretManager()
        cloud_machine_details = secret_manager.get_secret(secret_id=cloud_machine)
        cloud_machine_details = json5.loads(cloud_machine_details)
        return cloud_machine_details

    @property
    def marketplace_name(self) -> str:
        return self.marketplace_tag_name

    def configure_servers_and_restart(self):
        # No need of this step in cloud.
        pass

    def create_servers(self, options):
        logging.info("Starting server creation")
        servers = []
        for machine, info in self.machine_assignment_json.items():
            # since this loop doesn't run in parallel, we update the file with the needed instances secrets at each iteration
            logging.info(f"working on machine {machine!s}")

            packs_to_install = info.get("packs_to_install")
            tests_to_run = info.get("tests", {}).get(TEST_PLAYBOOKS, [])
            logging.info(f"{packs_to_install=}")
            logging.info(f"{tests_to_run=}")

            api_key, server_numeric_version, base_url, xdr_auth_id, _ = self.get_cloud_configuration(
                machine, options.cloud_servers_path
            )
            servers.append(
                CloudServer(
                    api_key=api_key,
                    server_numeric_version=server_numeric_version,
                    base_url=base_url,
                    xdr_auth_id=xdr_auth_id,
                    name=machine,
                    build_number=self.ci_build_number,
                    build=self,
                    pack_ids_to_install=packs_to_install,
                    tests_to_run=tests_to_run,
                    options=options,
                )
            )
        logging.info("Done working on servers")
        return servers


# ------------------------------------------------ Main ---------------------------------------------------------------


def options_handler(args=None):
    parser = argparse.ArgumentParser(description="Utility for instantiating and testing integration instances")
    parser.add_argument("-u", "--user", help="The username for the login", required=True)
    parser.add_argument("-p", "--password", help="The password for the login", required=True)
    parser.add_argument(
        "--ami_env",
        help="The AMI environment for the current run. Options are "
        '"Server Master", "Server 6.0". '
        "The server url is determined by the AMI environment.",
    )
    parser.add_argument("-g", "--git_sha1", help="commit sha1 to compare changes with")
    parser.add_argument("-c", "--conf", help="Path to conf file", required=True)
    parser.add_argument("-sn", "--sdk-nightly", type=str2bool, help="Is SDK nightly build")
    parser.add_argument("--branch", help="GitHub branch name", required=True)
    parser.add_argument("--build_number", help="CI job number where the instances were created", required=True)
    parser.add_argument(
        "-pl", "--pack_ids_to_install", help="Path to the packs to install file.", default="./content_packs_to_install.txt"
    )
    parser.add_argument(
        "--server_type", help=f'Server type running, choices: {",".join(SERVER_TYPES)}', default=Build.run_environment
    )
    parser.add_argument("--cloud_servers_path", help="Path to secret cloud server metadata file.")
    parser.add_argument("--marketplace_name", help="the name of the marketplace to use.")
    parser.add_argument("--artifacts_folder", help="the artifacts folder to use.")
    parser.add_argument("--marketplace_buckets", help="the path to the marketplace buckets.")
    parser.add_argument(
        "--machine_assignment", help="the path to the machine assignment file.", default="./machine_assignment.json"
    )
    parser.add_argument(
        "-sa",
        "--service_account",
        help=(
            "Path to gcloud service account, is for circleCI usage. "
            "For local development use your personal account and "
            "authenticate using Google Cloud SDK by running: "
            "`gcloud auth application-default login` and leave this parameter blank. "
            "For more information go to: "
            "https://googleapis.dev/python/google-api-core/latest/auth.html"
        ),
        required=False,
    )
    parser.add_argument(
        "--gsm_service_account",
        help=(
            "Path to gcloud service account, for circleCI usage. "
            "For local development use your personal account and "
            "authenticate using Google Cloud SDK by running: "
            "`gcloud auth application-default login` and leave this parameter blank. "
            "For more information see: "
            "https://googleapis.dev/python/google-api-core/latest/auth.html"
        ),
    )
    parser.add_argument("--gsm_project_id_dev", help="The project id for the GSM dev.")
    parser.add_argument("--gsm_project_id_prod", help="The project id for the GSM prod.")
    parser.add_argument("-gt", "--github_token", help="the github token.")
    parser.add_argument("-sf", "--json_path_file", help="Path to the secret json file.")
    # disable-secrets-detection-end
    options = parser.parse_args(args)

    return options


def create_build_object() -> Build:
    options = options_handler()
    logging.info(f"Server type: {options.server_type}")
    if options.server_type == XSOAR_SERVER_TYPE:
        return XSOARBuild(options)
    elif options.server_type in [XsiamClient.SERVER_TYPE, XsoarClient.SERVER_TYPE]:
        return CloudBuild(options)
    else:
        raise Exception(f"Wrong Server type {options.server_type}.")


def main():
    """
    The flow is:
        1. Add server config and restart servers (only in xsoar).
        2. Disable all enabled integrations.
        3. Finds only modified (not new) packs and install them, same version as in production.
            (before the update in this branch).
        4. Finds all the packs that should not be installed, like turned hidden -> non-hidden packs names
           or packs with higher min version than the server version,
           or existing packs that were added to a new marketplace.
        5. Compares master to commit_sha and return two lists - new integrations and modified in the current branch.
           Filter the lists, add the turned non-hidden to the new integrations list and remove it from the modified list
           This filter purpose is to ignore the turned-hidden integration tests in the pre-update step. (#CIAC-3009)
        6. Configures integration instances (same version as in production) for the modified packs
            and runs `test-module` (pre-update).
        7. Changes marketplace bucket to the new one that was created in create-instances workflow.
        8. Installs all (new and modified) packs from current branch.
        9. After updating packs from branch, runs `test-module` for both new and modified integrations,
            to check that modified integrations was not broken. (post-update).
        10. Upload the test playbooks of packs from the packs to install list.
        11. Prints results.
    """
    install_logging("Install_Content_And_Configure_Integrations_On_Server.log", logger=logging)
    build = create_build_object()
    logging.info(f"Build Number: {build.ci_build_number}")

    build.configure_servers_and_restart()
    build.disable_instances()

    with ThreadPoolExecutor(max_workers=len(build.servers)) as executor:
        futures = [executor.submit(server.perform_single_server_test_flow) for server in build.servers]

        # Wait for all tasks to complete
        success = True
        for future in as_completed(futures):
            try:
                success &= future.result()
            except Exception as e:
                logging.exception(f"Failed to run function with error: {e!s}")
                success = False

    if not success:
        logging.error("Failed to configure and test integration instances.")
        sys.exit(2)

    logging.success("Finished configuring and testing integration instances.")


if __name__ == "__main__":
    main()
