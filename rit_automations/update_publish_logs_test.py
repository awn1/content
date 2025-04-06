from rit_automations.update_publish_logs import parse_published_file


def test_parse_published_file_success(mocker):
    """
    Given: A valid file name in PATH_SRC_BUCKET with the correct format.
    When: The parse_published_file function is called.
    Then: It returns the correct file name and commit hash.
    """
    mocker.patch("rit_automations.update_publish_logs.PATH_SRC_BUCKET", "/path/to/4.1_20250302123139_7ba8eb81_content.zip")
    mocker.patch("rit_automations.update_publish_logs.PLATFORM_VERSION", "4.1")

    file_name, commit_hash = parse_published_file()

    assert file_name == "4.1_20250302123139_7ba8eb81_content.zip"
    assert commit_hash == "7ba8eb81"


def test_parse_published_file_add_platform_version(mocker):
    """
    Given: A file name without the platform version prefix.
    When: The parse_published_file function is called.
    Then: It adds the platform version to the file name and returns the correct file name and commit hash.
    """
    mocker.patch("rit_automations.update_publish_logs.PATH_SRC_BUCKET", "/path/to/20250302123139_7ba8eb81_content.zip")
    mocker.patch("rit_automations.update_publish_logs.PLATFORM_VERSION", "4.1")

    file_name, commit_hash = parse_published_file()

    assert file_name == "4.1_20250302123139_7ba8eb81_content.zip"
    assert commit_hash == "7ba8eb81"


def test_update_merge_status_merged(mocker):
    """
    Given: A list of existing rows with a merge request that has been merged.
    When: The update_merge_status function is called.
    Then: The 'is_merged' status is updated to 'yes' for the merged MR.
    """
    from rit_automations.update_publish_logs import update_merge_status

    existing_rows = [{"merge_request_number": "123", "is_merged": "no", "merge_request_link": "https://gitlab.com/mr/123"}]
    mock_gitlab = mocker.Mock()
    mock_mr = mocker.Mock()
    mock_mr.state = "merged"
    mock_gitlab.projects.get().mergerequests.get.return_value = mock_mr
    mocker.patch("builtins.open", mocker.mock_open())
    mocker.patch("json.dump")
    update_merge_status(existing_rows, mock_gitlab)

    assert existing_rows[0]["is_merged"] == "yes"


def test_update_merge_status_pending(mocker):
    """
    Given: A list of existing rows with a merge request that is still open.
    When: The update_merge_status function is called.
    Then: The 'is_merged' status remains 'no' and the MR link is added to pending_mrs.
    """
    from rit_automations.update_publish_logs import update_merge_status

    existing_rows = [{"merge_request_number": "456", "is_merged": "no", "merge_request_link": "https://gitlab.com/mr/456"}]
    mock_gitlab = mocker.Mock()
    mock_mr = mocker.Mock()
    mock_mr.state = "opened"
    mock_gitlab.projects.get().mergerequests.get.return_value = mock_mr

    mocker.patch("builtins.open", mocker.mock_open())
    mock_json_dump = mocker.patch("json.dump")

    update_merge_status(existing_rows, mock_gitlab)

    assert existing_rows[0]["is_merged"] == "no"
    mock_json_dump.assert_called_once()


def test_update_merge_status_exception(mocker):
    """
    Given: A list of existing rows with a merge request that raises an exception when checked.
    When: The update_merge_status function is called.
    Then: The 'is_merged' status is set to 'no' and a warning is logged.
    """
    from rit_automations.update_publish_logs import update_merge_status

    existing_rows = [{"merge_request_number": "789", "is_merged": "no", "merge_request_link": "https://gitlab.com/mr/789"}]
    mock_gitlab = mocker.Mock()
    mock_gitlab.projects.get().mergerequests.get.side_effect = Exception("API Error")

    mock_logging = mocker.patch("logging.warning")
    mocker.patch("builtins.open", mocker.mock_open())
    mocker.patch("json.dump")
    update_merge_status(existing_rows, mock_gitlab)

    assert existing_rows[0]["is_merged"] == "no"
    mock_logging.assert_called_once_with("Failed to check MR-789 status: API Error")


def test_get_mr_and_branch_success(mocker):
    """
    Given: A valid commit hash and GitLab token.
    When: The get_mr_and_branch function is called.
    Then: It returns the correct branch name, merge request number, and merge request link.
    """
    from rit_automations.update_publish_logs import get_mr_and_branch

    mocker.patch("subprocess.run", side_effect=[mocker.Mock(returncode=0), mocker.Mock(stdout="origin/feature-branch")])
    mocker.patch(
        "rit_automations.update_publish_logs.GitlabMergeRequest",
        return_value=mocker.Mock(data={"iid": "123", "web_url": "https://gitlab.com/mr/123"}),
    )

    result = get_mr_and_branch("fake_token", "abcdef123")
    assert result == ("feature-branch", "123", "https://gitlab.com/mr/123")
