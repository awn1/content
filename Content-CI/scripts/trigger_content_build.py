import argparse
import os
from pathlib import Path
import time
from ruamel.yaml import YAML
import git.exc
import git
import requests
import sys
import json

yaml = YAML()

GITLAB_SERVER_URL = os.getenv(
    "CI_SERVER_URL", "https://gitlab.xdr.pan.local"  # disable-secrets-detection
)
GITLAB_CONTENT_PROJECT_ID = "1061"
GITLAB_CONTENT_TRIGGER_URL = (
    f"{GITLAB_SERVER_URL}/api/v4/projects/{GITLAB_CONTENT_PROJECT_ID}/trigger/pipeline"
)
GITLAB_CONTENT_PIPELINES_BASE_URL = (
    f"{GITLAB_SERVER_URL}/api/v4/projects/{GITLAB_CONTENT_PROJECT_ID}/pipelines/"
)
TIMEOUT = 60 * 60 * 6  # 6 hours

GITLAB_CI_PATH = Path("./content/.gitlab/ci/.gitlab-ci.yml")


class ExitCode:
    SUCCESS = 0
    FAILED = 1


# Create or update test branch


class TestBranch:
    def __init__(self, url: str, branch_name: str) -> None:
        self.url = url
        self.branch_name = branch_name
        self.delete_branch: bool = False
        self.repo: git.Repo = self.clone(self.url)
        self.repo.config_writer().set_value("user", "name", "bot-content").release()
        self.repo.config_writer().set_value("user", "email", "bot@dummy.com").release()

    def clone(self, url: str) -> git.Repo:
        """
        Clones the Content repo from the specified URL.
        If cloning fails the program exits with a status code of 1.
        """
        try:
            print("Cloning Content repo ...")
            repo = git.Repo.clone_from(url=url, to_path="./content")
            print("Cloned Content repo")
        except Exception as e:
            print(f"Cloning Content repo failed, Error: {str(e)}")
            sys.exit(ExitCode.FAILED)

        print("Sleeping 5 seconds")
        time.sleep(5.0)
        return repo

    def is_branch_exists(self) -> bool:
        """
        Checks if the specified branch exists in the Content repo.

        Returns:
            bool: True if the branch exists, False otherwise.
        """
        does_exist = True
        try:
            self.repo.git.checkout(self.branch_name)
            self.repo.git.pull("--rebase")
        except git.exc.GitCommandError as e:
            print(str(e))
            does_exist = False
        except Exception as e:
            print(str(e))
            does_exist = False

        return does_exist

    def create_branch(self):
        """
        Creates a new branch in the Content repo by the self.branch_name.
        """

        self.repo.git.checkout("-b", self.branch_name)
        self.delete_branch = True
        print("Created new branch")

    def update_gitlab_ci_file(self):
        """
        Updates the 'ref' and 'CURRENT_BRANCH_NAME' variables
        in the GitLab CI file with the current branch name.
        """

        # Load GitLab CI file
        gitlab_ci_content = yaml.load(GITLAB_CI_PATH.read_text())

        # Update 'ref' for the include
        if gitlab_ci_content["include"][0]["ref"] != self.branch_name:
            gitlab_ci_content["include"][0]["ref"] = self.branch_name

        # Update 'CURRENT_BRANCH_NAME' variable
        if gitlab_ci_content["variables"]["CURRENT_BRANCH_NAME"] != self.branch_name:
            gitlab_ci_content["variables"]["CURRENT_BRANCH_NAME"] = self.branch_name

        yaml.dump(gitlab_ci_content, open(GITLAB_CI_PATH, "w"))

    def create_or_update_test_branch(self):
        """
        Creates or updates a test branch in the Content repo and pushes the changes to the remote.

        """
        if not self.is_branch_exists():
            print("branch does not exists in Content repo")
            self.create_branch()

        self.update_gitlab_ci_file()

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

    def delete_test_branch(self):
        if self.delete_branch:
            try:
                print(f"Start deleting branch: '{self.branch_name}'")
                self.repo.git.push("--set-upstream", self.url, f":{self.branch_name}")

                print("Successfully deleted branch.")
            except git.GitCommandError as e:
                print(e)
                sys.exit(ExitCode.FAILED)
            return
        print("The branch existed, no need to delete it")


# Trigger the test build in Content


