import argparse
import requests
import urllib3

from urllib3.exceptions import InsecureRequestWarning

urllib3.disable_warnings(InsecureRequestWarning)

GITLAB_CONTENT_PIPELINES_BASE_URL = (
    "https://gitlab.xdr.pan.local/api/v4/projects/1701/pipelines/{}/jobs"
)


def get_job(pipeline: dict, job_name: str) -> dict:
    for job in pipeline:
        if job["name"] == job_name:
            return job


def is_force_merge_allowed(job: dict, allowed_force_list: list[str]) -> True:
    return job["user"]["username"] in allowed_force_list


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("-gt", "--gitlab-token", help="Gitlab token.")
    parser.add_argument("-pid", "--pipeline-id", help="The pipeline ID.")
    parser.add_argument("-jn", "--job-name", help="The job name")
    parser.add_argument(
        "-auf", "--allowed-users-force", help="List of the allowed users to force"
    )
    return parser.parse_args()


def main():
    args = parse_arguments()
    allowed_force_list = (args.allowed_users_force).strip().split("|")
    try:
        res = requests.get(
            GITLAB_CONTENT_PIPELINES_BASE_URL.format(args.pipeline_id),
            headers={"Authorization": f"Bearer {args.gitlab_token}"},
            verify=False,
        ).json()
    except Exception:
        exit(1)

    job = get_job(res, args.job_name)
    print(
        f"true,{job['user']['name']}"
        if is_force_merge_allowed(job, allowed_force_list)
        else "false"
    )


if __name__ == "__main__":
    main()
