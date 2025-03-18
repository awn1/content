import requests
import typer
import urllib3
from dotenv import load_dotenv
from more_itertools import always_iterable

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

load_dotenv()
DEFAULT_CI_URL = "https://gitlab.xdr.pan.local"
DEFAULT_PROJECT_ID = "1061"


def list_to_csv(value: list):
    return ",".join(always_iterable(value))


def trigger(
    ci_token: str = typer.Option(..., "-ct", envvar="CI_TOKEN", hide_input=True),
    content_config_branch: str = typer.Option(
        ..., "-cb", envvar="CONTENT_CONFIG_BRANCH", help="The content branch name with configurations to use"
    ),
    repo_path: str = typer.Option(
        ".",
        help="Path of the content repo, relative to where we're running from",
        envvar="REPO_PATH",
    ),
    pr_assignees: list[str] = typer.Option(
        ...,
        "-pra",
        "--pr-assignees",
        help="The Github assignees of the remote PR. Repeat to pass multiple values.",
        envvar="PR_ASSIGNEES",
    ),
    pr_reviewers: list[str] = typer.Option(
        ...,
        "-prr",
        "--pr-reviewers",
        envvar="PR_REVIEWERS",
        help="The Github reviewers of the remote PR. Repeat to pass multiple values.",
    ),
    commit_message: str = typer.Option(
        ...,
        "-m",
        help="The commit message referenced with the changes made by the bash command",
        envvar="COMMIT_MESSAGE",
    ),
    branch_name_infix: str = typer.Option(
        ...,
        "-bni",
        "--branch-name-infix",
        "--infix",
        help=(
            "Infix of the branch name that will hold the changes of the bash command, "
            "between the automated `packwise/` prefix and incremental suffix"
        ),
        envvar="BRANCH_NAME_INFIX",
    ),
    release_note: str = typer.Option(..., "-rn", "--release-note", help="The release note of the changes", envvar="RELEASE_NOTE"),
    pr_title: str = typer.Option(
        ...,
        "-prt",
        "--pr-title",
        help="The title of the PR",
        envvar="PR_TITLE",
    ),
    packs_per_pr: int = typer.Option(
        20,
        "-ppr",
        "--packs-per-pr",
        help="Number of packs in each automated PR",
        envvar="PACKS_PER_PR",
    ),
    packs: list = typer.Option(
        "",
        "-p",
        "--packs",
        help="Pack names to run the bash command on",
        envvar="PACKS",
        parser=lambda s: s.split(",") if s else [],
    ),
    all_packs: bool = typer.Option(
        False,
        "-a",
        "--all-packs",
        envvar="ALL_PACKS",
        help="Whether to run on all packs",
    ),
    pr_labels: list = typer.Option(None, envvar="PR_LABELS", parser=lambda s: s.split(",") if s else []),
    hooks: list = typer.Option(
        ..., help="Which pre-commit hook to run?", envvar="HOOK", parser=lambda s: s.split(",") if s else []
    ),
    ci_server_url: str = typer.Option(DEFAULT_CI_URL, envvar="CI_SERVER_URL"),
    ci_project_id: str = typer.Option(DEFAULT_PROJECT_ID, envvar="CI_PROJECT_ID"),
    infra_branch: str = typer.Option(None, "-ib", "--infra-branch", help="The infra branch to use", envvar="INFRA_BRANCH"),
):
    if not any((all_packs, packs)):
        raise ValueError("Either `all_packs` or `packs` must be provided")
    if all_packs and packs:
        raise ValueError("Cannot supply both `all packs` and `packs` arguments")

    res = requests.post(
        f"{ci_server_url}/api/v4/projects/{ci_project_id}/trigger/pipeline",
        files={"token": (None, ci_token), "ref": (None, content_config_branch)}
        | {
            f"variables[{key}]": (
                None,
                list_to_csv(value) if isinstance(value, list) else str(value),
            )  # gitlab syntax
            for key, value in {
                "PACKWISE": "true",
                "REPO_PATH": repo_path,
                "CONTENT_CONFIG_BRANCH": content_config_branch,
                "HOOK": hooks,
                "PR_ASSIGNEES": pr_assignees,
                "PR_REVIEWERS": pr_reviewers,
                "PR_LABELS": pr_labels,
                "COMMIT_MESSAGE": commit_message,
                "BRANCH_NAME_INFIX": branch_name_infix,
                "RELEASE_NOTE": release_note,
                "PR_TITLE": pr_title,
                "PACKS_PER_PR": packs_per_pr,
                "PACKS": packs,
                "ALL_PACKS": all_packs,
                "INFRA_BRANCH": infra_branch,
            }.items()
        },
        verify=False,
    )
    try:
        print(res.json()["web_url"])
    except KeyError:
        try:
            print(res.json())
        except Exception:
            print(res.content)


if __name__ == "__main__":
    typer.run(trigger)
