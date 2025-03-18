import itertools
import json
import os
import re
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from pprint import pformat
from time import strftime

import github  # PyGithub
import github.Repository
import typer
import urllib3
from dotenv import load_dotenv  # python-dotenv
from git import Repo  # GitPython
from loguru import logger
from more_itertools import batched, map_reduce
from pathspec import PathSpec

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

load_dotenv()
app = typer.Typer(no_args_is_help=True)

logger.add(sys.stdout, level="INFO", backtrace=False)
logger.add(os.environ["LOG_PATH"], level="DEBUG", backtrace=False)


ORG_NAME = "demisto"
REPO_NAME = "content"
IGNORED_FOLDERS = {"venv", ".venv", "test_data"}
MASTER_BRANCH_NAME = "master"
PACKWISE_BRANCH_PREFIX = "packwise"
MAX_OPEN_PACKWISE_BRANCHES = 40
PACKWISE_PR_LABEL = "packwise"


class PullRequestCreator:
    def __init__(
        self,
        repo_path: Path,
        pr_assignees: list[str],
        pr_reviewers: list[str],
        commit_message: str,
        branch_name_infix: str,  # middle part, between packwise/ and the count
        release_note: str,
        pr_title: str,
        github_repo: github.Repository.Repository,
        github_token: str,
        pr_labels: list[str],
    ) -> None:
        self.repo_path = repo_path
        self.pr_assignees = sorted(pr_assignees)
        self.pr_reviewers = sorted(pr_reviewers)
        self.commit_message = commit_message
        self.branch_name_prefix = strftime(f"{PACKWISE_BRANCH_PREFIX}/{branch_name_infix}-%m%dT%H%M")
        self.release_note = release_note

        # PR attributes
        self.pr_title = pr_title
        self.pr_labels = pr_labels

        # Git
        self.git_repo = Repo(f"{self.repo_path}/.")

        self.git_ignore_spec = PathSpec.from_lines(
            "gitwildmatch",
            Path(f"{self.repo_path}/.gitignore").read_text().splitlines(),
        )

        # GitHub
        self.github_repo = github_repo
        github_url = self.github_repo.git_url.removeprefix("git://").removesuffix(".git")
        self.remote_url = f"https://packwise:{github_token}@{github_url}.git"

    def calculate_branch_allowance(self) -> int:
        logger.debug(f"{MAX_OPEN_PACKWISE_BRANCHES=}")

        if branch_count_allowance := (MAX_OPEN_PACKWISE_BRANCHES - _count_existing_packwise_branches(self.github_repo)):
            # Number of branches we may open in this run, before hitting MAX_OPEN_PACKWISE_BRANCHES, to save some build resources)
            logger.info(f"Can open up to {branch_count_allowance} branches before reaching {MAX_OPEN_PACKWISE_BRANCHES=}")
        else:
            logger.error(f"We reached {MAX_OPEN_PACKWISE_BRANCHES} open packwise branches. Delete them to proceed.")
            raise typer.Exit(1)
        return branch_count_allowance

    def unstage_packs_directory(self, staged_files: set[Path]) -> None:
        try:
            logger.debug(f"unstage_packs_directory len = {len(staged_files)}")
            for file in staged_files:
                self.git_repo.git.reset("HEAD", file)
            logger.debug("Successfully unstaged all staged files under the Packs directory")
        except Exception as e:
            logger.error(f"Exception occurred while unstaging files: {e}")

    def run(self, packs_per_pr: int) -> None:
        branch_count_allowance = self.calculate_branch_allowance()
        staged_files = {self.repo_path / file.a_path for file in self.git_repo.index.diff("HEAD")}
        pack_to_modified_files: dict = map_reduce(
            filter_files_under_packs(tuple(staged_files)),
            find_pack_name,
        )
        logger.debug(pformat(pack_to_modified_files))
        self.unstage_packs_directory(staged_files)  # unstage changes to split PRs

        total_packs = len(pack_to_modified_files)
        total_batches = (total_packs + packs_per_pr - 1) // packs_per_pr  # Calculate the total number of batches
        branches_to_open = min(total_batches, branch_count_allowance)
        ignored_packs = total_packs - (branches_to_open * packs_per_pr)

        logger.info(f"Total packs: {total_packs}")
        logger.info(f"Total branches to open: {branches_to_open}")
        logger.info(f"Total packs to be ignored: {ignored_packs}")
        for batch_index, batch in tuple(enumerate(batched(pack_to_modified_files.keys(), packs_per_pr)))[:branch_count_allowance]:
            logger.debug(f"Batch #{batch_index}")

            batch_branch_name = f"{self.branch_name_prefix}-{batch_index}"
            self._create_branch(batch_branch_name)

            for pack in batch:
                logger.debug(f"{pack=}: starting")
                pack_modified_files = pack_to_modified_files[pack]
                logger.debug(f"{pack} modified files: {pformat(pack_modified_files)}")

                self.git_repo.index.add(pack_modified_files)
                self.git_repo.index.commit(message=f"{pack}: {self.commit_message}", skip_hooks=True)
                logger.success(f"{pack}: Committed {len(pack_modified_files)} files")

            self.git_repo.git.push("--set-upstream", self.remote_url, batch_branch_name)
            self._create_remote_pr(index=batch_index)

    def _create_branch(self, branch_name: str) -> None:
        try:
            git_remote = subprocess.run(["git", "remote", "-v"], capture_output=True, text=True)
            if git_remote.returncode == 0:
                logger.debug(f"Git remote information:\n{git_remote.stdout}")
            else:
                logger.error(f"Failed to retrieve Git remote information:\n{git_remote.stderr}")
                raise Exception("Failed to retrieve Git remote information")

            self.git_repo.git.checkout(
                MASTER_BRANCH_NAME,
                [file.path for file in self.git_repo.tree().traverse() if "Packs" not in Path(file.path).parts],
                "--force",
            )
            logger.debug(f"Checked out {MASTER_BRANCH_NAME}")

            self.git_repo.git.checkout("-b", branch_name, MASTER_BRANCH_NAME)
            logger.debug(f"Checked out {branch_name} from {MASTER_BRANCH_NAME}")
        except Exception as e:
            logger.error(f"Failed to create and checkout branch {branch_name}: {e}")
            raise

    def _create_remote_pr(self, index: int):
        try:
            logger.debug("Creating pull request")
            pr = self.github_repo.create_pull(
                title=f"{self.pr_title} ({index})",
                body=self.release_note,
                base=MASTER_BRANCH_NAME,
                head=f"{self.branch_name_prefix}-{index}",
                draft=False,
            )

            pr.create_review_request(reviewers=self.pr_reviewers)
            logger.info(f'Requested review from {",".join(self.pr_reviewers)}')

            pr.add_to_assignees(*self.pr_assignees)
            logger.info(f'Assigned to {",".join(self.pr_assignees)}')

            list_labels = self.pr_labels[0].split(",") if self.pr_labels else []
            list_labels.append(PACKWISE_PR_LABEL)
            logger.info(f"Applying labels: {', '.join(list_labels)}")
            pr.set_labels(*list_labels)
            # Extract the number using regex
            number = re.search(r"/(\d+)$", pr.issue_url).group(1)  # type: ignore[union-attr]
            logger.success(f"Created https://github.com/demisto/content/pull/{number}")
        except Exception as e:
            logger.error(f"Failed to create pull request: {e}")
            raise


