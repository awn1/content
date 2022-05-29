from copy import copy
import logging
from typing import List

import requests
from gcp import Images, Instance, creds, get_image_zone
import argparse
from time import sleep


def options_handler():
    parser = argparse.ArgumentParser(
        description='A script that creates instances for the build')
    parser.add_argument('-v',
                        '--server-version',
                        help='The filter string with which server version should be used',
                        default=1,
                        type=str)
    parser.add_argument('-c', '--instance-count',
                        help='The number of instances to create',
                        required=True,
                        type=int)
    parser.add_argument('-p', '--name-prefix',
                        help='The number of instances to create',
                        required=True,
                        type=str)
    parser.add_argument('--creds',
                        help='GCP creds',
                        required=True,
                        type=str)
    options = parser.parse_args()
    return options


def main():
    options = options_handler()
    creds(options.creds)

    logging.info('searching latest image for version {options.server_version}')
    latest_image = Images.get_latest_image(options.server_version)
    logging.info('found image {latest_image.name}')

    logging.info('creating {options.instance_count} instances')
    for i in range(options.instance_count):
        instance_name = f'{options.name_prefix}-{i}'
        Instance.create(instance_name, latest_image)


if __name__ == '__main__':
    main()
