import argparse
import json
import xml.etree.ElementTree as ET  # noqa
from collections import defaultdict
from json import JSONEncoder
from pathlib import Path

from google.cloud import storage  # type: ignore[attr-defined]
from junitparser import JUnitXml, TestSuite

from Tests.Marketplace.common import fetch_pack_ids_to_install
from Tests.Marketplace.marketplace_services import init_storage_client, load_json
from Tests.scripts.collect_tests.constants import (
    ALWAYS_INSTALLED_PACKS_MAPPING,
    MODELING_RULES_TO_TEST_FILE,
    TEST_MODELING_RULES,
    TEST_PLAYBOOKS,
    TEST_USE_CASES,
    TPB_DEPENDENCIES_FILE,
    USE_CASE_TO_TEST_FILE,
    MarketplaceVersions,
)
from Tests.scripts.utils import logging_wrapper as logging
from Tests.scripts.utils.log_util import install_logging

ARTIFACTS_BUCKET = "xsoar-ci-artifacts"
XML_MIME_TYPE = "application/xml"
MAX_REPORT_FILES = 15
TEST_PLAYBOOKS_DEFAULT_EXECUTION_TIME = 600.0
TEST_MODELING_RULES_DEFAULT_EXECUTION_TIME = 300.0
TEST_USE_CASE_DEFAULT_EXECUTION_TIME = 600.0


class PackInfo:
    def __init__(self, name):
        self.name = name
        self.tests: dict[str, set] = {
            TEST_PLAYBOOKS: set(),
            TEST_MODELING_RULES: set(),
            TEST_USE_CASES: set(),
        }
        self.dependencies = set()
        self.total_expected_execution_time = 0.0


class MachineAssignmentEncoder(JSONEncoder):
    def default(self, o):
        if isinstance(o, MachineAssignment):
            return o.__dict__
        if isinstance(o, set):
            return list(o)
        return o.__dict__


class MachineAssignment:
    def __init__(self, machine_name: str, packs_to_install: set[str] | None = None, tests: dict | None = None):
        self.machine_name = machine_name
        self.packs_to_install = packs_to_install or set()
        self.tests = (
            {
                TEST_PLAYBOOKS: set(),
                TEST_MODELING_RULES: set(),
                TEST_USE_CASES: set(),
            }
            if tests is None
            else tests
        )


class Tests:
    def __init__(
        self,
        test_type: str,
        tests: dict,
        test_times: dict[str, float],
    ):
        self.tests = tests
        self.test_times = test_times
        self.test_type = test_type


def build_pack_information(tests_info: list[Tests]) -> dict[str, PackInfo]:
    """
    Builds pack information
    Args:
        tests_info: tests information.
    Returns: packs objects to install.

    """
    packs_objects_to_install = {}
    for test_info in tests_info:
        for name, info in test_info.tests.items():
            pack_name = info["pack"]
            if pack_name not in packs_objects_to_install:
                pack_obj: PackInfo = PackInfo(pack_name)
                packs_objects_to_install[pack_name] = pack_obj
            else:
                pack_obj = packs_objects_to_install[pack_name]

            pack_obj.tests[test_info.test_type].add(name)
            pack_obj.total_expected_execution_time += test_info.test_times[name]
            pack_obj.dependencies |= set(info.get("dependencies", []))

    return packs_objects_to_install


