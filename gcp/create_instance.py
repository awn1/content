import json
import logging
import os
from typing import Dict
from uuid import uuid4

from gcp import InstanceService
import argparse
from time import sleep


def options_handler():
    parser = argparse.ArgumentParser(
        description='A script that creates instances for the build')
    parser.add_argument("--env-type",
                        "-t",
                        help="The type for a the environment",
                        choices=[
                            "Nightly",
                            "Content-Env",
                            "Content-Master",
                            "Server Master",
                            "Server 6.8",
                            "Server 6.6",
                            "Server 6.5",
                            "Server 6.2",
                            "Bucket-Upload",
                        ],
                        required=True)
    parser.add_argument("--outfile",
                        help="path for te results file",
                        required=True,
                        default="./env_results.json")
    parser.add_argument('--creds',
                        help='GCP creds',
                        required=True,
                        type=str)
    parser.add_argument('--zone',
                        help='GCP zone',
                        required=True,
                        type=str)
    return parser.parse_args()


def instance_config(env_type: str, instancesconfig_file_path: str = './gcp/instancesconfig.json') -> Dict[str, str]:
    with open(instancesconfig_file_path, 'r') as inst_config:
        data = json.load(inst_config)
    config = data['config'][env_type]
    global_config = data['globalconfig']
    return [singel_conf | global_config for singel_conf in config]


def create_instances(inst_config, sa_file_path, zone):
    pipline_id = os.getenv(
        'CI_PIPELINE_ID', '').lower() or f'local-dev-{uuid4()}'

    instance_service = InstanceService(sa_file_path, zone)

    for i, instance in enumerate(inst_config):
        version = instance['imagefamily']
        instance['name'] = f'{version}-{pipline_id}-{i}'

    return instance_service.create_instances(inst_config)


def main():
    options = options_handler()
    logging.info('creating {options.instance_count} instances')
    inst_config = instance_config(options.env_type)
    instances = create_instances(inst_config, options.creds, options.zone)
    with open(options.outfile, 'w') as env_results_file:
        json.dump(instances, env_results_file, indent=4)


if __name__ == '__main__':
    main()