class PipelineManager:
    def __init__(
        self,
        trigger_url,
        gl_trigger_token,
        gl_info_token,
        gl_cancel_token,
        branch_name,
    ):
        self.trigger_url = trigger_url
        self.trigger_token = gl_trigger_token
        self.cancel_token = gl_cancel_token
        self.headers = {"Authorization": f"Bearer {gl_info_token}"}
        self.branch_name = branch_name

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
            print(f"Error: {e}")
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
                print(f"Error: {e}")
                exit(ExitCode.FAILED)
        print(f"All pipelines for branch {self.branch_name} have been canceled")

    def initiate_pipeline(self):
        if pipelines_runs := self.is_exist_pipeline_runs():
            self.cancel_pipelines(pipelines_runs)

        files = {
            "token": (None, self.trigger_token),
            "ref": (None, self.branch_name),
            "variables[TRIGGER_TEST_BRANCH]": (None, "true"),
        }
        try:
            res = requests.post(url=self.trigger_url, files=files, verify=False).json()
            # When it fails and an exception is not raised
            if 'web_url' not in res:
                print(f"Error: {str(res)}")
                sys.exit(ExitCode.FAILED)
            print(f"Successful triggered test content build - see {res['web_url']}")
            self.pipeline_id = str(res["id"])
        except Exception as e:
            print(f"Error: {str(e)}")
            sys.exit(ExitCode.FAILED)

    def pipeline_info(self, field_info: str = "web_url"):
        url = (
            GITLAB_CONTENT_PIPELINES_BASE_URL
            + self.pipeline_id
            + ("/jobs" if field_info == "status" else "")
        )
        res = requests.get(url, headers=self.headers)
        if res.status_code != 200:
            print(
                f"Failed to get status of pipeline {self.pipeline_id}, request to "
                f"{GITLAB_CONTENT_PIPELINES_BASE_URL} failed with error: {str(res.content)}"
            )
            sys.exit(ExitCode.FAILED)

        try:
            jobs_info = json.loads(res.content)
        except Exception as e:
            print(f"Unable to parse pipeline response: {e}")
            sys.exit(ExitCode.FAILED)

        if field_info == "status":
            return jobs_info[0].get("pipeline", {}).get("status")
        else:
            return jobs_info.get("web_url")

    def wait_for_pipeline_completion(self):

        pipeline_status = "running"  # pipeline status when start to run

        # initialize timer
        start = time.time()
        elapsed: float = 0

        while (
            pipeline_status not in ["failed", "success", "canceled"]
            and elapsed < TIMEOUT
        ):
            print(f"Pipeline {self.pipeline_id} status is {pipeline_status}")
            time.sleep(600)
            pipeline_status = self.pipeline_info(field_info="status")
            elapsed = time.time() - start

        if elapsed >= TIMEOUT:
            print(
                f"Timeout reached while waiting for upload to complete, pipeline number: {self.pipeline_id}"
            )
            sys.exit(ExitCode.FAILED)

        pipeline_url = self.pipeline_info()

        if pipeline_status in ["failed", "canceled"]:
            print(f"Content pipeline {pipeline_status}. See here: {pipeline_url}")
            return ExitCode.FAILED

        print(f"Content pipeline has finished. See pipeline here: {pipeline_url}")
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
    return parser.parse_args()


def main():
    # log_util.install_logging('trigger_content_build.log', logger=logging)

    # Parse arguments
    args = parse_arguments()
    server_host = args.server_host
    project_name = args.project_name
    username = args.username
    token_info = args.gitlab_token
    token_trigger = args.gitlab_token_trigger
    token_cancel = args.gitlab_cancel_token
    url = f"https://{username}:{token_info}@{server_host}/{project_name}.git"
    branch_name = args.branch_name

    # Managing the creation and update of the test branch
    test_branch = TestBranch(url, branch_name)
    test_branch.create_or_update_test_branch()

    # Managing and triggering the pipeline
    pipeline_manager = PipelineManager(
        GITLAB_CONTENT_TRIGGER_URL,
        token_trigger,
        token_info,
        token_cancel,
        branch_name,
    )
    pipeline_manager.initiate_pipeline()
    exit_code = pipeline_manager.wait_for_pipeline_completion()

    # Deleting the test branch if necessary
    test_branch.delete_test_branch()

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
