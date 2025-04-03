import argparse
import json
import os
import re
import shutil
import sys
from tempfile import mkdtemp
from typing import Any

from demisto_sdk.commands.common.constants import MarketplaceVersionToMarketplaceName
from demisto_sdk.commands.content_graph.common import ContentType, RelationshipType
from demisto_sdk.commands.content_graph.interface.neo4j.neo4j_graph import Neo4jContentGraphInterface
from google.cloud.storage import Blob
from packaging.version import Version

from Tests.Marketplace.logs_aggregator import LogAggregator
from Tests.Marketplace.marketplace_constants import GCPConfig
from Tests.Marketplace.marketplace_services import init_storage_client, load_json
from Tests.Marketplace.upload_packs import (
    download_and_extract_index,
    download_and_extract_pack,
)
from Tests.scripts.utils import logging_wrapper as logging
from Tests.scripts.utils.log_util import install_logging

VERSION_FORMAT_REGEX = "\d{1,3}\.\d{1,3}\.\d{1,3}"
LATEST_ZIP_REGEX = re.compile(
    rf"^{GCPConfig.GCS_PUBLIC_URL}/[\w./-]+/content/packs/([A-Za-z0-9-_.]+/\d+\.\d+\.\d+/" r"[A-Za-z0-9-_.]+\.zip$)"
)
PACK_REGEX = re.compile(r"([A-Za-z0-9-_.]+)/(\d+\.\d+\.\d+)/([A-Za-z0-9-_.]+)\.zip$")


def option_handler():
    """Validates and parses script arguments.

    Returns:
        Namespace: Parsed arguments object.

    """
    parser = argparse.ArgumentParser(description="Validate core packs list.")
    # disable-secrets-detection-start
    parser.add_argument(
        "-s",
        "--service_account",
        help=(
            "Path to gcloud service account, is for Gitlab usage. "
            "For local development use your personal account and "
            "authenticate using Google Cloud SDK by running: "
            "`gcloud auth application-default login` and leave this parameter blank. "
            "For more information go to: "
            "https://googleapis.dev/python/google-api-core/latest/auth.html"
        ),
        required=False,
    )
    parser.add_argument("-bb", "--build_bucket_name", help="Gitlab Build bucket name", required=False)
    parser.add_argument(
        "-n",
        "--ci_build_number",
        help="Gitlab build number (will be used as hash revision at index file)",
        required=False,
    )
    parser.add_argument("-c", "--gitlab_branch", help="Gitlab branch of current build", required=False)
    parser.add_argument("-mp", "--marketplace", help="marketplace version", default="xsoar")
    parser.add_argument("-sv", "--server_version", help="The server version of the core packs list to override", required=False)
    # disable-secrets-detection-end
    return parser.parse_args()


def get_last_corepacks_files_from_versions_metadata() -> tuple:
    """
    Gets the last two names of the corepacks-x.x.x.json files from the build bucket.
    """
    core_packs_file_versions: dict[str, dict] = GCPConfig.core_packs_file_versions
    sorted_versions_metadata_dict = dict(sorted(core_packs_file_versions.items(), key=lambda version: Version(version[0])))
    logging.debug(f"Sorted core packs file versions metadata: {sorted_versions_metadata_dict}")
    last_version = sorted_versions_metadata_dict[list(sorted_versions_metadata_dict.keys())[-1]].get("core_packs_file")
    penultimate_version = sorted_versions_metadata_dict[list(sorted_versions_metadata_dict.keys())[-2]].get("core_packs_file")
    logging.info(f"Validate the lists for {last_version=}, {penultimate_version=}")
    return last_version, penultimate_version


def get_file_blob(storage_bucket: Any, path: str) -> Blob:
    """Get file Blob.
    Args:
        storage_bucket (google.cloud.storage.bucket.Bucket): google cloud storage bucket.
        path (str): The path of the file.
    Returns:
        Blob: google cloud storage object that represents file blob.
    """
    index_storage_path = os.path.join(path)
    index_blob = storage_bucket.blob(index_storage_path)
    return index_blob


