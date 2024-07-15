import argparse
import json
import os
from pathlib import Path
from google.cloud import storage  # type: ignore[attr-defined]
import xml.etree.ElementTree as ET
from Tests.Marketplace.common import fetch_pack_ids_to_install
from Tests.Marketplace.marketplace_services import load_json
from Tests.scripts.collect_tests.constants import ALWAYS_INSTALLED_PACKS_MAPPING, MarketplaceVersions
from Tests.scripts.utils.log_util import install_logging
from Tests.scripts.utils import logging_wrapper as logging


ARTIFACTS_FOLDER_SERVER_TYPE = Path(os.getenv('ARTIFACTS_FOLDER_SERVER_TYPE', '.'))
ARTIFACTS_BUCKET = 'xsoar-ci-artifacts'
MAX_REPORT_FILES = 15
DEFAULT_PLAYBOOK_EXECUTION_TIME = 600.0


class PackInfo:
    def __init__(self, name):
        self.name = name
        self.test_playbooks_to_run = set()
        self.dependencies = set()
        self.total_expected_execution_time = 0.0


def build_pack_information(playbooks: dict, playbook_times:  dict[str, float]) -> dict[str, PackInfo]:
    """
    Builds pack information
    Args:
        playbooks: playbooks information. For each playbook - what is its pack and what its dependencies.
                    example: {"tpb": {"pack": pack_id, "dependencies": list(dependencies_packs)}}
        playbook_times: mapping between playbook name to avg past execution time.

    Returns: packs objects to install.

    """
    packs_objects_to_install = {}
    for name, info in playbooks.items():
        pack_name = info['pack']
        if pack_name not in packs_objects_to_install:
            pack_obj: PackInfo = PackInfo(pack_name)
            packs_objects_to_install[pack_name] = pack_obj
        else:
            pack_obj = packs_objects_to_install[pack_name]

        pack_obj.test_playbooks_to_run.add(name)
        pack_obj.total_expected_execution_time += playbook_times[name]
        pack_obj.dependencies |= set(info['dependencies'])

    return packs_objects_to_install


def machine_assignment(packs_objects_to_install: dict, machines: set, packs_to_install_from_file: list,
                       marketplace: MarketplaceVersions) -> dict[str, dict[str, list[str]]]:
    """
    Split packs into available machines
    Args:
        packs_objects_to_install: all packs objects to install - test playbook related.
        machines: available machines.
        packs_to_install_from_file: list of packs from content_packs_to_install.txt file created in test collection.
        marketplace: marketplace version
    """
    machine_assignments: dict[str, dict[str, set[str]]] = {machine: {'packs_to_install': set(), 'playbooks_to_run':
        set()} for machine in machines}
    machine_loads = {machine: 0 for machine in machines}

    sorted_packs_by_execution_time = sorted(packs_objects_to_install.values(),
                                            key=lambda pack: pack.total_expected_execution_time,
                                            reverse=True)
    logging.info(f"Sorted packs by execution times are: "
                 f"{[(pack.name, pack.total_expected_execution_time) for pack in sorted_packs_by_execution_time]}")
    logging.info(f"packs to install from file: {str(packs_to_install_from_file)}")
    for pack in sorted_packs_by_execution_time:
        logging.debug(f"current load on machines is {str(machine_loads)}")
        min_load_machine = min(machine_loads, key=lambda machine: machine_loads[machine])
        machine_assignments[min_load_machine]['packs_to_install'].update({pack.name, *pack.dependencies})
        machine_assignments[min_load_machine]['playbooks_to_run'].update({*pack.test_playbooks_to_run})
        machine_loads[min_load_machine] += pack.total_expected_execution_time
        logging.debug(f"load on machines after assigning: {str(machine_loads)}")
        logging.debug(f"assignment on machines after assigning: {str(machine_assignments)}")

        if pack.name in packs_to_install_from_file:
            packs_to_install_from_file.remove(pack.name)
            logging.debug(f"Removing {pack.name} from packs_to_install list (already collected)")

    # get machine with minimal load
    minimal_machine = min(machine_loads, key=lambda machine: machine_loads[machine])
    machine_assignments[minimal_machine]['packs_to_install'].update(packs_to_install_from_file)

    # turn sets into lists
    final_assignments: dict[str, dict[str, list[str]]] = {
        machine: {
            'packs_to_install': list(machine_dict['packs_to_install'] |
                                     set(ALWAYS_INSTALLED_PACKS_MAPPING[marketplace])),
            'playbooks_to_run': list(machine_dict['playbooks_to_run'])
        } for machine, machine_dict in machine_assignments.items()
    }

    logging.info(f"final assignment: {str(final_assignments)}")
    return final_assignments


