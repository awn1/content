import os

import requests
from create_cve_report_json import get_latest_tag
from demisto_sdk.commands.content_graph.interface.neo4j.neo4j_graph import (
    Neo4jContentGraphInterface as ContentGraphInterface,
)
from neo4j import Transaction
from requests.auth import HTTPBasicAuth


def query_used_dockers(tx: Transaction) -> list[tuple[str]]:
    """
    queries the content graph for relevant docker images
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
    Return DISTINCT iss.docker_image
    """
        )
    )


def get_all_content_images() -> set[str]:
    """Return all used content items, their images, and their paths

    Returns:
        list[dict]: each dict has id, image, path attributes
    """
    with ContentGraphInterface() as graph:
        with graph.driver.session() as session:
            return {row[0] for row in session.execute_read(query_used_dockers)}


def get_twistlock_scan_rules(images):
    repos_tags: set[tuple] = {tuple(image.split(":")) for image in images}
    print(f"There are {len(repos_tags)} distinct repos excluding latest")
    distinct_repos = {rt[0] for rt in repos_tags}
    latest_repo_tag: set[tuple] = {(repo, get_latest_tag(repo)) for repo in distinct_repos}
    return [
        {
            "repository": repo,
            "tag": tag,
            "cap": 1,
            "os": "linux",
            "version": "2",
            "credentialID": "demistodockerhub",
            "scanners": 2,
            "collections": ["All"],
            "harborDeploymentSecurity": False,
        }
        for repo, tag in repos_tags | latest_repo_tag
    ]


def main():
    images = get_all_content_images()

    scan_rules = get_twistlock_scan_rules(images)

    settings_body = {"specifications": scan_rules}

    url = f'{os.getenv("PRISMA_CONSOLE_URL")}/api/{os.getenv("PRISMA_CONSOLE_API_VERSION")}'
    tenant = os.getenv("PRISMA_CONSOLE_TENANT")
    basic = HTTPBasicAuth(os.getenv("PRISMA_CONSOLE_USER"), os.getenv("PRISMA_CONSOLE_PASS"))
    print(f"Posting {len(scan_rules)} rules to Twistlock")

    put_rules_response = requests.put(f"{url}/settings/registry?project={tenant}", auth=basic, json=settings_body)
    put_rules_response.raise_for_status()

    print("posted rules to twistlock successfully")

    start_scan_response = requests.post(f"{url}/registry/scan?project={tenant}", auth=basic)
    start_scan_response.raise_for_status()

    print("started scan in twistlock")


if __name__ == "__main__":
    main()