def get_core_packs_content(core_packs_file_data: dict, core_packs_dict: dict):
    """Gets the relevant dictionary from the corepacks.json file.

    Args:
        core_packs_file_data (dict): The content of the core packs list file.
        core_packs_dict (dict): An empty dict that will have the wanted info in the end of the function.
    Returns:
        dict: The relevant part of the core packs list. For example:
        {"pack_name":
            {"version": "1.0.0", "index_zip_path": "/pack_name/metadata-1.0.0.json"}
        }

    """
    core_packs_file_list = core_packs_file_data.get("corePacks", [])
    for core_pack_path in core_packs_file_list:
        pack_name = extract_pack_name_from_path(core_pack_path)
        pack_version = extract_pack_version_from_pack_path(core_pack_path, pack_name)
        core_packs_dict.update(
            {
                f"{pack_name}": {
                    "version": pack_version,
                    "index_zip_path": f"/{pack_name}/metadata-{pack_version}.json",
                }
            }
        )


def get_core_packs_from_artifacts(path: str) -> dict:
    """Gets the content of the core packs list file from the artifacts in order to create a dict with the needed info.

    Args:
        path (str): The path in the artifacts folder of the relevant core packs file.
    Returns:
        dict: The relevant part of the core packs list.

    """
    core_packs_dict: dict[Any, Any] = {}
    logging.debug(f"Getting the core packs file content from the {path=}.")
    core_packs_file_data = load_json(path)
    if core_packs_file_data:
        get_core_packs_content(core_packs_file_data, core_packs_dict)
    else:
        logging.info(f"{path} does not exists in the artifacts, will not be checked.")
    return core_packs_dict


def get_core_packs_from_file(storage_bucket: Any, path: str) -> dict:
    """Gets the core pack list from the corepacks.json file in the build bucket.

    Args:
        storage_bucket (google.cloud.storage.bucket.Bucket): google storage bucket where corepacks.json is stored.
        path (str): The path of the corepacks.json file.
    Returns:
        dict: The core packs dict.

    """
    core_packs_dict: dict[Any, Any] = {}
    blob = get_file_blob(storage_bucket, path)
    if blob.exists():
        logging.debug(f"Getting the core packs file content from the {storage_bucket=}.")
        with blob.open("r") as f:
            core_packs_file_data = json.load(f)
            get_core_packs_content(core_packs_file_data, core_packs_dict)
    else:
        logging.info(f"{path} does not exists in the bucket, will not be checked.")
    return core_packs_dict


def get_dependencies_from_pack_meta_data(pack_path: str, folder_path: str) -> dict:
    """Gets the meta data file of a specific pack.

    Args:
        pack_path (str): The path of the pack.
        folder_path (str): he path of the folder.
    Returns:
        dict: The pack dependencies.

    """
    pack_metadata_path = folder_path + pack_path
    if os.path.exists(pack_metadata_path):
        with open(pack_metadata_path) as pack:
            pack_meta_data_json = json.load(pack)
            # if dependencies is empty we get {}
            pack_dependencies = pack_meta_data_json.get("dependencies")
            if pack_dependencies is None:
                logging.critical(f"We dont have pack_dependencies for: {pack_path=}")
                sys.exit(1)
            return pack_dependencies
    else:
        logging.critical(f"Could not find {pack_metadata_path}")
        sys.exit(1)


def verify_all_mandatory_dependencies_are_in_corepack_list(
    pack_name: str,
    pack_version: str,
    dependencies: dict,
    core_packs: dict,
    file_to_check: str,
    marketplace: str,
    zip_or_index_file: str,
    log_aggregator: LogAggregator,
) -> None:
    """Verify all mandatory dependencies are in corepack list.
    Args:
        pack_name (str): The pack name.
        pack_version (str): The version of the pack.
        dependencies (dict): The dependencies of the pack.
        core_packs (dict): A dict with all the core packs.
        file_to_check (str): The file we are checking.
        marketplace (str): the marketplace type of the bucket. possible options: xsoar, marketplace_v2 or xpanse.
        zip_or_index_file (str): The type of the file we are checking - for logs.
        log_aggregator (LogAggregator): logs aggregator.
    Returns:
        None
    """
    for dependency_name, dependency_data in dependencies.items():
        if dependency_data.get("mandatory", False):
            min_version = dependency_data.get("minVersion")
            if core_pack := core_packs.get(dependency_name):
                if min_version and core_pack.get("version"):
                    if Version(min_version) <= Version(core_pack.get("version")):
                        logging.debug(
                            f"for pack {pack_name}/{pack_version} "
                            f"The dependency {dependency_name}/{min_version} in the {zip_or_index_file} "
                            f"meets the conditions for {dependency_name}/{core_pack.get('version')} "
                            f"for the {file_to_check} list."
                        )
                    else:
                        log_aggregator.add_log(
                            f"The dependency {dependency_name}/{min_version} "
                            f"of the pack {pack_name}/{pack_version} in the {zip_or_index_file} "
                            f"does not meet the conditions for {dependency_name}/{core_pack.get('version')} "
                            f"in the {file_to_check} list."
                        )
                else:
                    log_aggregator.add_log(
                        f"No minVersion or version for pack dependency"
                        f" {dependency_name=} for pack {pack_name} version {pack_version}."
                    )
            else:
                logging.debug(
                    f"The dependency {dependency_name} with min version number {min_version} "
                    f"of the pack {pack_name}/{pack_version} "
                    f"Does not exists in core pack list. - check_if_test_dependency."
                )
                if not (check_if_test_dependency(dependency_name, pack_name, marketplace)):
                    log_aggregator.add_log(
                        f"The dependency {dependency_name} with min version number {min_version} "
                        f"of the pack {pack_name}/{pack_version} "
                        f"Does not exists in core pack list {file_to_check}."
                    )


