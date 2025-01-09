import argparse
import json
import re
import sys
from distutils.util import strtobool

import requests
import urllib3

from Tests.scripts.utils import logging_wrapper as logging
from Tests.scripts.utils.log_util import install_logging

# Disable insecure warnings
urllib3.disable_warnings()

# Regex to split the changelog line to 3 pieces: description, PR number, and URL
CHANGELOG_REGEX = re.compile(r"^(.*) \[(#\d+)\]\((http.*)\)")
# Adjusted regex to match titles
CHANGELOG_TITLE_REGEX = re.compile(r"#+\s*(\d+\.\d+\.\d+)\s*")


def fetch_changelog(release_branch_name: str) -> str:
    url = f"https://raw.githubusercontent.com/demisto/demisto-sdk/{release_branch_name}/CHANGELOG.md"
    response = requests.request("GET", url, verify=False)
    if response.status_code != requests.codes.ok:
        logging.error(f"Failed to get the CHANGELOG.md file from branch {release_branch_name}")
        logging.error(response.text)
        sys.exit(1)
    return response.text


def compile_changelog(changelog: str, text_format="markdown"):
    # Extract the specific release section
    if not (release_section_match := CHANGELOG_TITLE_REGEX.search(changelog)):
        logging.error("Failed to find the release section in the changelog")
        sys.exit(1)
    version = release_section_match.group(1)

    # Split the file text on the matched release title
    release_sections = changelog.split(f"## {version}")
    # The first value in the `release_section` is the new line (/n) after the release title.
    release_section = release_sections[1] if len(release_sections) > 1 else release_sections[0]

    # Limit release_section to the next major section (##) or end of file
    next_section_idx = release_section.find("\n## ")
    if next_section_idx != -1:
        release_section = release_section[:next_section_idx].strip()
    else:
        release_section = release_section.strip()

    # Find all categories dynamically, e.g, Feature, Internal
    category_matches = re.findall(r"### (\w+)", release_section)
    category_to_notes: dict[str, list] = {category: [] for category in category_matches}

    for category in category_matches:
        category_section_match = re.search(f"### {category}\n(.*?)(?=\n###|\Z)", release_section, re.DOTALL)
        if category_section_match:
            changes = category_section_match.group(1).strip().splitlines()
            for change in changes:
                match = CHANGELOG_REGEX.search(change)
                if match:
                    description, pr_number, url = match.groups()
                    if text_format == "markdown":
                        category_to_notes[category].append(f"{description} [{pr_number}]({url})")
                    elif text_format == "slack":
                        category_to_notes[category].append(f"{description} <{url}|{pr_number}>")
                    else:
                        logging.error(f"The format {text_format} is not supported")
                        sys.exit(1)

    # Combine all sections into a single string
    result_lines = []
    for category, changes in category_to_notes.items():
        if changes:
            result_lines.append(f"### {category}")
            result_lines.extend(changes)
            result_lines.append("")  # Add an empty line between sections

    return "\n".join(result_lines)


def options_handler():
    parser = argparse.ArgumentParser(description="Creates release branch for demisto-sdk.")

    parser.add_argument("-t", "--access_token", help="Github access token", required=True)
    parser.add_argument("-b", "--release_branch_name", help="The name of the release branch", required=True)
    parser.add_argument("-d", "--is_draft", help="Is draft release", default="FALSE")
    options = parser.parse_args()
    return options


def main():
    install_logging("create_release.log", logger=logging)

    options = options_handler()
    release_branch_name = options.release_branch_name
    access_token = options.access_token
    is_draft = bool(strtobool(options.is_draft))

    if is_draft:
        logging.info(f"Preparing to create draft release for Demisto SDK version {release_branch_name}")
    else:
        logging.info(f"Preparing to release Demisto SDK version {release_branch_name}")

    # release the sdk version
    # The reference can be found here https://docs.github.com/en/rest/releases/releases?apiVersion=2022-11-28#create-a-release
    url = "https://api.github.com/repos/demisto/demisto-sdk/releases"
    data = json.dumps(
        {
            "tag_name": f"v{release_branch_name}",
            "name": f"v{release_branch_name}",
            "body": compile_changelog(fetch_changelog(release_branch_name)),
            "draft": is_draft,
            "target_commitish": release_branch_name,
        }
    )

    headers = {"Content-Type": "application/vnd.github+json", "Authorization": f"Bearer {access_token}"}
    response = requests.request("POST", url, headers=headers, data=data, verify=False)
    if response.status_code != requests.codes.created:
        if response.status_code == 422 and "already_exists" in response.text:
            logging.info(f"Demisto SDK v{release_branch_name} already exist")
            return
        logging.error(f"Failed to create release {release_branch_name} for demisto SDK")
        logging.error(response.text)
        sys.exit(1)

    logging.success(f"Demisto SDK v{release_branch_name} released successfully!")


if __name__ == "__main__":
    main()
