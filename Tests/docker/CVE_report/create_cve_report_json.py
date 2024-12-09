import argparse
import csv
import functools
import io
import json
import os
import re
import subprocess
import sys
from collections import defaultdict, namedtuple
from collections.abc import Iterable
from datetime import datetime, timedelta

import requests
from dateparser import parse

SEVERITY_ORDER = ["critical", "high", "medium", "moderate", "low"]
SUPPORT_ORDER = ["xsoar", "partner", "community"]
VERIFY = True
from demisto_sdk.commands.common.hook_validations.docker import DockerImageValidator
from demisto_sdk.commands.content_graph.interface.neo4j.neo4j_graph import (
    Neo4jContentGraphInterface as ContentGraphInterface,
)
from more_itertools import bucket
from neo4j import Transaction


def get_console_link(image):
    return f'{os.getenv("PRISMA_CONSOLE_URL")}/#!/monitor/vulnerabilities/images/registries?projectId={os.getenv("PRISMA_CONSOLE_TENANT")}&search={image}'


MITIGATED_CVES = None
MODIFIED_CVE_CHANGES = None
GraphEntry = namedtuple("GraphEntry", ["path", "image", "id", "support_level"])


class Entry:
    """
    Represents one row in the twistlock report.
    Each row is a cve on a docker image.
    An image with 25 cves will have 25 entries.
    One cve on two images will be two different entries.
    """

    def to_row(self):
        return (
            self.repository,
            self.cve_id,
            self.Fix_Status,
            self.Source_Package,
            self.Packages,
            self.Vulnerability_Link,
            self.Description,
        )

    def __init__(self, *args):
        self.registry = args[0]
        self.repository = args[1]
        self.tag = args[2]
        self.id = args[3]
        self.distro = args[4]
        self.hostname = args[5]
        self.layer = args[6]
        self.cve_id = args[7][0] if len(args[7]) == 1 else args[7]
        self.compliance_id = args[8]
        self.result = args[9]
        self.type = args[10]
        self.severity = args[11]
        self.packages = args[12]
        self.source_package = args[13]
        self.package_version = args[14]
        self.package_license = args[15]
        self.CVS_score = args[16]
        self.fix_status = args[17]
        self.risk_factors = args[18]
        self.vulnerability_tags = args[19]
        self.description = args[20]
        self.cause = args[21]
        self.custom_labels = args[22]
        self.published = args[23]
        self.namespace = args[24]
        self.image_id = args[25]
        self.vulnerability_link = args[26]
        self.package_path = args[27]
        self.purl = args[28]
        self.console_link = get_console_link(f"{self.repository}:{self.tag}")


def query_used_dockers_content(tx: Transaction) -> list[tuple[str, str, str]]:
    """
    queries the content graph for content items, their docker images, and their paths
    """
    return list(
        tx.run(
            """
    MATCH (pack:Pack) <-[:IN_PACK] - (iss)
    WHERE iss.content_type IN ["Integration", "Script"]
    AND NOT iss.deprecated
    AND NOT iss.type = 'javascript'
    AND NOT pack.object_id = 'ApiModules'
    AND NOT iss.object_id = 'CommonServerPython'
    AND iss.docker_image IS NOT NULL
    AND NOT pack.hidden
    Return DISTINCT iss.object_id, iss.docker_image, iss.path, pack.support
    """
        )
    )


@functools.lru_cache
def get_all_content_images_to_id() -> list[GraphEntry]:
    """Return all used content items, their images, and their paths

    Returns:
        list[GraphEntry]: each dict has id, image, path attributes
    """
    with ContentGraphInterface() as graph:
        with graph.driver.session() as session:
            return [
                GraphEntry(id=row[0], image=row[1], path=row[2], support_level=row[3])
                for row in session.execute_read(query_used_dockers_content)
            ]


def get_image_names(entries: list[GraphEntry]) -> set[str]:
    """

    Args:
        entries list[GraphEntry]: results from the graph

    Returns:
        set[str]: images in demisto/imagename format without the tag
    """
    distinct_images = {e.image for e in entries}
    return {re.search("(demisto/.*):", image).group(1) for image in distinct_images if isinstance(image, str)}


def index_or_default(l: list, element, default=-1):
    try:
        return l.index(element)
    except ValueError:
        return default


