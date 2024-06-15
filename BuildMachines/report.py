import argparse
import json
import logging
import os
from datetime import datetime
from pathlib import Path

import urllib3
from jinja2 import Environment, FileSystemLoader
from urllib3.exceptions import InsecureRequestWarning

from infra.settings import Settings, XSOARAdminUser
from infra.xsoar_api import XsoarClient, XsiamClient

urllib3.disable_warnings(InsecureRequestWarning)

COLUMNS = [
    {'data': '', 'exportable': False, 'visible': True, 'add_class': False, 'filterable': False, 'className': 'dt-control',
     'orderable': 'false', 'key': '', 'defaultContent': ''},
    {'data': 'Host', 'exportable': True, 'visible': True, 'add_class': False, 'filterable': False, 'key': 'host'},
    {'data': 'Machine Name', 'exportable': True, 'visible': True, 'add_class': False, 'filterable': False, 'key': 'machine_name'},
    {'data': 'Enabled', 'exportable': True, 'visible': True, 'add_class': True, 'filterable': True, 'key': 'enabled'},
    {'data': 'Flow Type', 'exportable': True, 'visible': True, 'add_class': True, 'filterable': True, 'key': 'flow_type'},
    {'data': 'Platform Type', 'exportable': True, 'visible': True, 'add_class': True, 'filterable': True, 'key': 'platform_type'},
    {'data': 'Server Version', 'exportable': True, 'visible': True, 'add_class': True, 'filterable': True, 'key': 'version'},
    {'data': 'LCAAS ID', 'exportable': True, 'visible': True, 'add_class': True, 'filterable': False, 'key': 'lcaas_id'},
    {'data': 'Agent Host Name', 'exportable': True, 'visible': False, 'add_class': True, 'filterable': False,
     'key': 'agent_host_name'},
    {'data': 'Agent IP', 'exportable': True, 'visible': False, 'add_class': True, 'filterable': False, 'key': 'agent_host_ip'},
]

ARTIFACTS_FOLDER = os.environ["ARTIFACTS_FOLDER"]
GITLAB_ARTIFACTS_URL = os.environ["GITLAB_ARTIFACTS_URL"]
CI_JOB_ID = os.environ["CI_JOB_ID"]
XDR_PERMISSIONS_DEV = os.environ["XDR_PERMISSIONS_DEV"]
XDR_UPGRADE_CHANNEL_DEV = os.environ["XDR_UPGRADE_CHANNEL_DEV"]
PERMISSION_ROLE = os.environ.get("PERMISSION_ROLE", "cortex-operator-data-access")


def create_report(current_date: str, records: list[dict], columns, columns_filterable, managers) -> str:

    template_path = Path(__file__).parent / "report" / "Files"
    env = Environment(loader=FileSystemLoader(template_path))
    template = env.get_template("ReportTemplate.html")
    logging.info("Successfully loaded template.")
    report_title = f"Build Machines Report - {current_date}"
    content = template.render(records=records, report_title=report_title,
                              columns_json=json.dumps(columns), columns=columns,
                              columns_filterable=columns_filterable, managers=managers,
                              xdr_permissions_dev=XDR_PERMISSIONS_DEV,
                              xdr_upgrade_channel_dev=XDR_UPGRADE_CHANNEL_DEV,
                              permission_role=PERMISSION_ROLE)
    logging.info("Successfully rendered report.")
    return content