def extract_pack_name_from_path(path_of_the_pack: str) -> str:
    """Extracts the pack version from the pack path.

    Examples
        >>> extract_pack_name_from_path('pack-name/1.1.38/pack-name.zip')
        pack-name

    Args:
        path_of_the_pack (str): The path of the pack.

    Returns:
        str: The pack name
    """
    pack_name_extraction = re.findall(PACK_REGEX, path_of_the_pack)
    if pack_name_extraction and pack_name_extraction[0]:
        pack_name = pack_name_extraction[0][0]
        return pack_name
    logging.critical(f"Could not find pack name for {path_of_the_pack}")
    sys.exit(1)


def extract_pack_version_from_pack_path(path_of_the_pack: str, pack_name: str) -> str:
    """Extracts the pack version from the pack path.

    Examples
        >>> extract_pack_version_from_pack_path('pack-name/1.1.38/pack-name.zip', 'pack-name')
        1.1.38

    Args:
        path_of_the_pack (str): The path of the pack.
        pack_name (str): The name of the pack.

    Returns:
        str: The pack version
    """
    pack_path_extraction = re.findall(PACK_REGEX, path_of_the_pack)
    if pack_path_extraction:
        pack_verison = pack_path_extraction[0][1]
        pack_version_regex = re.findall(VERSION_FORMAT_REGEX, pack_verison)
    else:
        pack_version_regex = re.findall(VERSION_FORMAT_REGEX, path_of_the_pack)
    if pack_version_regex:
        pack_version = pack_version_regex[0]
        return pack_version
    logging.critical(f"Could not find pack version for {pack_name}")
    sys.exit(1)


def check_if_test_dependency(dependency_name: str, pack_name: str, marketplace: str) -> bool:
    """Checks if the dependency of the pack is test dependency.
    Args:
        dependency_name (str): The name of the dependency.
        pack_name (str): The name of the pack.
        marketplace (str): the marketplace type of the bucket. possible options: xsoar, marketplace_v2 or xpanse.
    Returns:
        bool: Whether the dependency is test dependency.
    """
    with Neo4jContentGraphInterface() as interface:
        res = interface.search(content_type=ContentType.PACK, marketplace=marketplace, object_id=pack_name)
        logging.debug(f"Content type for {pack_name} result is {bool(res)}")
        for node in res:
            for dependency in node.relationships_data[RelationshipType.DEPENDS_ON]:
                if (
                    dependency.content_item_to.database_id == dependency.target_id
                    and dependency.is_test
                    and dependency.content_item_to.object_id == dependency_name
                ):
                    logging.debug(f"The dependency {dependency_name} " f"of the pack {pack_name} is a test dependency")
                    return True
        return False