def get_twistlock_results(provided_file_path: str) -> list[Entry]:
    """Will fetch the registry scan results from the twistlock api.

    Args:
        provided_file_path (str): for debugging. To work with a previously downloaded result payloaded

    Returns:
        list[Entry]: List of entries from the twistlock api.
    """
    if provided_file_path:
        with open(provided_file_path) as f:
            response_text = f.read()
    else:
        url = f'{os.getenv("PRISMA_CONSOLE_URL")}/api/{os.getenv("PRISMA_CONSOLE_API_VERSION")}'
        tenant = os.getenv("PRISMA_CONSOLE_TENANT")
        response = requests.get(
            f"{url}/registry/download?project={tenant}",
            auth=(os.getenv("PRISMA_CONSOLE_USER"), os.getenv("PRISMA_CONSOLE_PASS")),
            verify=VERIFY,
        )
        response.raise_for_status()
        response_text = response.text
    entries = []
    try:
        for row in csv.reader(io.StringIO(response_text)):
            entries.append(Entry(*row))
    except IndexError:
        print(
            f"Unable to read results from prisma. Response text: \n{response_text}\nSee if you have connection to the console. "
        )
        sys.exit(1)
    return entries


def find_highest_severity(image, filtered_content_entries: list[Entry], tag=None):
    severities = {e.severity.lower() for e in filtered_content_entries if e.repository == image and (not tag or e.tag == tag)}
    sorted_severities = sorted(list(severities), key=lambda x: index_or_default(SEVERITY_ORDER, x, len(SEVERITY_ORDER)))
    return sorted_severities[0] if sorted_severities else "None"


def find_highest_support(image, filtered_content_entries: list[Entry], tag=None):
    severities = {e.severity.lower() for e in filtered_content_entries if e.repository == image and (not tag or e.tag == tag)}
    sorted_severities = sorted(list(severities), key=lambda x: index_or_default(SEVERITY_ORDER, x, len(SEVERITY_ORDER)))
    return sorted_severities[0] if sorted_severities else "None"


def find_latest_tag_used(repository, graph_entries: list[GraphEntry]):
    def tag_last(tag):
        return tag.split(".")[-1]

    return max([ge.image.split(":")[1] for ge in graph_entries if ge.image.split(":")[0] == repository], key=tag_last)


def get_content_report(
    filtered_content_entries: list[Entry], graph_entries: list[GraphEntry], outdated_date, content_dir: str, relevant_levels
) -> list[dict]:
    """Builds the report for status in the content repo
    will return entries that are either outdated/has cves/ using deprecated images

    Args:
        filtered_content_entries (list[Entry]): filtered entries on content images
        graph_entries (list[GraphEntry]): image, tag, path of content items
        problematic_candidates (list[Entry]): relevant entries only latest
        content_dir (str): path to content repo

    Returns:
        [type]: the report for content info
    """
    problematic_candidates = problematic_prod_candidates(filtered_content_entries)
    repos_with_issues_in_latest = {entry.repository for entry in problematic_candidates if entry.severity in relevant_levels}

    repo_to_entries = defaultdict(dict)
    for entry in filtered_content_entries:
        repo_to_entries[f"{entry.repository}:{entry.tag}"][entry.severity] = 1 + repo_to_entries[
            f"{entry.repository}:{entry.tag}"
        ].get(entry.severity, 0)

    content_info = dict()

    for graph_entry in graph_entries:
        repository, tag = graph_entry.image.split(":")
        latest_tag = get_latest_tag(repository)

        repo_info = content_info.get(
            repository,
            {
                "num_content_items_with_cves": 0,
                "num_content_items_with_critical_cves": 0,
                "outdated_item_info": [],
                "cve_item_info": [],
                "highest_severity": find_highest_severity(repository, filtered_content_entries),
                "highest_support": "",
                "latest_tag": latest_tag,
                "latest_has_cve": repository in repos_with_issues_in_latest,
                "latest_used_content": find_latest_tag_used(repository, graph_entries),
                "deprecated": image_is_deprecated(repository),
            },
        )

        content_info[repository] = repo_info
        if index_or_default(SUPPORT_ORDER, graph_entry.support_level, 4) < index_or_default(
            SUPPORT_ORDER, repo_info.get("highest_support"), 4
        ):
            repo_info["highest_support"] = graph_entry.support_level

        outdated_item_info = repo_info.get("outdated_item_info")
        cve_item_info = repo_info.get("cve_item_info")

        path_to_check = "/".join(graph_entry.path.split("/")[:-1])  # parent folder for file

        last_updated = None if not outdated_date else get_last_updated(path_to_check, content_dir)
        if sev_dict := repo_to_entries.get(graph_entry.image, {}):
            if sev_dict.keys() & relevant_levels:
                repo_info["num_content_items_with_cves"] += 1
            if sev_dict.get("critical"):
                repo_info["num_content_items_with_critical_cves"] += 1
            cve_item_info.append(
                {
                    "id": graph_entry.id,
                    "num_cves": sum(sev_dict.values()),
                    "highest_severity": find_highest_severity(repository, filtered_content_entries, tag),
                    "tag": tag,
                    "console_link": get_console_link(graph_entry.image),
                    "support_level": graph_entry.support_level,
                    "last_updated": str(last_updated),
                }
            )
        if image_is_deprecated(repository) or tag != latest_tag and outdated_date and last_updated < outdated_date:
            repo_info["outdated"] = True
            outdated_item_info.append(
                {
                    "id": graph_entry.id,
                    "tag": tag,
                    "console_link": get_console_link(graph_entry.image),
                    "support_level": graph_entry.support_level,
                    "last_updated": str(last_updated),
                }
            )

    return {
        key: value
        for key, value in content_info.items()
        if value.get("outdated") or value.get("num_content_items_with_cves") or value.get("deprecated")
    }


