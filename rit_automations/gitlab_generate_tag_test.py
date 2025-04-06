import os

from freezegun import freeze_time

import rit_automations


@freeze_time("2020-11-04T13:34:14.75Z")
def test_generate_changelog_with_branches(mocker):
    """
    Given: A list of branches, a platform version, and a GitLab token.
    When: The generate_changelog function is called with these parameters.
    Then: It returns correctly formatted Markdown and Slack changelogs.
    """
    from rit_automations.gitlab_generate_tag import generate_changelog

    mocker.patch("rit_automations.gitlab_generate_tag.GitlabMergeRequest")

    branches = ["branch1", "branch2"]
    platform_version = "1.0.0"
    gitlab_token = "dummy_token"

    mock_mr_data = {"title": "Test MR", "author": {"username": "test_user"}, "web_url": "http://test.url"}
    rit_automations.gitlab_generate_tag.GitlabMergeRequest.return_value.data = mock_mr_data

    markdown_changelog, slack_changelog = generate_changelog(branches, platform_version, gitlab_token)

    expected_markdown = (
        "# Release 1.0.0 (2020-11-04-13-34)\n- [Test MR](http://test.url) by @test_user\n- [Test MR]("
        "http://test.url) by @test_user"
    )
    expected_slack = (
        "*Release 1.0.0 (2020-11-04-13-34)*\n• <http://test.url|Test MR> by @test_user\n• <http://test.url|Test MR> by @test_user"
    )

    assert markdown_changelog == expected_markdown
    assert slack_changelog == expected_slack


@freeze_time("2020-11-04T13:34:14.75Z")
def test_push_new_tag_success(mocker):
    """
    Given: A platform version, changelog, and GitLab token.
    When: The push_new_tag function is called with these parameters.
    Then: A new tag and release are created successfully in GitLab.
    """
    from rit_automations.gitlab_generate_tag import push_new_tag

    # Mock GitLab API interactions
    mock_gitlab = mocker.patch("gitlab.Gitlab")
    mock_project = mock_gitlab.return_value.projects.get.return_value

    # Set up test parameters
    platform_version = "1.0.0"
    changelog = "Test changelog"
    gitlab_token = "test_token"
    tag = (
        f"v{platform_version}_20201104133414"
        if os.getenv("CI_COMMIT_REF_NAME", "master") == "master"
        else f"hf{platform_version}_20201104133414"
    )

    # Call the function
    push_new_tag(platform_version, changelog, gitlab_token)

    # Assert that the GitLab API was called correctly
    mock_gitlab.assert_called_once_with(mocker.ANY, private_token=gitlab_token)
    mock_project.tags.create.assert_called_once_with(
        {
            "tag_name": tag,
            "ref": os.getenv("CI_COMMIT_SHA"),
        }
    )
    mock_project.releases.create.assert_called_once_with(
        {
            "name": f"Release {tag}",
            "tag_name": tag,
            "description": changelog,
        }
    )
