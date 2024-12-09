import argparse
import json
import os
import re
import sys
from datetime import datetime

import requests
from dateparser import parse


def get_mitigated_cves(mitigated_path: str) -> dict:
    with open(mitigated_path) as file:
        return json.load(file)


def image_key_from_name(name: str) -> str:
    """
    Will return the image name from a full tag. Examples
    devdemisto/python3-deb:3.10.11.12345 -> python3-deb
    demisto/chromium:1.0.0.12345 -> chromium
    """
    return re.search(r".*/(.*?):.*", name).group(1)  # type: ignore[union-attr]


def vulnerability_to_description(v):
    return f'{v.get("id")} - {v.get("severity")} - {v.get("description")}'


def get_latest_prod_report(name):
    url = f'{os.getenv("PRISMA_CONSOLE_URL_PROD")}/api/{os.getenv("PRISMA_CONSOLE_API_VERSION")}'
    tenant = os.getenv("PRISMA_CONSOLE_TENANT_PROD")
    response = requests.get(
        f"{url}/registry?project={tenant}&repository=demisto/{name}",
        auth=(os.getenv("PRISMA_CONSOLE_USER_PROD"), os.getenv("PRISMA_CONSOLE_PASS_PROD")),  # type: ignore[arg-type]
    )
    response.raise_for_status()
    all_scans = response.json()
    if not all_scans:
        return {}
    return max(all_scans, key=lambda x: int(x["tags"][0]["tag"].split(".")[-1]))


def parse_report(report: dict, mitigated_cves: dict, must_mitigate_severity: list[str], compare_with_latest) -> dict:
    """
    Takes a dict of a given twistlock report, filters for the relevant results, and returns it in a format that
    can be used to determine if the job should fail, and is able to be printed
    """
    if not report["results"]:
        print("Report does not contain results: {report}. Exiting with error")
        sys.exit(1)
    name = image_key_from_name(report["results"][0]["name"])
    mitigated_cves_for_docker = {
        k: v
        for k, v in (mitigated_cves.get(name, {}) | mitigated_cves.get("*")).items()
        if parse(v.get("until", "2099-12-31")) > datetime.now()  # type: ignore[operator]
    }

    print(f"DEBUG: docker {name} has {len(mitigated_cves_for_docker)} total mitigated cves")

    in_latest_cves = []
    must_mitigate_vulnerabilities = []

    mitigated_counter = 0

    vulnerabilities_filtered_by_severity = [
        v for v in report["results"][0].get("vulnerabilities", []) if v.get("severity") in must_mitigate_severity
    ]
    cves_in_latest = set()
    if compare_with_latest:
        latest_report = get_latest_prod_report(name)
        if latest_report:
            print(f"Comparing to latest report of tag {latest_report['tags'][0]['tag']}")
        cves_in_latest = {vuln["cve"] for vuln in latest_report.get("vulnerabilities") or []}

    for vulnerability in vulnerabilities_filtered_by_severity:
        if vulnerability.get("id") in mitigated_cves_for_docker:
            print(
                f'{vulnerability.get("id")} is mitigated for reason: '
                f'{mitigated_cves_for_docker[vulnerability["id"]]["description"]}'
            )
            mitigated_counter += 1
        elif vulnerability.get("id") in cves_in_latest:
            in_latest_cves.append(vulnerability_to_description(vulnerability))
        else:
            must_mitigate_vulnerabilities.append(vulnerability_to_description(vulnerability))

    print(
        f"DEBUG: There are {len(set(mitigated_cves_for_docker.keys())) - mitigated_counter} cves in the mitigated-cves "
        f"file that were not reported for image {name}"
    )

    return {
        "name": name,
        "outstanding_vulnerabilities": must_mitigate_vulnerabilities,
        "number_mitigated": mitigated_counter,
        "in_latest_cves": in_latest_cves,
        "number_outstanding": len(must_mitigate_vulnerabilities),
    }


def get_reports_from_folder(
    folder_path: str, mitigated_cves: dict, must_mitigate_severity: list[str], compare_with_latest: bool
) -> list[dict]:
    reports = []
    for filename in os.listdir(folder_path):
        file_path = os.path.join(folder_path, filename)
        print(f"Reading {file_path}")
        with open(file_path) as file:
            try:
                reports.append(json.load(file))
            except json.JSONDecodeError as e:
                print(f"Error decoding JSON file {filename}: {e}")
                raise e
    print(f"DEBUG: Parsing {len(reports)} reports")
    return [parse_report(report, mitigated_cves, must_mitigate_severity, compare_with_latest) for report in reports]


def output_report_results(parsed_reports: list[dict]):
    print("\n===================== 🥁 Results 🥁 =====================\n")
    total_outstanding = sum([r["number_outstanding"] for r in parsed_reports])
    exit_code = 0
    for report in parsed_reports:
        if report["outstanding_vulnerabilities"] or report["in_latest_cves"]:
            print("_________________")
            print(
                f'Results for image {report["name"]}, number of outstanding CVEs: {report["number_outstanding"]}. '
                f'Number mitigated: {report["number_mitigated"]}'
            )
            if report["outstanding_vulnerabilities"]:
                print("\n These cves must be solved before merge.")
                for cve in report["outstanding_vulnerabilities"]:
                    exit_code = 1
                    print(f"\n{cve}")
            if report["in_latest_cves"]:
                print("\nWARNING: CVEs that must be mitigated and are in the latest production image")
                for cve in report["in_latest_cves"]:
                    print(f"\n{cve}")
    print(
        f"_________________\nThere are a total of {total_outstanding} Outstanding cves that need to be mitigated. "
        "See the summary above.\nFor more information about the cves see the Scan Images job."
    )
    if not exit_code:
        print("No outstanding cves were found 🙏. ")
    print("\n================================================================\n")
    sys.exit(exit_code)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-s",
        "--relevant-severity-levels",
        help="Comma seperated list of relevant severity levels to fail for if unmitigated. Default is critical and high",
        default="critical,high",
    )
    parser.add_argument("--reports-folder", help="Path to the folder containing reports")
    parser.add_argument("-mcf", "--mitigated-cves-file", help="Path to the mitigated cves file")
    parser.add_argument(
        "--compare-with-latest",
        help="Whether only to fail if the latest prod image doesnt include the same cves",
        action="store_true",
    )

    args = parser.parse_args()
    folder_path = args.reports_folder
    must_mitigate_severity = args.relevant_severity_levels.split(",")
    print(f"relevant security levels: {must_mitigate_severity}")
    mitigated_cves = get_mitigated_cves(args.mitigated_cves_file)
    parsed_reports = get_reports_from_folder(folder_path, mitigated_cves, must_mitigate_severity, args.compare_with_latest)

    output_report_results(parsed_reports)


if __name__ in ("__main__", "__builtin__", "builtins"):
    main()