def machine_assignment(
    packs_objects_to_install: dict, machines: set, packs_to_install_from_file: list, marketplace: MarketplaceVersions
) -> dict[str, MachineAssignment]:
    """
    Split packs into available machines
    Args:
        packs_objects_to_install: all packs objects to install - test related.
        machines: available machines.
        packs_to_install_from_file: list of packs from content_packs_to_install.txt file created in test collection.
        marketplace: marketplace version
    """
    machine_assignments: dict[str, MachineAssignment] = {machine: MachineAssignment(machine) for machine in machines}
    machine_loads = {machine: 0 for machine in machines}

    sorted_packs_by_execution_time = sorted(
        packs_objects_to_install.values(), key=lambda pack: pack.total_expected_execution_time, reverse=True
    )
    logging.info(
        f"Sorted packs by execution times are: "
        f"{[(pack.name, pack.total_expected_execution_time) for pack in sorted_packs_by_execution_time]}"
    )
    logging.info(f"packs to install from file: {packs_to_install_from_file!s}")
    for pack in sorted_packs_by_execution_time:
        logging.debug(f"current load on machines is {machine_loads!s}")
        min_load_machine = min(machine_loads, key=lambda machine: machine_loads[machine])
        machine_assignments[min_load_machine].packs_to_install.update({pack.name, *pack.dependencies})
        for test_type in pack.tests:
            machine_assignments[min_load_machine].tests[test_type].update({*pack.tests[test_type]})
        machine_loads[min_load_machine] += pack.total_expected_execution_time
        logging.debug(f"load on machines after assigning: {machine_loads!s}")
        logging.debug(f"assignment on machines after assigning: {machine_assignments!s}")

        if pack.name in packs_to_install_from_file:
            packs_to_install_from_file.remove(pack.name)
            logging.debug(f"Removing {pack.name} from packs_to_install list (already collected)")

    # Assigning the remaining packs which only need installation without any tests to the machine with the minimal load.
    minimal_machine = min(machine_loads, key=lambda machine: machine_loads[machine])
    machine_assignments[minimal_machine].packs_to_install.update(packs_to_install_from_file)

    # Adding the always installed packs list into each machine.
    final_assignments: dict[str, MachineAssignment] = {
        machine: MachineAssignment(
            machine, machine_dict.packs_to_install | set(ALWAYS_INSTALLED_PACKS_MAPPING[marketplace]), machine_dict.tests
        )
        for machine, machine_dict in machine_assignments.items()
    }

    return final_assignments


def get_properties_for_test_suite(test_suite: TestSuite) -> dict[str, str]:
    return {prop.name: prop.value for prop in test_suite.properties()}


def calculate_average_execution_time(
    bucket_name: str,
    download_prefix: str,
    matching_property: str,
    server_type: str,
    tests_file: Path,
    test_type: str,
    storage_client: storage.Client,
    max_files: int,
    default_execution_time: float,
) -> Tests:
    """
    This function iterates over files in the path, parses the XML files and calculates the average execution
    time for each test.
    Args:
        bucket_name: The name of the GCP bucket.
        download_prefix: The prefix to download the reports from.
        matching_property: The property to match the tests by.
        server_type: The server type to filter the results for.
        tests_file: The path to the JSON file that contains the tests to packs mapping.
        test_type: The type of the tests to calculate the average execution time for.
        storage_client: The path to the service account JSON file.
        max_files: Max files to examine.
        default_execution_time: The default execution time to use if the time is not available.

    Returns:
        A dictionary where keys are tests and values are the average execution time.
    """
    tests = load_json(tests_file.as_posix())
    prefix = f"{download_prefix}/{server_type}/"

    # List files in the bucket path
    blobs = storage_client.list_blobs(bucket_name, prefix=prefix)

    # Filter and sort XML files by the most recent
    xml_files = [blob for blob in blobs if blob.content_type == XML_MIME_TYPE]
    xml_files.sort(key=lambda x: x.updated, reverse=True)  # Sort by updated time, most recent first
    logging.info(f"Sorted XML files by updated time: {[blob.name for blob in xml_files]}")

    tests_times = defaultdict(list)

    for blob in xml_files[:max_files]:
        try:
            blob_data = blob.download_as_string()
            xml = JUnitXml.fromstring(blob_data)
        except Exception as e:
            # Handle potential errors during file download or parsing
            logging.info(f"Error processing file {blob.name}: {e}")
            continue

        for test_suite in xml.iterchildren(TestSuite):
            if test_suite.skipped != 0:
                # Skip tests that were skipped.
                continue

            test_suite_properties = get_properties_for_test_suite(test_suite)
            test_matching_property = test_suite_properties.get(matching_property)
            if test_matching_property not in tests:
                continue

            logging.debug(f"Processing test {test_matching_property}")
            try:
                tests_times[test_matching_property].append(float(test_suite.time))
            except ValueError:
                # Handle potential errors during time conversion
                logging.warning(f"Error parsing execution time for {test_matching_property} in {blob.name}")

    # Calculate average execution time for each playbook
    average_times = {}
    for test in tests:
        times = tests_times.get(test, [])
        average_times[test] = sum(times) / len(times) if times else default_execution_time

    logging.info(f"Calculated average execution times: {average_times}")
    return Tests(test_type, tests, average_times)


