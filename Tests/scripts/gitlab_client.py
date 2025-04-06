import os
import zipfile
from distutils.util import strtobool
from pathlib import Path
from tempfile import mkdtemp
from typing import Any

import requests
import urllib3

from Tests.scripts.utils import logging_wrapper as logging
from Tests.scripts.utils.log_util import install_logging

urllib3.disable_warnings()

GITLAB_SERVER_URL = os.getenv("CI_SERVER_URL", "https://gitlab.xdr.pan.local")  # disable-secrets-detection
GITLAB_SSL_VERIFY = bool(strtobool(os.getenv("GITLAB_SSL_VERIFY", "true")))
API_BASE_URL = f"{GITLAB_SERVER_URL}/api/v4"
PROJECT_ID = os.getenv("CI_PROJECT_ID", "1061")  # default is Content
install_logging("gitlab_client.log")


class GitlabClient:
    def __init__(self, gitlab_token: str) -> None:
        self.base_url = f"{API_BASE_URL}/projects/{PROJECT_ID}"
        self.headers = {"PRIVATE-TOKEN": gitlab_token}

    def _get(
        self,
        endpoint: str,
        params: dict | None = None,
        to_json: bool = False,
        stream: bool = False,
    ) -> Any:
        url = f"{self.base_url}/{endpoint}"
        response = requests.get(url, params, headers=self.headers, stream=stream, verify=GITLAB_SSL_VERIFY)
        response.raise_for_status()
        if to_json:
            return response.json()
        return response

    def get_pipelines(
        self,
        commit_sha: str | None = None,
        ref: str | None = None,
        sort: str = "asc",
    ) -> list:
        params = {
            "sha": commit_sha,
            "ref": ref,
            "sort": sort,
        }
        return self._get("pipelines", params=params, to_json=True)

    def get_job_id_by_name(self, pipeline_id: str, job_name: str) -> str | None:
        response: list = self._get(f"pipelines/{pipeline_id}/jobs", to_json=True)
        for job in response:
            if job["name"] == job_name:
                return job["id"]
        return None

    def download_and_extract_artifacts_bundle(
        self,
        job_id: str,
    ) -> Path:
        temp_path = Path(mkdtemp())
        target_path = temp_path / "artifacts.zip"
        response: requests.Response = self._get(f"jobs/{job_id}/artifacts", stream=True)
        with open(target_path, "wb") as zip_file:
            for chunk in response.iter_content(chunk_size=8192):
                zip_file.write(chunk)

        with zipfile.ZipFile(target_path, "r") as zip_ref:
            zip_ref.extractall(temp_path)

        return temp_path

    def get_artifact_file(
        self,
        commit_sha: str,
        job_name: str,
        artifact_filepath: Path,
        ref: str | None = None,
    ) -> str:
        """Gets an artifact file data as text.

        Args:
            commit_sha (str): A commit SHA
            job_name (str): A job name
            artifact_filepath (Path): The artifact file path
            ref (str): The branch name.

        Raises:
            Exception: An exception message specifying the reasons for not returning the file data,
            for each pipeline triggered for the given commit SHA.

        Returns:
            str: The artifact text data.
        """
        try:
            pipelines = self.get_pipelines(commit_sha=commit_sha, ref=ref)
            if not pipelines:
                raise Exception("No pipelines found for this SHA")
            errors = []
            for pipeline in pipelines:
                pid = pipeline["id"]
                if job_id := self.get_job_id_by_name(pid, job_name):
                    try:
                        bundle_path = self.download_and_extract_artifacts_bundle(job_id)
                        return (bundle_path / artifact_filepath).read_text()
                    except requests.HTTPError:
                        errors.append(f"Pipeline #{pid}: No artifacts in job {job_name}")
                    except FileNotFoundError:
                        errors.append(f"Pipeline #{pid}: The file {artifact_filepath} does not exist in the artifacts")
                else:
                    errors.append(f"Pipeline #{pid}: No job with the name {job_name}")
            raise Exception("\n".join(errors))

        except Exception as e:
            raise Exception(f"Could not extract {artifact_filepath.name} from any pipeline with SHA {commit_sha}:\n{e}")


