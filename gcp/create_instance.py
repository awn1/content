import argparse
import copy
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List
from uuid import uuid4

import humanize

from gcp import InstanceService

ARTIFACTS_FOLDER_SERVER_TYPE = Path(os.getenv('ARTIFACTS_FOLDER_SERVER_TYPE', '.'))
log_file_path = ARTIFACTS_FOLDER_SERVER_TYPE / 'logs' / 'create_instances.log'
logging.basicConfig(filename=log_file_path, level=logging.INFO)


def options_handler():
    parser = argparse.ArgumentParser(
        description='A script that creates instances for the build')
    parser.add_argument("--env-type",
                        "-t",
                        help="The type for a the environment",
                        choices=[
                            "Nightly",
                            "Bucket-Upload",
                            "Content-Env",
                            "Content-Master",
                            "Server Master",
                            "Server 6.12",
                            "Server 6.11",
                            "Server 6.10",
                            "Server 6.9",
                        ],
                        required=True)
    parser.add_argument("--outfile",
                        help="path for te results file",
                        required=True,
                        default="./env_results.json")
    parser.add_argument("--filter-envs",
                        help="path for the filter env file",
                        required=True,
                        default="./filter_envs.json")
    parser.add_argument('--creds',
                        help='GCP creds',
                        required=True,
                        type=str)
    parser.add_argument('--zone',
                        help='GCP zone',
                        required=True,
                        type=str)
    return parser.parse_args()


def instance_config(env_type: str,
                    instancesconfig_file_path: str = './gcp/instancesconfig.json') -> List[Dict]:
    with open(instancesconfig_file_path, 'r') as inst_config:
        data = json.load(inst_config)
    config = data['config'][env_type]
    global_config = data['globalconfig']
    return [global_config | single_conf for single_conf in config]


def create_instances(inst_config: List[Dict], filtered_envs: Dict[str, bool], sa_file_path: str, zone: str) -> List[Dict]:
    pipeline_id = os.getenv(
        'CI_PIPELINE_ID', '').lower() or f'local-dev-{uuid4()}'

    instance_service = InstanceService(sa_file_path, zone)

    instances_to_create = []
    i = 0
    for instance in inst_config:
        if filtered_envs[instance['role']]:
            name = f"{instance['imagefamily']}-{pipeline_id}-{i}"
            i += 1
            logging.info(f'creating instance #{i} for {instance["role"]} with name {name}')
            instance_to_create = copy.copy(instance)
            instance_to_create['name'] = name
            instances_to_create.append(instance_to_create)
        else:
            logging.info(f'not creating instance for {instance["role"]}')

    if instances_to_create:
        logging.info(f'creating {len(instances_to_create)} instance(s)')
        return instance_service.create_instances(instances_to_create)
    logging.info('no instances to create')
    return []


def main():
    options = options_handler()
    logging.info(f'creating instances for infra type: {options.env_type}')
    inst_config = instance_config(options.env_type)
    start_time = datetime.utcnow()

    with open(options.filter_envs) as json_file:
        filtered_envs = json.load(json_file)

    instances = create_instances(inst_config, filtered_envs, options.creds, options.zone)
    with open(options.outfile, 'w') as env_results_file:
        json.dump(instances, env_results_file, indent=4)

    duration = humanize.naturaldelta(datetime.utcnow() - start_time, minimum_unit="milliseconds")
    logging.info(f"Finished creating instances - took:{duration}")


if __name__ == '__main__':
    main()