DEPRECATED_IMAGES = set()


def image_is_deprecated(image: str) -> bool:
    """checks if an image is deprecated according to deprecated_images in dockerfiles

    Args:
        image (str): image to check if is deprecated

    Returns:
        bool: true if the image is deprecated
    """
    global DEPRECATED_IMAGES
    if not DEPRECATED_IMAGES:
        DEPRECATED_IMAGES = {
            item.get("image_name")
            for item in requests.get(
                "https://raw.githubusercontent.com/demisto/dockerfiles/master/docker/deprecated_images.json", verify=VERIFY
            ).json()
        }
    return image in DEPRECATED_IMAGES


@functools.lru_cache
def get_last_updated(path, content_dir):
    """returned the outdated date for content in the event it is outdated

    Args:
        path ([type]): path to the item from the content repo
        content_dir ([type]): location of the content repo

    Returns:
        [type]: date if the item is outdated. None if it isnt
    """
    command = ["git", "log", "-1", "--pretty=format:%aI", "--", path]
    raw_time = subprocess.check_output(command, text=True, cwd=content_dir)
    print(f"{path} was updated on {raw_time}")
    return datetime.strptime(raw_time, "%Y-%m-%dT%H:%M:%S%z").date()


@functools.lru_cache(maxsize=512)
def get_latest_tag(repository) -> str:
    """
    Will return the latest tag for a given repository
        repository (str): the reposiroty to get latest for

    Returns:
        str: the latest tag for the repository
    """
    tag = DockerImageValidator.get_docker_image_latest_tag_request(repository)
    print(f"recieved latest tag for {repository} - {tag}")
    return tag


def problematic_prod_candidates(entries: Iterable[Entry]) -> list[Entry]:
    """Filters the entries to only include ones with the latest tag and image isnt deprecated

    Args:
        entries (Iterable[Entry]): The raw list of entries

    Returns:
        list[Entry]: [description]
    """
    return [
        entry for entry in entries if get_latest_tag(entry.repository) == entry.tag and not image_is_deprecated(entry.repository)
    ]


def is_mitigated(entry: Entry, mitigated_cve_path: str) -> bool:
    """Returns true if an entry is considered mitigated based on the mitigated cves file

    Args:
        entry (Entry): entry to check if is deprecated
        mitigated_cve_path (str): Path to the mitigated_cves file

    Returns:
        bool: Whether the entry is considered mitigated
    """
    global MITIGATED_CVES
    if not mitigated_cve_path:
        return False
    if MITIGATED_CVES is None:
        with open(mitigated_cve_path) as f:
            MITIGATED_CVES = json.load(f)
            print(f"loaded mitigated_cves file with {len(MITIGATED_CVES)} entries")
    mitigated_cves_for_image = {
        k: v.get("description")
        for k, v in (MITIGATED_CVES.get(entry.repository.split("/")[1], {}) | MITIGATED_CVES.get("*", {})).items()
        if parse(v.get("until", "2099-12-31")) > datetime.now()
    }
    return entry.cve_id in mitigated_cves_for_image


