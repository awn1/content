from pathlib import Path

from Tests.sdk_release.create_content_pr import SLACK_MERGE_PRS_FILE
from Tests.sdk_release.update_sdk_v_in_infra import create_slack_message


def test_create_slack_message():
    infra_mr_number = 1
    infra_mr_link = "{infra_mr_link}"
    slack_merge_prs_file = Path(SLACK_MERGE_PRS_FILE)
    old_message = "Please merge the demisto-sdk and content pull requests:\n{sdk_pr}\n{content_pr}"
    slack_merge_prs_file.write_text(old_message)
    create_slack_message("", infra_mr_number, infra_mr_link)
    result_slack_message = slack_merge_prs_file.read_text()
    expected_message = (
        "Please merge the demisto-sdk and content pull requests as well as the Infra merge request:\n"
        "{sdk_pr}\n{content_pr}\n{infra_mr_link}"
    )
    assert result_slack_message == expected_message
