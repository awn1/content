import argparse
import logging
import os
from pathlib import Path
import time
from ruamel.yaml import YAML
import git.exc
import git
import requests
import sys
import json
import urllib3

from urllib3.exceptions import InsecureRequestWarning
import common
from Tests.scripts.utils.log_util import install_logging

urllib3.disable_warnings(InsecureRequestWarning)

yaml = YAML()

GITLAB_SERVER_URL = os.getenv(
    "CI_SERVER_URL", "https://gitlab.xdr.pan.local"  # disable-secrets-detection
)
GITLAB_CONTENT_PROJECT_ID = "1061"
GITLAB_CONTENT_TRIGGER_URL = (
    f"{GITLAB_SERVER_URL}/api/v4/projects/{GITLAB_CONTENT_PROJECT_ID}/trigger/pipeline"
)
GITLAB_CONTENT_REPO_URL = (
    f"{GITLAB_SERVER_URL}/api/v4/projects/{GITLAB_CONTENT_PROJECT_ID}/repository/branches/"
)
GITLAB_CONTENT_PIPELINES_BASE_URL = (
    f"{GITLAB_SERVER_URL}/api/v4/projects/{GITLAB_CONTENT_PROJECT_ID}/pipelines/"
)
TIMEOUT = 60 * 60 * 6  # 6 hours
ARTIFACTS_FOLDER = Path(os.getenv('ARTIFACTS_FOLDER', '.'))

GITLAB_CI_PATH = Path("./content/.gitlab/ci/.gitlab-ci.yml")
SLACK_CHANNEL = os.environ.get('SLACK_CHANNEL', 'dmst-build-test')


class ExitCode:
    SUCCESS = 0
    FAILED = 1


logger = logging.getLogger(__name__)

# Create or update test branch


class TestBranch:
    def __init__(self, url: str, branch_name: str, github_token: str, gitlab_token: str) -> None:
        self.url = url
        self.branch_name = branch_name
        self.github_token = github_token
        self.gitlab_token = gitlab_token

    def clone(self, url: str):
        """
        Clones the Content repo from the specified URL.
        If cloning fails the program exits with a status code of 1.
        """
        try:
            print("Cloning Content repo ...")
            repo = git.Repo.clone_from(url=url, to_path="./content", depth=1)
            print("Cloned Content repo")
        except Exception as e:
            print(f"Cloning Content repo failed, Error: {str(e)}")
            sys.exit(ExitCode.FAILED)

        print("Sleeping 5 seconds")
        time.sleep(5.0)

        self.repo = repo
        self.repo.config_writer().set_value("user", "name", "bot-content").release()
        self.repo.config_writer().set_value("user", "email", "bot@dummy.com").release()

    def is_there_pr_in_github(self):
        """
        checks if a specific branch exists on GitHub and not on GitLab, if so,
        deletes the corresponding branch from the GitLab
        """
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.github_token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        params = {
            "state": "open",
            "base": "master",
            "head": f"demisto:{self.branch_name}",
        }
        res = requests.get(
            "https://api.github.com/repos/demisto/content/pulls",
            params=params,
            headers=headers,
            verify=False,
        )
        return bool(res.json())

    def delete_old_branch(self):
        try:
            # Removing remote branch
            print(f"Start deleting old branch: '{self.branch_name}' in remote")
            self.repo.git.push("--set-upstream", self.url, f":{self.branch_name}")
            print("Successfully deleted old branch.")
        except git.GitCommandError as e:
            print(e)
            sys.exit(ExitCode.FAILED)
        print("Sleep 5 seconds after deleting old branch")
        time.sleep(5.0)

    def is_branch_exists_in_gitlab(self) -> bool:
        """
        Checks if the specified branch exists in the GitLab Content repo.

        Returns:
            bool: True if the branch exists, False otherwise.
        """
        headers = {
            "Content-Type": "application/json",
            "PRIVATE-TOKEN": self.gitlab_token,
        }
        res = requests.get(
            url=GITLAB_CONTENT_REPO_URL + self.branch_name,
            headers=headers,
        )
        return res.status_code == 200

    def create_branch(self):
        """
        Creates a new branch in the Content repo by the self.branch_name.
        """
        self.repo.git.checkout("-b", self.branch_name)
        print("Created new branch")

    def create_test_branch(self):
        """
        Checks if a test branch needs to be created,
        if so it is created in the Content repo and pushed to the remote.

        """
        if self.is_there_pr_in_github():
            print(
                "There is a PR in GitHub that belong to "
                f"the {self.branch_name} branch, no need to create a new branch"
            )
            return

        self.clone(self.url)
        if self.is_branch_exists_in_gitlab():
            print(
                "Founded old branch with the same name in Gitlab Content repo, we will to delete it, "
                "don't worry we are recreating it"
            )
            self.delete_old_branch()
        self.create_branch()

        self.repo.git.add(".")
        self.repo.git.commit(
            "--allow-empty", "-m", "Test build for infra files", no_verify=True
        )

        # Push changes to the remote repository, skipping CI pipelines
        self.repo.git.push(
            "--set-upstream", self.url, self.branch_name, push_option="ci.skip"
        )

        print("Sleeping after pushing 10 seconds")
        time.sleep(10.0)

