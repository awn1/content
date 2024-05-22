import argparse
import json
import logging
from datetime import datetime
from pathlib import Path

import urllib3
from jinja2 import Environment, FileSystemLoader
from urllib3.exceptions import InsecureRequestWarning

from infra.settings import Settings, XSOARAdminUser
from infra.xsoar_api import XsoarClient, XsiamClient

urllib3.disable_warnings(InsecureRequestWarning)


def create_report(records: list[dict]) -> str:
    current_date = datetime.now().strftime("%Y-%m-%d")
    logging.info(f"Creating report for {current_date}")

    template_path = Path(__file__).parent / "report" / "Files"
    env = Environment(loader=FileSystemLoader(template_path))
    template = env.get_template("ReportTemplate.html")
    logging.info("Successfully loaded template.")
    content = template.render(
        records=records, current_date=current_date)
    logging.info("Successfully rendered report.")
    return content


def options_handler(args=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Script to generate a report for the build machines.')
    parser.add_argument('--xsiam-json', type=str, action="store", required=True, help='Tenant json for xsiam tenants')
    parser.add_argument('--xsoar-ng-json', type=str, action="store", required=True, help='Tenant files for xsoar-ng tenants')
    parser.add_argument('-o', '--output-path', required=True, help='The path to save the report to.')
    options = parser.parse_args(args)

    return options


def generate_records(xsoar_ng_json, xsoar_admin_user: XSOARAdminUser, client_type: type[XsoarClient]):
    records = []
    for key, value in xsoar_ng_json.items():
        # ui_url is in the format of https://<host>/ we need just the host.
        host = value.get("ui_url").replace("https://", "").replace("/", "")
        record = {
            "host": host,
            "ui_url": value.get("ui_url"),
            "machine_name": key,
            "enabled": value.get("enabled"),
            "flow_type": value.get("flow_type"),
            "platform_type": client_type.PLATFORM_TYPE,
            "lcaas_id": "N/A",
            "version": "N/A",
        }
        try:
            client = client_type(xsoar_host=host,
                                 xsoar_user=xsoar_admin_user.username,
                                 xsoar_pass=xsoar_admin_user.password,
                                 tenant_name=key)
            client.login_auth(force_login=True)
            versions = client.get_version_info()
            record |= versions
        except Exception as e:
            logging.error(f"Failed to get data for {key}: {e}")
        records.append(record)
    return records


def main():
    args = options_handler()

    admin_user = Settings.xsoar_admin_user
    xsiam_json = json.loads(Path(args.xsiam_json).read_text())
    xsoar_ng_json = json.loads(Path(args.xsoar_ng_json).read_text())

    # records = [
    #     {
    #         "ui_url": "https://www.google.com/",
    #         "host": "123",
    #         "machine_name": "meir",
    #         "enabled": True,
    #         "flow_type": "upload",
    #         "platform_type": "xsiam",
    #         "lcaas_id": "9995321362587",
    #         "version": "test",
    #     },
    #     {
    #         "ui_url": "https://www.facebook.com/",
    #         "host": "345",
    #         "machine_name": "koby",
    #         "enabled": False,
    #         "flow_type": "build",
    #         "platform_type": "xsoar",
    #         "lcaas_id": "N/A",
    #         "version": "N/A",
    #     },
    # ]
    records_xsoar_ng = generate_records(xsoar_ng_json, admin_user, XsoarClient)
    records_xsiam = generate_records(xsiam_json, admin_user, XsiamClient)
    records = records_xsoar_ng + records_xsiam
    report = create_report(records)

    with open(args.output_path, 'w') as f:
        f.write(report)


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    logging.basicConfig(format="[%(levelname)-8s] [%(name)s] %(message)s")
    main()