def filter_files_under_packs(paths: Sequence[Path]) -> list[Path]:
    return list(filter(lambda path: "Packs" in path.parts, paths))


def find_pack_name(path: Path) -> str:
    if "Packs" not in path.parts:
        raise ValueError(f"{path!s} is not under a `Packs` folder")
    return path.parts[path.parts.index("Packs") + 1]


def list_all_xsoar_supported_packs(repo_path: Path) -> list[str]:
    # TODO CIAC-12756 take list of support levels as argument (add to typer & Runner too)
    supported_packs = []
    packs_path = repo_path / "Packs"

    for pack_dir in packs_path.iterdir():
        if pack_dir.is_dir():
            pack_metadata_path = pack_dir / "pack_metadata.json"
            if pack_metadata_path.exists():
                with open(pack_metadata_path) as f:
                    pack_metadata = json.load(f)
                    if pack_metadata.get("support") == "xsoar":
                        supported_packs.append(pack_dir.name)

    return sorted(supported_packs)


def csv_parser(string: str | None) -> list[str]:
    raw_list = (string or "").split(",")  # may be ['']
    return list(filter(None, raw_list))  # turns [''] into []


@app.command("push")
def create_pull_requests(
    repo_path: Path = typer.Option(
        ...,
        help="Path of the content repo",
        envvar="REPO_PATH",
        file_okay=False,
        dir_okay=True,
        exists=True,
    ),
    pr_assignees: list[str] = typer.Option(
        ...,
        help="Github assignees for the remote PR. Repeat to pass multiple values.",
        envvar="PR_ASSIGNEES",
    ),
    pr_reviewers: list[str] = typer.Option(
        ...,
        envvar="PR_REVIEWERS",
        help="Github reviewers for the remote PR. Repeat to pass multiple values.",
    ),
    commit_message: str = typer.Option(..., envvar="COMMIT_MESSAGE"),
    branch_name_infix: str = typer.Option(
        ...,
        help=(
            "Infix of the branch name that will hold the changes of the bash command, "
            "between the automated `packwise/` prefix and incremental suffix"
        ),
        envvar="BRANCH_NAME_INFIX",
    ),
    release_note: str = typer.Option(..., help="Release notes to add", envvar="RELEASE_NOTE"),
    pr_title: str = typer.Option(..., help="Title of the PR", envvar="PR_TITLE"),
    packs_per_pr: int = typer.Option(
        20,
        "-ppr",
        "--pack-per-pr",
        help="Number of packs in each automated PR",
        envvar="PACKS_PER_PR",
    ),
    pr_labels: list[str] = typer.Option(None, envvar="PR_LABELS"),
    github_token: str = typer.Option(..., envvar="GITHUB_TOKEN"),
) -> None:
    PullRequestCreator(
        repo_path=repo_path,
        pr_assignees=pr_assignees,
        pr_reviewers=pr_reviewers,
        commit_message=commit_message,
        branch_name_infix=branch_name_infix,
        release_note=release_note,
        pr_title=pr_title,
        pr_labels=pr_labels,
        github_token=github_token,
        github_repo=github.Github(github_token, verify=False).get_repo(f"{ORG_NAME}/{REPO_NAME}"),
    ).run(packs_per_pr=packs_per_pr)