class GitlabMergeRequest(GitlabClient):
    def __init__(
        self,
        gitlab_token: str,
        sha1: str | None = None,
        branch: str | None = None,
        mr_number: int | None = None,
        state: str = "opened",
    ) -> None:
        super().__init__(gitlab_token)
        self.data = self.get_merge_request(sha1, branch, mr_number, state)

    def get_merge_request(
        self,
        sha1: str | None = None,
        branch: str | None = None,
        mr_number: int | None = None,
        state: str = "opened",
    ) -> dict:
        """Fetches merge request details by merge request number, branch, or sha1.

        Args:
            sha1 (str | None): The commit SHA associated with the merge request.
            branch (str | None): The source branch of the merge request.
            mr_number (int | None): The merge request number (MR ID).
            state (str): The state of the merge request (e.g., 'opened', 'closed', 'merged'). Defaults to 'opened'.

        Returns:
            dict: The merge request details.
        """
        if not (sha1 or branch or mr_number):
            raise ValueError("You must provide at least one of sha1, branch, or mr_number to fetch the merge request.")

        if mr_number:
            logging.info(f"Fetching merge request by MR number: {mr_number}")
            endpoint = f"merge_requests/{mr_number}"
            return self._get(endpoint, to_json=True)

        # Search for merge requests using branch or sha1
        logging.info(f"Searching for merge requests with branch='{branch}', sha1='{sha1}', state='{state}'")
        endpoint = "merge_requests"
        params = {"state": state}

        if branch:
            params["source_branch"] = branch
        if sha1:
            params["sha"] = sha1

        res = self._get(endpoint, params=params, to_json=True)
        logging.debug(f"Fetched merge request: {res}")
        if not res:
            logging.warning(f"No merge requests found for branch '{branch}', sha1='{sha1}', state='{state}'")
        elif len(res) > 1:
            logging.warning(
                f"Multiple merge requests found for branch '{branch}', sha1='{sha1}', state='{state}', skipping search."
            )
        else:
            return res[0]

        return {}

    def add_comment(self, comment: str) -> None:
        """Adds a comment to the merge request.

        Args:
            comment (str): The comment text.
        """
        logging.info(f"Adding a comment to merge request #{self.data['iid']}")
        endpoint = f"merge_requests/{self.data['iid']}/notes"
        response = requests.post(
            f"{self.base_url}/{endpoint}",
            json={"body": comment},
            headers=self.headers,
        )
        response.raise_for_status()

    def edit_comment(self, comment_id: int, comment: str) -> None:
        """Edits an existing comment on the merge request.

        Args:
            comment_id (int): The ID of the comment to edit.
            comment (str): The updated comment text.
        """
        logging.info(f"Editing comment #{comment_id} on merge request #{self.data['iid']}")
        endpoint = f"merge_requests/{self.data['iid']}/notes/{comment_id}"
        response = requests.put(
            f"{self.base_url}/{endpoint}",
            json={"body": comment},
            headers=self.headers,
        )
        response.raise_for_status()

    def add_labels_to_mr(self, labels: list) -> None:
        """Adds labels to a GitLab merge request.

        Args:
            labels (list): List of labels to add.
        """
        logging.info(f"Adding labels {labels} to merge request #{self.data['iid']}")
        endpoint = f"merge_requests/{self.data['iid']}"
        response = requests.put(
            f"{self.base_url}/{endpoint}",
            json={"labels": ",".join(labels)},
            headers=self.headers,
        )
        response.raise_for_status()

    def delete_label_from_mr(self, label: str) -> None:
        """Removes a label from a GitLab merge request.

        Args:
            label (str): The label to remove.
        """
        logging.info(f"Removing label '{label}' from merge request #{self.data['iid']}")
        current_labels = self.data.get("labels", [])
        updated_labels = [lbl for lbl in current_labels if lbl != label]
        endpoint = f"merge_requests/{self.data['iid']}"
        response = requests.put(
            f"{self.base_url}/{endpoint}",
            json={"labels": ",".join(updated_labels)},
            headers=self.headers,
        )
        response.raise_for_status()