# Trigger the test build in Content


class PipelineManager:
    def __init__(self, trigger_url, gl_trigger_token, gl_info_token, gl_cancel_token, branch_name, is_nightly, is_sdk_nightly,
                 slack_channel):
        self.pipeline_id = None
        self.trigger_url = trigger_url
        self.trigger_token = gl_trigger_token
        self.cancel_token = gl_cancel_token
        self.headers = {"Authorization": f"Bearer {gl_info_token}"}
        self.branch_name = branch_name
        self.is_nightly = is_nightly
        self.is_sdk_nightly = is_sdk_nightly
        self.slack_channel = slack_channel

    def is_exist_pipeline_runs(self) -> list[dict]:
        headers = {
            "Content-Type": "application/json",
            "PRIVATE-TOKEN": self.cancel_token,
        }
        params = {"ref": self.branch_name}
        try:
            response = requests.get(
                GITLAB_CONTENT_PIPELINES_BASE_URL, params=params, headers=headers
            ).json()
        except Exception as e:
            logging.info(f"Error: {e}")
            exit(ExitCode.FAILED)
        if response:
            return [res for res in response if res.get("status") == "running"]
        else:
            return []

    def cancel_pipelines(self, pipelines: list[dict]):
        headers = {
            "PRIVATE-TOKEN": self.cancel_token,
        }
        for pipeline in pipelines:
            try:
                requests.post(
                    GITLAB_CONTENT_PIPELINES_BASE_URL + f"{pipeline['id']}/cancel",
                    headers=headers,
                )
            except Exception as e:
                logging.info(f"Error: {e}")
                exit(ExitCode.FAILED)
        logging.info(f"All pipelines for branch {self.branch_name} have been canceled")

    def initiate_pipeline(self, output_file) -> int:
        if pipelines_runs := self.is_exist_pipeline_runs():
            self.cancel_pipelines(pipelines_runs)

        files = {
            "token": (None, self.trigger_token),
            "ref": (None, self.branch_name),
            "variables[INFRA_BRANCH]": (None, self.branch_name),
        }
        if self.slack_channel:
            slack_parent_pipeline_id = os.environ["CI_PIPELINE_ID"]
            slack_parent_project_id = os.environ["CI_PROJECT_ID"]
            files["variables[SLACK_CHANNEL]"] = (None, self.slack_channel)
            files["variables[SLACK_PARENT_PIPELINE_ID]"] = (None, slack_parent_pipeline_id)
            files["variables[SLACK_PARENT_PROJECT_ID]"] = (None, slack_parent_project_id)
        build_type = common.CONTENT_PR
        if self.is_nightly:
            build_type = common.CONTENT_NIGHTLY
            files["variables[IS_NIGHTLY]"] = (None, "true")
            files["variables[NIGHTLY]"] = (None, "true")  # backward compatibility.
        if self.is_sdk_nightly:
            build_type = common.SDK_NIGHTLY
            files["variables[DEMISTO_SDK_NIGHTLY]"] = (None, "true")
        if not self.is_nightly and not self.is_sdk_nightly:
            files["variables[TRIGGER_TEST_BRANCH]"] = (None, "true")
        try:
            res = requests.post(url=self.trigger_url, files=files, verify=False).json()
            # When it fails and an exception is not raised, so we raise an exception.
            if "web_url" not in res:
                raise Exception(str(res))

            logging.info(f"Successful triggered build type:{build_type} - see {res['web_url']}")
            self.pipeline_id = str(res["id"])
            if output_file:
                with open(output_file, "w") as f:
                    title = (f"{build_type} - pipeline has been triggered. "
                             f"See pipeline {common.slack_link(res['web_url'], 'here')}")
                    f.write(json.dumps([{
                        'color': 'good',
                        'fallback': title,
                        'title': title,
                    }]))
            return ExitCode.SUCCESS
        except Exception as e:
            logging.exception(f"Error: {str(e)}")
            if output_file:
                with open(output_file, "w") as f:
                    title = f"Failed to trigger build type: {build_type}"
                    f.write(json.dumps([{
                        'color': 'danger',
                        'fallback': title,
                        'title': title,
                    }]))

        return ExitCode.FAILED

    def pipeline_info(self, field_info: str = "web_url"):
        job_suffix = "/jobs" if field_info == "status" else ""
        url = f"{GITLAB_CONTENT_PIPELINES_BASE_URL}{self.pipeline_id}{job_suffix}"
        res = requests.get(url, headers=self.headers)
        if res.status_code != 200:
            logging.info(
                f"Failed to get status of pipeline {self.pipeline_id}, request to "
                f"{GITLAB_CONTENT_PIPELINES_BASE_URL} failed with error: {str(res.content)}"
            )
            sys.exit(ExitCode.FAILED)

        try:
            jobs_info = json.loads(res.content)
        except Exception as e:
            logging.info(f"Unable to parse pipeline response: {e}")
            sys.exit(ExitCode.FAILED)

        if field_info == "status":
            return jobs_info[0].get("pipeline", {}).get("status")
        else:
            return jobs_info.get("web_url")

    def wait_for_pipeline_completion(self, sleep_time: int = 600):

        # initialize timer
        start = time.time()

        while True:
            pipeline_status = self.pipeline_info(field_info="status")
            if pipeline_status in ["failed", "success", "canceled"]:
                break
            elapsed = time.time() - start
            if elapsed >= TIMEOUT:
                logging.info(
                    f"Timeout reached while waiting for upload to complete, pipeline number: {self.pipeline_id}"
                )
                return ExitCode.FAILED
            logging.info(f"Pipeline {self.pipeline_id} status is {pipeline_status}, sleeping for {sleep_time} seconds")
            time.sleep(sleep_time)

        pipeline_url = self.pipeline_info()

        if pipeline_status in ["failed", "canceled"]:
            logging.info(f"Content pipeline {pipeline_status}. See here: {pipeline_url}")
            return ExitCode.FAILED

        logging.info(f"Content pipeline has finished. See pipeline here: {pipeline_url}")
        return ExitCode.SUCCESS


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("-gt", "--gitlab-token", help="Gitlab Content token.")  #
    parser.add_argument("-gct", "--gitlab-cancel-token", help="Gitlab Content token.")
    parser.add_argument("-gtt", "--gitlab-token-trigger")
    parser.add_argument(
        "-un", "--username", help="Gitlab username.", default="gitlab-ci-token"
    )
    parser.add_argument(
        "-sh", "--server-host", help="A server host", default="gitlab.xdr.pan.local"
    )
    parser.add_argument("-pn", "--project-name", help="A project name")
    parser.add_argument("-bn", "--branch-name", help="Current branch name")
    parser.add_argument("-ght", "--github-token", help="GitHub token")
    parser.add_argument('-n', '--is-nightly', type=common.string_to_bool, help='Is nightly build')
    parser.add_argument('-sn', '--sdk-nightly', type=common.string_to_bool, help='Is SDK nightly build')
    parser.add_argument(
        '-ch', '--slack-channel', help='The slack channel in which to send the notification', default=SLACK_CHANNEL
    )
    parser.add_argument('-w', '--wait', help='Wait for the pipeline to finish', action='store_true', default=False)
    parser.add_argument('-o', '--output', help='Output file for the slack message', default=None)
    return parser.parse_args()