def filter_content_entries(
    twistlock_results: Iterable[Entry],
    used_images: set[str],
    mitigated_cve_path: str,
) -> list[Entry]:
    """Filter out the entries that are not relevant for the content repo.
    By severity, use, and mitigation status.

    Args:
        twistlock_results (Iterable[Entry]): The raw entries returned by twistlock
        used_images (set[str]): set of images in use by content
        mitigated_cve_path (str): path to mitigated_cves.json

    Returns:
        list[Entry]: A list of entries that should be used in the report
    """

    ret = []
    if not twistlock_results:
        return []
    for entry in twistlock_results[1:]:
        if (
            not is_mitigated(entry, mitigated_cve_path)
            and entry.repository in used_images
            and entry.cve_id  # compliance lines dont have a cve_id, ignore them
        ):
            ret.append(entry)
    return ret


def save_json_file(results, output_path):
    class MyEncoder(json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, Entry):
                return obj.__dict__
            return super().default(obj)

    with open(output_path, "w") as f:
        f.write(json.dumps(results, cls=MyEncoder))
    print(f"Saved json file {output_path}")


def get_cli_args():
    arg_parser = argparse.ArgumentParser(
        description="Will generate a report of outdated docker images in content and cves in latest images in dockerfiles."
    )
    arg_parser.add_argument(
        "--verify", help="Whether to verify the ssl certificates", action=argparse.BooleanOptionalAction, default=True
    )
    arg_parser.add_argument(
        "--relevant_security_levels",
        "-s",
        required=False,
        help="Comma seperated statuses to include in the report. Eg, 'critical,high'. Possible options: critical,high,medium,low",
        default="critical",
    )
    arg_parser.add_argument("--output_path", help="Renders a json file output", default="cve_report.json")
    arg_parser.add_argument(
        "--days_ago_alert",
        help="If a cve was published within this number of days, it will be listed in the report.",
        default=2,
        type=int,
    )
    arg_parser.add_argument(
        "--twistlock_raw_input",
        "-ti",
        required=False,
        help="A twistlock report to parse. Will fetch from API if not provided. Mostly for debugging.",
    )
    arg_parser.add_argument(
        "--mitigated_cves_file",
        "-mcf",
        required=False,
        help="The path to the mitigated_cves file",
        default="./mitigated-cves.json",
    )
    arg_parser.add_argument(
        "--excluded_repos",
        "-er",
        required=False,
        help="Repos explicitly not to include in the report",
        default="",
    )

    arg_parser.add_argument(
        "--content_dir",
        required=False,
        help="Path to the content repository",
        default="./content",
    )
    arg_parser.add_argument(
        "--days_to_consider_outdated",
        required=False,
        help="How much time to give before considering a content date outdated",
        default=365,
        type=int,
    )
    return arg_parser.parse_args()


def cve_was_modified(cve_id, days_ago):
    global MODIFIED_CVE_CHANGES
    if MODIFIED_CVE_CHANGES is None:
        try:
            days_ago_time = datetime.now() - timedelta(days=days_ago)
            from_time = days_ago_time.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
            to_time = datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]

            resp = requests.get(
                url="https://services.nvd.nist.gov/rest/json/cvehistory/2.0",
                params={"changeStartDate": from_time, "changeEndDate": to_time},
            )
            resp_json = resp.json()
            print(f"cve modiefied {resp.status_code=}")
            print(
                f'Total results from modified api {resp_json["totalResults"]}'
            )  # note, page size is 5000 and we only take first page.
            content = [e["change"] for e in resp_json["cveChanges"]]
            MODIFIED_CVE_CHANGES = {}
            for change in content:
                for details in change.get("details", []):
                    if "cvss" in details.get("type"):
                        MODIFIED_CVE_CHANGES[change["cveId"].lower()] = "Score was updated."
                        break
        except Exception as e:
            print(f"received error from changes api {e}")
            MODIFIED_CVE_CHANGES = {}
    return MODIFIED_CVE_CHANGES.get(cve_id.lower(), "")


def cve_updated_info(entry: Entry, days_ago):
    if entry.published and datetime.fromisoformat(entry.published) > (datetime.now() - timedelta(days=days_ago)):
        return "Newly published cve"
    return cve_was_modified(entry.cve_id, days_ago)


