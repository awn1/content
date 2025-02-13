from Tests.scripts.gitlab_slack_notifier import auto_close_results_to_slack_msg


def test_auto_close_results_to_slack_msg():
    """
    Given:
        - A set of strings representing auto-close logs formatted as log entries.

    When:
        - Calling the `auto_close_results_to_slack_msg` function with a set of log entries.

    Then:
        - Assert that the function correctly formats the logs into a Slack message.
        - Validate that the formatted message includes all log entries, each on a new line,
          under the "Auto Close Label" heading.
    """
    auto_close_logs_playbooks = {
        "runs with auto-close": {"test_playbook_1": {"url": "link1", "key": "key1"}},
        "failed runs with auto-close": {"test_playbook_2": {"url": "link2", "key": "key2"}},
        "closed tickets after successful runs": {"test_playbook_3": {"url": "link3", "key": "key3"}},
    }
    auto_close_logs_modeling_rules = {
        "runs with auto-close": {"modeling_rule_1": {"url": "link1", "key": "key1"}},
        "failed runs with auto-close": {"modeling_rule_2": {"url": "link2", "key": "key2"}},
        "closed tickets after successful runs": {"modeling_rule_3": {"url": "link3", "key": "key3"}},
    }

    result = auto_close_results_to_slack_msg(auto_close_logs_playbooks, auto_close_logs_modeling_rules)
    assert result[0]["fallback"] == "Auto Close Playbooks"
    assert result[0]["fields"][0]["title"] == "runs with auto-close"
    assert result[0]["fields"][0]["value"] == "<link1|test_playbook_1 [key1]>"
    assert result[0]["fields"][1]["title"] == "failed runs with auto-close"
    assert result[0]["fields"][1]["value"] == "<link2|test_playbook_2 [key2]>"
    assert result[0]["fields"][2]["title"] == "closed tickets after successful runs"
    assert result[0]["fields"][2]["value"] == "<link3|test_playbook_3 [key3]>"
    assert result[1]["fallback"] == "Auto Close Modeling Rules"
    assert result[1]["fields"][0]["title"] == "runs with auto-close"
    assert result[1]["fields"][0]["value"] == "<link1|modeling_rule_1 [key1]>"
    assert result[1]["fields"][1]["title"] == "failed runs with auto-close"
    assert result[1]["fields"][1]["value"] == "<link2|modeling_rule_2 [key2]>"
    assert result[1]["fields"][2]["title"] == "closed tickets after successful runs"
    assert result[1]["fields"][2]["value"] == "<link3|modeling_rule_3 [key3]>"
