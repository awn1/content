import json
import logging
import os
from pathlib import Path
from typing import Dict
from uuid import uuid4

from gcp import Images, Instance, creds
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
    return parser.parse_args()


def instance_config(env_type: str, instancesconfig_file_path: str = './gcp/instancesconfig.json') -> Dict[str, str]:
    with open(instancesconfig_file_path, 'r') as inst_config:
        try:
            return json.load(inst_config)[env_type]
        except FileNotFoundError as error:
            logging.error(
                f'could not find instance config file in {Path(instancesconfig_file_path).absolute()}')
            raise error from None
        except json.decoder.JSONDecodeError as error:
            logging.error(
                f'failed to parse the instance config file in {Path(instancesconfig_file_path).absolute()}')
            raise error from None
        except KeyError as error:
            logging.error(
                f'env type {env_type} dosnt exist')
            raise error from None


def create_instances(inst_config):
    pipline_id = os.getenv(
        'CI_PIPELINE_ID', '').lower() or f'local-dev-{uuid4()}'
    instances = []

    for i, instance in enumerate(inst_config):
        version = instance['imagefilter']
        role = instance['role']
        instance_name = f'{version}-{pipline_id}-{i}'
        latest_image = Images.get_latest_image(instance['imagefilter'])
        logging.info(
            f"creating instance '{instance_name}' for role '{role}' using image '{latest_image.name}'")
        Instance.create(instance_name, latest_image)
        instances.append({
            'InstanceName': instance_name,
            'Key': 'oregon-ci',
            'Role': role,
            'SSHuser': 'gcp-user',
            'ImageName': latest_image.name,
            'TunnelPort': 443,
            'AvailabilityZone': Images.get_image_zone(latest_image)
        })

    for instance in instances:
        for _ in range(5):
            ip = Instance.describe(
                instance['InstanceName'], instance['AvailabilityZone']).network_interfaces[0].network_i_p
            if ip:
                instance['InstanceDNS'] = ip
                break
            sleep(5)
    return instances


def main():
    options = options_handler()
    creds(options.creds)
    logging.info('creating {options.instance_count} instances')
    inst_config = instance_config(options.env_type)
    instances = create_instances(inst_config)
    with open(options.outfile, 'w') as env_results_file:
        json.dump(instances, env_results_file, indent=4)


if __name__ == '__main__':
    main()
