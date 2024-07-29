import argparse

import json5

from Tests.configure_and_test_integration_instances import CloudBuild


def run(options: argparse.Namespace):
    cloud_machines: list[str] = options.cloud_machine_ids.split(",") if options.cloud_machine_ids else []
    cloud_machines_details: dict[str, dict] = {}
    for cloud_machine in cloud_machines:
        cloud_machine_details = CloudBuild.get_cloud_machine_from_gsm(cloud_machine)
        cloud_machines_details[cloud_machine] = cloud_machine_details

    print(json5.dumps(cloud_machines_details, quote_keys=True))


def options_handler(args=None):
    parser = argparse.ArgumentParser(description="Get cloud machine details from GSM.")
    parser.add_argument("--cloud_machine_ids", help="Cloud machine ids to use.")
    options = parser.parse_args(args)
    return options


if __name__ == "__main__":
    options = options_handler()
    run(options)
