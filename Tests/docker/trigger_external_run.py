import argparse
import json

import requests


def trigger_pipeline(commit, branch, token, external):
    url = "https://gitlab.xdr.pan.local/api/v4/projects/1673/trigger/pipeline?"
    url += (
        f"token={token}&ref=main&variables[FORKED_REPO]={str(external).lower()}"
        f"&variables[GH_COMMIT]={commit}&variables[GH_BRANCH]={branch}"
    )
    response = requests.request("POST", url, verify=False)

    res = json.loads(response.text)
    print(json.dumps(res, indent=2))


def get_commit_number(commit, branch, external):
    if commit.lower() != "last":
        return commit
    base_url = "https://api.github.com"
    endpoint = "pulls" if external else "commits"
    url = f"{base_url}/repos/demisto/dockerfiles/{endpoint}/{branch}"
    headers = {"Accept": "application/vnd.github.v3+json"}

    response = requests.get(url, headers=headers, verify=False)
    if response.status_code == 200:
        commit = response.json()["head"]["sha"] if external else response.json()["sha"]
        print(f"last commit was {commit}")
        return commit
    else:
        raise ValueError(f"Failed to get the last commit. Response: {response.text}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--pr", help="The number of the external pull request, eg. 22334. If internal, the name of the branch", required=True
    )
    parser.add_argument(
        "--commit", help='Path to the folder containing reports. "last" will fetch the latest commit', default="last"
    )
    parser.add_argument("--token", help="The gitlab token needed to trigger the pipeline", required=True)
    parser.add_argument("--external", help="Whether the triggered pr is an external pr.", default="True")
    args = parser.parse_args()

    external = args.external.capitalize() == "True"
    if external and not args.pr.isnumeric():
        raise ValueError("External prs must be an int.")

    branch = f"pull/{args.pr}" if external else args.pr

    commit = get_commit_number(args.commit, args.pr, external)

    return trigger_pipeline(commit, branch, args.token, external)


if __name__ in ("__main__", "__builtin__", "builtins"):
    main()