@app.command("pre-commit")
def run_pre_commit(
    repo_path: Path = typer.Option(
        ...,
        help="The path of the repo",
        envvar="REPO_PATH",
        file_okay=False,
        dir_okay=True,
        exists=True,
        resolve_path=True,
    ),
    packs: list = typer.Option(
        "",
        "--packs",
        help="Pack names to run the bash command on",
        envvar="PACKS",
        parser=csv_parser,
    ),
    all_packs: bool = typer.Option(False, "-a", "--all-packs", envvar="ALL_PACKS"),
    hooks: str = typer.Option(..., help="Which pre-commit hook to run?", envvar="HOOK"),
):
    """
    Calls pre-commit with the right arguments
    """
    logger.info(f"{hooks=}, {all_packs=}, {packs=}")
    if all_packs:
        packs = list_all_xsoar_supported_packs(repo_path)

    args = list(itertools.chain.from_iterable(("-i", f"{(repo_path/'Packs'/pack)!s}") for pack in packs))
    hooks = hooks.split(",")
    logger.info(f"Running pre-commit hooks: {hooks}")
    for hook in hooks:
        logger.debug(f"Running pre-commit hook: {hook}")
        command = ["demisto-sdk", "pre-commit", *args, hook]
        subprocess.run(command)
        logger.debug(command)

    """
    Not passing `check=True`, because pre-commit returns 1 when fixing files.
    We decided, instead of putting effort into telling whether pre-commit failed or fixed files, to let this one fail.
    Worst case, we'll catch the errors in the next steps of the packwise workflow.
    """


def _count_existing_packwise_branches(github_repo: github.Repository.Repository) -> int:
    existing_packwise_branch_names = sorted(
        [branch.name for branch in github_repo.get_branches() if branch.name.startswith(f"{PACKWISE_BRANCH_PREFIX}/")]
    )

    logger.info(
        f"Found {len(existing_packwise_branch_names)} open packwise branches in GitHub: "
        + ",".join(existing_packwise_branch_names)
    )
    return len(existing_packwise_branch_names)


if __name__ in ("__main__", "__builtin__", "builtins"):
    app()
