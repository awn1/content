import itertools
import subprocess
from pathlib import Path

import git
import typer
import urllib3
from dotenv import load_dotenv
from packaging.version import Version

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
load_dotenv(override=True)
GITLAB_BASE_BRANCH = "master"

GITLAB_BASE_URL = "https://gitlab.xdr.pan.local"
GITLAB_INFRA_URL = f"{GITLAB_BASE_URL}/xdr/cortex-content/infra"
GITLAB_GIT_URL = f"{GITLAB_INFRA_URL.removeprefix('https://')}.git"
GITLAB_INFRA_PROJECT_ID = "1701"

REMOTE_NAME = "origin"

CHANGELOG_FRAHMENTS_FOLDER = Path(".changelogs")
CHANGELOG_PATH = Path("CHANGELOG.md")
PYPROJECT_PATH = Path("pyproject.toml")

MERGE_REQUEST_LABELS = "Infra Release"

app = typer.Typer(
    pretty_exceptions_show_locals=False  # prevent printing sensitive values on error
)


repo = git.Repo()


def check_branch_doesnt_exist(repo: git.Repo, branch_name: str):
    remote = repo.git.remote(REMOTE_NAME)
    remote.fetch()

    if branch_name in {ref.name for ref in remote.refs}:
        raise ValueError(f"Branch {branch_name} already exists in remote, delete it from there.")


def create_release_branch(commit_to_release: str, version: Version) -> None:
    """
    Bumps the version, creates release notes, and commits to a branch from the given commit.
    """
    branch_name = f"infra_release_v{version}"
    title = branch_name.replace("_", " ").title()

    repo.git.checkout("-b", branch_name, commit_to_release)

    for command_parts in (
        ("poetry", "version", str(version)),  # Update version in pyptoject.toml
        ("towncrier", "build", "--version", str(version), "--yes"),  # Update Changelog
    ):
        print("running", (" ".join(command_parts)))
        try:
            print(subprocess.run(command_parts, text=True, check=True, capture_output=True).stdout)

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

    repo.git.push(
        *itertools.chain.from_iterable(
            ("-o", option)
            for option in (
                "ci.skip",
                "merge_request.create",
                f"merge_request.target={GITLAB_BASE_BRANCH}",
                f"merge_request.title={title}",
                f"merge_request.label={MERGE_REQUEST_LABELS}",
            )
        )
    )

    commit_sha = subprocess.run(("git", "rev-parse", "HEAD"), capture_output=True, text=True).stdout

    print(
        f"Pushed a new branch {branch_name}, commit sha={commit_sha}.\n"
        f"Visit {GITLAB_INFRA_URL}/-/merge_requests to see the MR.\n"
        f"After merging it, create a release in {GITLAB_INFRA_URL}/-/releases."
    )


@app.command("release")
def release(
    start_commit: str = typer.Option(
        "The commit hash to start the release from. IMPORTANT: Make sure it passed nightly before running!"
    ),
    version: Version = typer.Option("The version to release, e.g. 1.2.3", "-v", parser=Version),
):
    previous_branch = repo.active_branch.name

    try:
        create_release_branch(start_commit, version)

    finally:
        print(f"Checking out back to {previous_branch}")
        repo.git.checkout(previous_branch, "-f")


if __name__ == "__main__":
    app()
