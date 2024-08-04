import itertools
import os
import subprocess
import time
from pathlib import Path
from pprint import pprint
from tempfile import NamedTemporaryFile

import git
import gitlab
import typer
import urllib3
from dotenv import load_dotenv
from gitlab.v4.objects.projects import Project
from more_itertools import one
from packaging.version import Version
from tqdm import tqdm

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
load_dotenv(override=True)
GITLAB_BASE_URL = "https://gitlab.xdr.pan.local"
GITLAB_BASE_BRANCH = "master"
GITLAB_GIT_URL = f"{GITLAB_BASE_URL.removeprefix('https://')}/xdr/cortex-content/infra.git"
DEFAULT_PROJECT_ID = "1701"

POLL_SLEEP_DURATION_S = 10
POLL_MAX_SLEEP_S = 120


CHANGELOG_FRAHMENTS_FOLDER = Path(".changelogs")
CHANGELOG_PATH = Path("CHANGELOG.md")
PYPROJECT_PATH = Path("pyproject.toml")

TMP_RELEASE_NOTES_PATH = Path(NamedTemporaryFile("w+").name)
MERGE_REQUEST_LABELS = "infra_release"

app = typer.Typer(
    pretty_exceptions_show_locals=False,  # prevent printing sensitive values on error
)


repo = git.Repo()


def login_gitlab(project_id: str, gitlab_token: str) -> Project:
    return gitlab.Gitlab(
        url=GITLAB_BASE_URL,
        private_token=gitlab_token,
        ssl_verify=bool(os.getenv("CI")),
    ).projects.get(id=project_id)


def create_release_branch(
    project: Project,
    commit_to_release: str,
    version: Version,
    assignee: str,
    gitlab_push_token: str,
) -> str:
    """
    Bumps the version, creates release notes, and commits to a branch from the given commit.
    """
    branch_name = f"infra_release_v{version}"
    title = branch_name.replace("_", " ").title().replace(" V", " v")

    if project.branches.list(search=branch_name):
        raise ValueError(f"Branch {branch_name} already exists in remote, delete it.")

    repo.git.checkout("-b", branch_name, commit_to_release)  # new branch from commit_to_release

    for command_parts in (
        ("poetry", "version", str(version)),  # Update version in pyptoject.toml
        ("towncrier", "build", "--version", str(version), "--yes"),  # Update Changelog
    ):
        print("running", (command_str := " ".join(command_parts)))
        try:
            print(
                subprocess.run(
                    command_parts,
                    text=True,
                    check=True,
                    capture_output=True,
                ).stdout
            )
            print("Done", command_str)

        except subprocess.CalledProcessError as e:
            print(f"{e.returncode=}")
            print(f"{e.output=}")
            print(f"{e.stderr=}")
            print(f"{e.stdout=}")
            raise

    repo.git.add(
        str(CHANGELOG_PATH),  # update changelog
        str(PYPROJECT_PATH),  # update version in pyproject
        f"{CHANGELOG_FRAHMENTS_FOLDER}/*",  # remove old fragments
    )
    repo.git.commit("-m", title)
    push_options = itertools.chain.from_iterable(
        ("-o", option)
        for option in (
            "ci.skip",
            "merge_request.create",
            f"merge_request.target={GITLAB_BASE_BRANCH}",
            f"merge_request.title={title}",
            f"merge_request.label={MERGE_REQUEST_LABELS}",
            f"merge_request.assign={assignee}",
        )
    )
    repo.git.push(
        "--set-upstream",
        f"https://gitlab-ci-token:{gitlab_push_token}@{GITLAB_GIT_URL}",
        *push_options,
    )
    commit_sha = subprocess.run(("git", "rev-parse", "HEAD"), capture_output=True, text=True).stdout
    print(f"pushed {commit_sha} successfully to new branch {branch_name}")
    return commit_sha


def create_gitlab_release(project: Project, release_commit: str, version: Version):
    """Creates a GitLab Release for a commit hash"""
    if not (mrs := project.mergerequests.list(state="opened", labels=MERGE_REQUEST_LABELS)):
        raise ValueError(f"Cannot find an open MR with labels={MERGE_REQUEST_LABELS}")

    mr = one(
        mrs,
        too_short=IndexError(f"Cannot find an open MR with the {MERGE_REQUEST_LABELS} label"),
        too_long=IndexError(f"Found {len(mrs)}>1 MRs with the {MERGE_REQUEST_LABELS} label"),
    )
    # Poll until approved
    mr_id = mr.attributes["iid"]  # iid is not a typo

    print(f"MR ID: {mr_id}")
    print(f"MR URL: {mr.attributes['web_url']}")

    for _ in tqdm(tuple(range(POLL_MAX_SLEEP_S // POLL_SLEEP_DURATION_S))):
        pprint(mr.asdict())  # TODO remove
        if (state := mr.attributes.get("approval_state")) != "approved":
            print(
                f"MR #{mr_id} has {state=}"  # type:ignore[union-attr]
                f"sleeping {POLL_SLEEP_DURATION_S}s hoping it's `approved` by the next iteration"
            )
            time.sleep(POLL_SLEEP_DURATION_S)

    project.releases.create(
        {
            "name": f"Release v{version}",
            "ref": release_commit,
            "tag_name": f"v{version}",
            "description": TMP_RELEASE_NOTES_PATH.read_text(),
        }
    )
    print("Created release succesfully!")


@app.command("release")
def release(
    gitlab_project_id: str = typer.Option(DEFAULT_PROJECT_ID, envvar="CI_PROJECT_ID"),
    gitlab_token: str = typer.Option(envvar="GITLAB_CONTENT_CANCEL_TOKEN"),
    start_commit: str = typer.Option(),
    version: Version = typer.Option(..., "-v", envvar="RELEASE_VERSION", parser=Version),
    assignee: str = typer.Option(envvar="RELEASE_MR_ASSIGNEE"),
    gitlab_push_token: str = typer.Option(envvar="GITLAB_PUSH_TOKEN"),
):
    previous_branch = repo.active_branch.name

    try:
        project = login_gitlab(gitlab_project_id, gitlab_token)
        release_commit = create_release_branch(project, start_commit, version, assignee, gitlab_push_token)
        create_gitlab_release(project, release_commit, version)

    finally:
        print(f"Checking out back to {previous_branch}")
        repo.git.checkout(previous_branch, "-f")


if __name__ == "__main__":
    app()