def calculate_average_execution_time(bucket_name: str,
                                     server_type: str,
                                     test_playbooks: list,
                                     storage_client: storage.Client,
                                     max_files: int) -> dict[str, float]:
    """
    This function iterates over files in the path, parses the XML files and calculates the average execution
    time for each test playbook.
    Args:
        bucket_name: The name of the GCP bucket.
        server_type: The server type to filter the results for.
        test_playbooks: A list of test playbooks to calculate the average execution time for.
        storage_client: The path to the service account JSON file.
        max_files: Max files to examine.

    Returns:
        A dictionary where keys are test playbooks and values are the average execution time.
    """

    prefix = f"content-playbook-reports/{server_type}/"

    # List files in the bucket path
    blobs = storage_client.list_blobs(bucket_name, prefix=prefix)

    # Filter and sort XML files by the most recent
    xml_files = [blob for blob in blobs if blob.content_type == 'application/xml']
    xml_files.sort(key=lambda x: x.updated, reverse=True)  # Sort by updated time, most recent first
    logging.info(f"Sorted XML files by updated time: {[blob.name for blob in xml_files]}")

    playbook_times: dict = {playbook: [] for playbook in test_playbooks}

    for blob in xml_files[:max_files]:

        try:
            blob_data = blob.download_as_string()
            root = ET.fromstring(blob_data)
        except Exception as e:
            # Handle potential errors during file download or parsing
            logging.info(f"Error processing file {blob.name}: {e}")
            continue

        for testsuite in root.findall("testsuite"):
            playbook_name = testsuite.get("name")
            skipped = testsuite.get("skipped") != '0'

            if playbook_name not in test_playbooks or skipped:
                continue

            logging.debug(f"Processing {playbook_name}")
            if time_str := testsuite.get("time"):
                try:
                    execution_time = float(time_str)
                    playbook_times[playbook_name].append(execution_time)
                except ValueError:
                    # Handle potential errors during time conversion
                    logging.info(f"Error parsing execution time for {playbook_name} in {blob.name}")

    # Calculate average execution time for each playbook
    average_times = {playbook: sum(times) / len(times) if times else DEFAULT_PLAYBOOK_EXECUTION_TIME
                     for playbook, times in playbook_times.items()}
    logging.info(f"Calculated average execution times: {average_times}")
    return average_times


def options_handler() -> argparse.Namespace:
    """
    Returns: options parsed from input arguments.
    """
    parser = argparse.ArgumentParser(description='Utility for splitting packs installation into chosen cloud machines')
    parser.add_argument('--cloud_machines', help='List of chosen cloud machines', nargs='?', default=None)
    parser.add_argument('--server_type', help='Type of server currently running tests on.', required=True)
    parser.add_argument('--playbooks_to_packs', help='Path to the tpb_dependencies_packs.json file that contains '
                                                     'connection between tpb to related packs to install', required=True)

    parser.add_argument("--service_account", help="Path to gcloud service account.")
    parser.add_argument("--packs_to_install_path", help="Path to the content_packs_to_install.txt file.")
    parser.add_argument('--marketplace', type=MarketplaceVersions, help='marketplace version', default='xsoar')
    parser.add_argument('--output_file_name', help='The output file name', default='packs_to_install_by_machine')
    options = parser.parse_args()
    return options


def main():
    install_logging('split_packs_to_machines.log', logger=logging)

    options = options_handler()
    storage_client = storage.Client.from_service_account_json(options.service_account)

    playbooks = load_json(options.playbooks_to_packs)

    machine_list = options.cloud_machines.split(',') if options.cloud_machines else ['xsoar-machine']
    logging.info(f"machines:{machine_list}")

    packs_to_install = fetch_pack_ids_to_install(options.packs_to_install_path)

    logging.info("Calling calculate")
    playbook_times = calculate_average_execution_time(bucket_name=ARTIFACTS_BUCKET,
                                                      server_type=options.server_type,
                                                      test_playbooks=list(playbooks.keys()),
                                                      storage_client=storage_client,
                                                      max_files=MAX_REPORT_FILES)

    logging.info("Calling build pack information")
    packs_objects_to_install = build_pack_information(playbooks, playbook_times)

    logging.info("Calling machine assignment")
    marketplace = MarketplaceVersions(options.marketplace)
    machine_assignments = machine_assignment(packs_objects_to_install, set(machine_list), packs_to_install,
                                             marketplace)

    # output files
    output_file = ARTIFACTS_FOLDER_SERVER_TYPE / f'{options.output_file_name}.json'
    output_file.write_text(json.dumps(machine_assignments))


if __name__ == "__main__":
    main()