def prepare_validate_corepacks(
    marketplace: str, option: argparse.Namespace, gitlab_branch: str | None, build_number: str = ""
) -> tuple:
    """Prepares the relevant parameters depending on the use case.
        1. Override-corepacks-list flow.
            a. The relevant corepacks list in this case is in the artifacts folder.
            b. There is no build and no build bucket in this flow. As a result the bucket_base_path is different.
            c. Checks only the specific server version that was requested in the flow parameters.
        2. Regular build flow.
            a. There is a PR and a build or an active upload flow.
            b. As a result there is a build bucket.
            c. Checks the 2 last versions of the core pack (the unlocked one and the latest locked one).
    Args:
        marketplace (str): the marketplace type of the bucket. possible options: xsoar, marketplace_v2 or xpanse.
        option (argparse.Namespace)
        gitlab_branch (str | None): The relevant gitlab branch from the MR, if relevant.
        build_number (str | None): The number of the relevant build.
    Returns:
        A tuple of the parameters to be used later in the validation bucket_name, artifacts_folder, bucket_base_path,
        corepacks_files_names.
    """
    if not gitlab_branch:  # override-corepacks-list case
        bucket_name = MarketplaceVersionToMarketplaceName[marketplace]
        artifacts_folder = os.getenv("ARTIFACTS_FOLDER")
        server_version = option.server_version
        bucket_base_path = GCPConfig.CONTENT_PACKS_PATH
        corepacks_files_names = [f"corepacks-{server_version}.json"]
        logging.debug(
            f"Validating core packs list versions in override core packs pipeline. {corepacks_files_names=} "
            f"{bucket_name=}, {artifacts_folder=}."
        )

    else:
        artifacts_folder = ""
        bucket_name = GCPConfig.CI_BUILD_BUCKETS[marketplace]
        build_bucket_path = os.path.join(GCPConfig.BUILD_PATH_PREFIX, gitlab_branch, build_number)
        bucket_base_path = os.path.join(build_bucket_path, GCPConfig.CONTENT_PACKS_PATH)

        # Get relevant files name of corepacks-x.x.x.json or corepacks.json
        corepacks_json_file_name = f"{GCPConfig.CORE_PACK_FILE_NAME}"
        last_version_corepacks, penultimate_version_corepacks = get_last_corepacks_files_from_versions_metadata()

        corepacks_files_names = [
            penultimate_version_corepacks,
            last_version_corepacks,
            corepacks_json_file_name,
        ]
        logging.debug(f"Validate core packs list versions in a build bucket. {corepacks_files_names=} {bucket_name=}.")
    return bucket_name, artifacts_folder, bucket_base_path, corepacks_files_names


def main():
    install_logging("validate_core_pack_list.log", logger=logging)
    option = option_handler()

    # Initialize build base paths.
    logging.debug("Initialize build base paths.")
    marketplace = option.marketplace
    build_number = option.ci_build_number
    gitlab_branch = option.gitlab_branch
    extract_destination_path = mkdtemp()

    bucket_name, artifacts_folder, bucket_base_path, corepacks_files_names = prepare_validate_corepacks(
        marketplace, option, gitlab_branch, build_number
    )

    # google cloud storage client initialized.
    logging.debug("init storage_client")
    storage_client = init_storage_client()
    storage_bucket = storage_client.bucket(bucket_name)

    # Get the index file from the bucket.
    index_folder_path, _, _ = download_and_extract_index(storage_bucket, extract_destination_path, bucket_base_path)

    with LogAggregator() as log_aggregator:
        for corepacks_file_name in corepacks_files_names:
            if not artifacts_folder:
                core_packs = get_core_packs_from_file(storage_bucket, os.path.join(bucket_base_path, corepacks_file_name))
            else:
                core_packs = get_core_packs_from_artifacts(os.path.join(artifacts_folder, bucket_name, corepacks_file_name))
            for pack_name, pack_data in core_packs.items():
                pack_version = pack_data.get("version")
                if pack_path_after_extraction := download_and_extract_pack(
                    pack_name,
                    pack_version,
                    storage_bucket,
                    extract_destination_path,
                    bucket_base_path,
                ):
                    metadata_zip_index = get_dependencies_from_pack_meta_data(pack_data.get("index_zip_path"), index_folder_path)
                    metadata_zip_pack = get_dependencies_from_pack_meta_data("/metadata.json", pack_path_after_extraction)  # type: ignore[arg-type]

                    for dependencies, zip_or_index_file in [
                        (metadata_zip_index, "index.zip"),
                        (metadata_zip_pack, f"{pack_name}.zip"),
                    ]:
                        verify_all_mandatory_dependencies_are_in_corepack_list(
                            pack_name,
                            pack_version,
                            dependencies,
                            core_packs,
                            corepacks_file_name,
                            marketplace,
                            zip_or_index_file,
                            log_aggregator,
                        )
                    if isinstance(pack_path_after_extraction, str):
                        shutil.rmtree(pack_path_after_extraction)
                else:
                    log_aggregator.add_log(
                        f"pack {pack_name=} version from core pack " f"{pack_data.get('version')=} not in the bucket"
                    )
        shutil.rmtree(index_folder_path)


if __name__ == "__main__":
    main()