def options_handler() -> argparse.Namespace:
    """
    Returns: options parsed from input arguments.
    """
    parser = argparse.ArgumentParser(description="Utility for splitting packs installation into chosen cloud machines")
    parser.add_argument("--cloud_machines", help="List of chosen cloud machines", nargs="?", default=None)
    parser.add_argument("--server_type", help="Type of server currently running tests on.", required=True)
    parser.add_argument("--artifacts-path", help="Path to the artifacts folder", required=True)
    parser.add_argument("--service_account", help="Path to gcloud service account.")
    parser.add_argument("--marketplace", type=MarketplaceVersions, help="marketplace version", default=MarketplaceVersions.XSOAR)
    options = parser.parse_args()
    return options


def main():
    install_logging("split_packs_to_machines.log", logger=logging)

    options = options_handler()
    storage_client = init_storage_client()

    machine_list = set(options.cloud_machines.split(",") if options.cloud_machines else ("xsoar-machine",))
    logging.info(f"machines:{machine_list}")

    artifacts_path = Path(options.artifacts_path)
    logging.info("Calling calculate")
    tests_info = [
        calculate_average_execution_time(
            bucket_name=ARTIFACTS_BUCKET,
            download_prefix="content-playbook-reports",
            matching_property="playbook_id",
            server_type=options.server_type,
            tests_file=artifacts_path / TPB_DEPENDENCIES_FILE,
            test_type=TEST_PLAYBOOKS,
            storage_client=storage_client,
            max_files=MAX_REPORT_FILES,
            default_execution_time=TEST_PLAYBOOKS_DEFAULT_EXECUTION_TIME,
        ),
        calculate_average_execution_time(
            bucket_name=ARTIFACTS_BUCKET,
            download_prefix="content-test-modeling-rules",
            matching_property="modeling_rule_path",
            server_type=options.server_type,
            tests_file=artifacts_path / MODELING_RULES_TO_TEST_FILE,
            test_type=TEST_MODELING_RULES,
            storage_client=storage_client,
            max_files=MAX_REPORT_FILES,
            default_execution_time=TEST_MODELING_RULES_DEFAULT_EXECUTION_TIME,
        ),
        calculate_average_execution_time(
            bucket_name=ARTIFACTS_BUCKET,
            download_prefix="content-test-use-case-reports",
            matching_property="test_use_case_path",
            server_type=options.server_type,
            tests_file=artifacts_path / USE_CASE_TO_TEST_FILE,
            test_type=TEST_USE_CASES,
            storage_client=storage_client,
            max_files=MAX_REPORT_FILES,
            default_execution_time=TEST_USE_CASE_DEFAULT_EXECUTION_TIME,
        ),
    ]

    logging.info("Calling build pack information")
    packs_objects_to_install = build_pack_information(tests_info)

    marketplace = MarketplaceVersions(options.marketplace)
    logging.info(f"Calling machine assignment, marketplace: {marketplace}")
    packs_to_install = fetch_pack_ids_to_install((artifacts_path / "content_packs_to_install.txt").as_posix())
    machine_assignments = machine_assignment(packs_objects_to_install, machine_list, packs_to_install, marketplace)

    # output files

    output_file = artifacts_path / "machine_assignment.json"
    logging.info(f"Final machine assignments written to:{output_file}")
    output_file.write_text(json.dumps(machine_assignments, cls=MachineAssignmentEncoder, indent=4, sort_keys=True))


if __name__ == "__main__":
    main()