def options_handler(args=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Script to generate a report for the build machines.')
    parser.add_argument('--xsiam-json', type=str, action="store", required=True, help='Tenant json for xsiam tenants')
    parser.add_argument('--xsoar-ng-json', type=str, action="store", required=True, help='Tenant files for xsoar-ng tenants')
    parser.add_argument('-o', '--output-path', required=True, help='The path to save the report to.')
    parser.add_argument('-n', '--name-mapping_path', help='Path to name mapping file.', required=False)
    parser.add_argument('-t', '--test-data', help="Use test data and don't connect to the servers.", required=False)
    options = parser.parse_args(args)

    return options


def generate_html_link(text, url):
    return f'<a href="{url}" target="_blank">{text}</a>'


def generate_cell(display, sort=None):
    return {
        "display": display,
        "sort": sort if sort is not None else display,
    }


def generate_records(xsoar_ng_json, xsoar_admin_user: XSOARAdminUser, client_type: type[XsoarClient]):
    records = []
    for key, value in xsoar_ng_json.items():
        # ui_url is in the format of https://<host>/ we need just the host.
        host = value.get("ui_url").replace("https://", "").replace("/", "")
        record = {
            "host": generate_cell(generate_html_link(host, value.get("ui_url")), value.get("ui_url")),
            "ui_url": generate_cell(value.get("ui_url")),
            "machine_name": generate_cell(key),
            "enabled": generate_cell(value.get("enabled")),
            "flow_type": generate_cell(value.get("flow_type")),
            "platform_type": generate_cell(client_type.PLATFORM_TYPE),
            "lcaas_id": generate_cell("N/A", ""),
            "version": generate_cell("N/A", ""),
            "agent_host_name": generate_cell(value.get("agent_host_name", "N/A"), value.get("agent_host_name", "")),
            "agent_host_ip": generate_cell(value.get("agent_host_ip", "N/A"), value.get("agent_host_ip", "")),
        }
        try:
            client = client_type(xsoar_host=host,
                                 xsoar_user=xsoar_admin_user.username,
                                 xsoar_pass=xsoar_admin_user.password,
                                 tenant_name=key)
            client.login_auth(force_login=True)
            versions = client.get_version_info()
            record |= {key: generate_cell(value) for key, value in versions.items()}
        except Exception as e:
            logging.error(f"Failed to get data for {key}: {e}")
        records.append(record)
    return records


def main():
    args = options_handler()
    output_path = Path(args.output_path)
    if args.test_data:
        records = json.loads(Path(args.test_data).read_text())
    else:
        admin_user = Settings.xsoar_admin_user
        xsiam_json = json.loads(Path(args.xsiam_json).read_text())
        xsoar_ng_json = json.loads(Path(args.xsoar_ng_json).read_text())
        records_xsoar_ng = generate_records(xsoar_ng_json, admin_user, XsoarClient)
        records_xsiam = generate_records(xsiam_json, admin_user, XsiamClient)
        records = records_xsoar_ng + records_xsiam

    managers = []
    if args.name_mapping_path:
        with open(args.name_mapping_path) as f:
            name_mapping = json.load(f)
            managers.extend(name_mapping.get("managers", []))
    static_columns = {column["key"] for column in COLUMNS if column["key"]}
    dynamic_columns = list({key for record in records for key in record.keys() if key not in static_columns})
    COLUMNS.extend([
        {"data": key, 'exportable': False, "visible": False, 'filterable': False, "key": key} for key in dynamic_columns])
    current_date = datetime.now().strftime("%Y-%m-%d")
    logging.info(f"Creating report for {current_date}")
    columns_filterable = [i for i, c in enumerate(COLUMNS) if c["filterable"]]
    # Save the records to a json file for future use and debugging.
    with open(output_path / "records.json", "w") as f:
        json.dump(records, f, indent=4)

    report = create_report(current_date, records, COLUMNS, columns_filterable, managers)
    report_file_name = f"Report_{current_date}.html"
    with open(output_path / report_file_name, 'w') as f:
        f.write(report)

    with open(output_path / "slack_msg.txt", "w") as f:
        f.write(f"Build machines report was created and can be found <{GITLAB_ARTIFACTS_URL}/{CI_JOB_ID}/"
                f"artifacts/{ARTIFACTS_FOLDER}/{report_file_name}|here>")


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    logging.basicConfig(format="[%(levelname)-8s] [%(name)s] %(message)s")
    main()
