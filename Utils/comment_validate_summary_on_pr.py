#!/usr/bin/env python3
import argparse
import logging
import os
import sys
from pathlib import Path

import requests


def main():
    parser = argparse.ArgumentParser(description="Add a comment to a pull request in the repo.")
    parser.add_argument("-p", "--pr_number", help="Pull request number")
    parser.add_argument("-ght", "--github_token", help="The token for Github-Api", required=False)
    args = parser.parse_args()

    pr_number = args.pr_number
    token = args.github_token
    comment_validate_summary_on_pr(pr_number, token)

    print("Successfully added the comment to the PR.")


def get_pr_comments_url(pr_number: str) -> str:
    """
    Get the comments URL for a PR. If the PR contains a comment about an instance test (for contrib PRs),
    it will use that comment.
    Args:
        pr_number: The pull request number

    Returns:
        The comments URL for the PR.
    """
    pr_url = f"https://api.github.com/repos/demisto/content/pulls/{pr_number}"
    response = requests.get(pr_url)
    response.raise_for_status()
    pr = response.json()
    if not pr:
        print("Could not find the pull request to reply on.")
        sys.exit(1)
    page = 1
    comments_url = pr["comments_url"]
    while True:
        response = requests.get(comments_url, params={"page": str(page)})
        response.raise_for_status()
        comments = response.json()
        if not comments:
            break

        link_comments = [comment for comment in comments if "Instance is ready." in comment.get("body", "")]
        if link_comments:
            comments_url = link_comments[0]["url"]
            break
        page += 1

    return comments_url


def comment_validate_summary_on_pr(pr_num: int, github_token: str) -> None:
    """
    If the validate summary exist, comment the summary on the pr.

    """
    # Getting validate summary message.
    validate_summary_msg = obtain_validate_summary_msg()
    if not validate_summary_msg:
        logging.info("validate_summary_msg is empty, aborting comment.")
        return
    # Checking whether there's already a validate_summary msg in the pr so we could update it rather than add a new one.
    comments_url: str = get_pr_comments_url(str(pr_num))
    headers = {"Authorization": f"Bearer {github_token}"}
    comments = get_pr_comments(comments_url, headers)
    if comments:
        logging.info("The PR already include comments, checking for validate_summary comment.")
        for comment in comments:
            if comment.get("body", "").startswith("Validate summary"):
                logging.info(f"Validate summary already exists, deleting the comment {comment['id']}.")
                remove_previous_comment(comments_url, headers, comment["id"])
                # break
    # Posting new validate_summary msg.
    comment_on_pr(comments_url, validate_summary_msg, headers)
    logging.info(f"Successfully commented on PR {pr_num} the validate summary.")


def remove_previous_comment(url: str, headers: dict, comment_id: str):
    """Send request to remove the previous coment

    Args:
        url (str): The pr url
        headers (dict): The headers dict including the auth.
        comment_id (str): The id of the comment to be removed.
    """
    requests.delete(f"https://api.github.com/repos/demisto/content/issues/comments/{comment_id}", headers=headers)


def get_pr_comments(url: str, headers: dict):
    """Execute a request to get all the pr comments.

    Args:
        url (str): The pr's url to get the comments from.
        headers (dict): The headers dict including the auth.

    Returns:
        The list of pr's existing comments.
    """
    response = requests.get(url, headers=headers)
    comments = response.json()
    return comments


def comment_on_pr(url: str, msg: str, headers: dict):
    """Execute a request to comment on the pr.

    Args:
        url (str): The pr's url / url to the specific comment if already exist.
        msg (str): The msg to comment.
        headers (dict): The headers dict including the auth.
    """
    response = requests.post(url, json={"body": msg}, headers=headers)
    response.raise_for_status()


def obtain_validate_summary_msg():
    """Obtain the validate summary txt file from the artifacts and returns it.

    Raises:
        Exception: if the validate summary file doesn't exist.
        Exception: _description_
    """
    validate_summary_msg = ""
    if (artifacts_folder := Path(os.getenv("ARTIFACTS_FOLDER", "."))) and artifacts_folder.exists():
        if (
            artifacts_validate_summary_path := artifacts_folder / "validate_summary.txt"
        ) and artifacts_validate_summary_path.exists():
            logging.info(f"reading from the validate summary results at {artifacts_validate_summary_path.as_posix()}.")
            validate_summary_msg = artifacts_validate_summary_path.read_text()
            logging.info(f"Done reading file at {artifacts_validate_summary_path.as_posix()}, {validate_summary_msg=}.")
        else:
            raise Exception(f"could not find validate summary file at {artifacts_validate_summary_path}.")
    else:
        raise Exception(f"could not find artifacts folder at {artifacts_folder}.")
    return validate_summary_msg


if __name__ == "__main__":
    main()