def get_new_cve_data_for_entries(
    filtered_content_entries: list[Entry], graph_entries: list[GraphEntry], days_ago, relevant_levels
):
    """Returns information for new cves used in our repo.

    Args:
        filtered_content_entries (list[Entry]): the filtered entries from twistlock
        graph_entries ([type]): image, tag, path of content items
        days_ago ([type]): minimum age of cve to include in the result

    Returns:
        [type]: a tree hierarchy in this form: cve_id -(found in)> docker_image -(used by)> content item
    """
    recent_cves = [entry for entry in filtered_content_entries]
    cve_bucket = bucket(recent_cves, lambda e: e.cve_id)  # group by cveid
    ret_dict = {}
    for cve_id in cve_bucket:
        entries_for_cve = list(cve_bucket[cve_id])
        affected_images: set = {f"{e.repository}:{e.tag}" for e in entries_for_cve}
        image_to_items = {}
        for image in affected_images:
            if content_using_image := [item.id for item in graph_entries if item.image == image]:
                image_to_items[image] = content_using_image
        if image_to_items:  # if this cve is in use, add it as an entry
            num_affected = sum(len(content_list) for content_list in image_to_items.values())

            ret_dict[cve_id] = {
                "content_items": image_to_items,
                "cve_details": entries_for_cve[0],
                "num_content_affected": num_affected,
                "cve_updated_info": ""
                if entries_for_cve[0].severity not in relevant_levels
                else cve_updated_info(entries_for_cve[0], days_ago),
            }
    return ret_dict


def create_report_result(
    content_report, graph_entries, unique_image_names, filtered_content_entries, new_cve_data, relevant_levels, progress
):
    problematic_candidates = problematic_prod_candidates(filtered_content_entries)
    total_cve_content_items = sum(
        repo_info["num_content_items_with_cves"]
        for repo_info in content_report.values()
        if repo_info["highest_severity"] in relevant_levels
    )
    total_critical_cve_content_items = sum(
        repo_info["num_content_items_with_critical_cves"]
        for repo_info in content_report.values()
        if repo_info["highest_severity"] == "critical"
    )
    number_used_deprecated_images = len({key: value for key, value in content_report.items() if value.get("deprecated")})
    return {
        "progress": progress,
        "relevant_levels": relevant_levels,
        "new_cve_data": new_cve_data,
        "content_report": content_report,
        "total_cve_content_items": total_cve_content_items,
        "total_critical_cve_content_items": total_critical_cve_content_items,
        "date": datetime.today().strftime("%Y-%m-%d"),
        "number_deprecated_images": number_used_deprecated_images,
        "problematic_candidates": problematic_candidates,
        "num_problematic_candidates": len(
            {entry.repository for entry in problematic_candidates if entry.severity in relevant_levels}
        ),
        "num_problematic_cves_candidates": len({entry.cve_id for entry in problematic_candidates}),
        "number_total_used_content": len({item.image for item in graph_entries}),
        "number_distinct_used_content": len(unique_image_names),
    }


def get_scan_progress():
    url = f'{os.getenv("PRISMA_CONSOLE_URL")}/api/{os.getenv("PRISMA_CONSOLE_API_VERSION")}'
    tenant = os.getenv("PRISMA_CONSOLE_TENANT")
    response = requests.get(
        f"{url}/registry/progress?project={tenant}",
        auth=(os.getenv("PRISMA_CONSOLE_USER"), os.getenv("PRISMA_CONSOLE_PASS")),
        verify=VERIFY,
    )
    response.raise_for_status()
    return response.json()


def main():
    args = get_cli_args()
    relevant_levels = args.relevant_security_levels.split(",")
    global VERIFY
    VERIFY = args.verify
    outdated_date = None
    if days := args.days_to_consider_outdated:
        outdated_date = (datetime.now() - timedelta(days=days)).date()

    twistlock_results = get_twistlock_results(args.twistlock_raw_input)

    graph_entries = get_all_content_images_to_id()

    unique_image_names = get_image_names(graph_entries)
    dockers_to_check = unique_image_names - set(args.excluded_repos.split(","))

    filtered_content_entries = filter_content_entries(
        twistlock_results,
        dockers_to_check,
        args.mitigated_cves_file,
    )

    new_cve_data = get_new_cve_data_for_entries(filtered_content_entries, graph_entries, args.days_ago_alert, relevant_levels)

    content_report = get_content_report(filtered_content_entries, graph_entries, outdated_date, args.content_dir, relevant_levels)

    results = create_report_result(
        content_report=content_report,
        graph_entries=graph_entries,
        unique_image_names=unique_image_names,
        filtered_content_entries=filtered_content_entries,
        new_cve_data=new_cve_data,
        relevant_levels=relevant_levels,
        progress=get_scan_progress(),
    )

    save_json_file(results, args.output_path)


if __name__ == "__main__":
    main()
