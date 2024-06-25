from pathlib import Path
from ruamel.yaml import YAML

INFRA_PATH = Path(__file__).parents[2]
yaml = YAML()


def test_verify_same_docker_image_slack_notify_gitlab_ci():
    """
    This test checks if gitlab-ci and slack-notify have the same image.
    IF THIS TEST FAILED, PLEASE UPDATE BOTH DOCKER IMAGES.
    """
    gitlab_ci_path = INFRA_PATH / ".gitlab" / "ci" / "content-ci" / "ci" / ".gitlab-ci.yml"
    slack_notify_path = INFRA_PATH / ".gitlab" / "ci" / "content-ci" / "ci" / ".gitlab-ci.slack-notify.yml"

    gitlab_ci_yml = yaml.load(gitlab_ci_path)
    slack_notify_yml = yaml.load(slack_notify_path)

    assert gitlab_ci_yml["default"]["image"] == slack_notify_yml["default"]["image"]