def main():
    install_logging("trigger_content_build.log")

    # Parse arguments
    args = parse_arguments()
    server_host = args.server_host
    project_name = args.project_name
    username = args.username
    token_info = args.gitlab_token
    token_trigger = args.gitlab_token_trigger
    token_cancel = args.gitlab_cancel_token
    github_token = args.github_token
    url = f"https://{username}:{token_info}@{server_host}/{project_name}.git"
    branch_name = args.branch_name

    # Managing the creation and update of the test branch
    test_branch = TestBranch(url, branch_name, github_token, token_cancel)
    test_branch.create_test_branch()

    logging.info(f"Triggering content build for branch {branch_name}")
    logging.info(f"Project name: {project_name}")
    logging.info(f"Is nightly: {args.is_nightly}")
    logging.info(f"Is SDK nightly: {args.sdk_nightly}")
    logging.info(f"Slack channel: {args.slack_channel}")
    logging.info(f"Wait for pipeline to finish: {args.wait}")
    logging.info(f"Output file: {args.output}")

    # Managing and triggering the pipeline
    pipeline_manager = PipelineManager(
        GITLAB_CONTENT_TRIGGER_URL,
        token_trigger,
        token_info,
        token_cancel,
        branch_name,
        args.is_nightly,
        args.sdk_nightly,
        args.slack_channel,
    )
    if exit_code := pipeline_manager.initiate_pipeline(args.output) != ExitCode.SUCCESS:
        sys.exit(exit_code)
    if args.wait:
        exit_code = pipeline_manager.wait_for_pipeline_completion()
        sys.exit(exit_code)


if __name__ == "__main__":
    main()
