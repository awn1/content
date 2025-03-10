from Tests.Marketplace.upload_marketplace_data_to_bigquery import (
    GET_ITEMS_USED_BY_PLAYBOOK_QUERY,
    GET_PLAYBOOKS_USING_ITEM_QUERY,
    NOT_RELEVANT_FIELDS,
    batch_iterable,
    enhance_content_item_with_pack_name,
    enhance_integration_data,
    enhance_playbook_items,
    enhance_playbook_usage,
    normalize_item_data,
    should_skip_item,
)


def test_should_skip_item_hidden_true():
    """
    Given:
        An item with 'hidden' property set to 'true'.
    When:
        The should_skip_item function is called with this item.
    Then:
        The function should return True, indicating the item should be skipped.
    """
    item = {"hidden": "true", "content_type": "Integration"}
    assert should_skip_item(item)


def test_should_skip_item_hidden_false():
    """
    Given:
        An item with 'hidden' property set to 'false'.
    When:
        The should_skip_item function is called with this item.
    Then:
        The function should return False, indicating the item should not be skipped.
    """
    item = {"hidden": "false", "content_type": "Script"}
    assert not should_skip_item(item)


def test_should_skip_item_test_content_type():
    """
    Given:
        An item with 'content_type' property starting with 'Test'.
    When:
        The should_skip_item function is called with this item.
    Then:
        The function should return True, indicating the item should be skipped.
    """
    item = {"content_type": "Integration", "hidden": "false"}
    assert not should_skip_item(item)


def test_should_skip_item_non_test_content_type():
    """
    Given:
        An item with 'content_type' property not starting with 'Test'.
    When:
        The should_skip_item function is called with this item.
    Then:
        The function should return False, indicating the item should not be skipped.
    """
    item = {"content_type": "IncidentType", "hidden": "false"}
    assert not should_skip_item(item)


def test_should_skip_item_hidden_not_present():
    """
    Given:
        An item without a 'hidden' property.
    When:
        The should_skip_item function is called with this item.
    Then:
        The function should return False, using the default value for 'hidden'.
    """
    item = {"content_type": "Integration"}
    assert not should_skip_item(item)


def test_enhance_content_item_pack_type(mocker):
    """
    Given:
        A content item of type "Pack".
    When:
        The enhance_content_item_with_pack_name function is called with this item.
    Then:
        The function should set the "pack" field to the item's name without querying the database.
    """
    driver_mock = mocker.Mock()
    item = {"content_type": "Pack", "name": "Pack1"}

    enhance_content_item_with_pack_name(driver_mock, item)

    assert item["pack"] == "Pack1"
    driver_mock.assert_not_called()


def test_enhance_content_item_non_pack_type_with_result(mocker):
    """
    Given:
        A content item not of type "Pack" and a database query that returns a pack name.
    When:
        The enhance_content_item_with_pack_name function is called with this item.
    Then:
        The function should set the "pack" field to the pack name returned by the database query.
    """
    driver_mock = mocker.Mock()
    mock_run_query = mocker.patch("Tests.Marketplace.upload_marketplace_data_to_bigquery.run_query")
    mock_run_query.return_value = iter([{"pack.name": "ContainingPack"}])

    item = {"content_type": "Integration", "object_id": "123"}

    enhance_content_item_with_pack_name(driver_mock, item)

    assert item["pack"] == "ContainingPack"
    mock_run_query.assert_called_once()


def test_enhance_content_item_non_pack_type_no_result(mocker):
    """
    Given:
        A content item not of type "Pack" and a database query that returns no results.
    When:
        The enhance_content_item_with_pack_name function is called with this item.
    Then:
        The function should not set the "pack" field in the item.
    """
    driver_mock = mocker.Mock()
    mock_run_query = mocker.patch("Tests.Marketplace.upload_marketplace_data_to_bigquery.run_query")
    mock_run_query.return_value = iter([])

    item = {"content_type": "Integration", "object_id": "123"}

    enhance_content_item_with_pack_name(driver_mock, item)

    assert "pack" not in item
    mock_run_query.assert_called_once()


def test_enhance_integration_data_with_commands_and_mirroring(mocker):
    """
    Given:
        An integration item with commands and mirroring capabilities.
    When:
        The enhance_integration_data function is called.
    Then:
        The item is enhanced with command names and mirroring information.
    """
    mock_driver = mocker.Mock()
    mock_run_query = mocker.patch("Tests.Marketplace.upload_marketplace_data_to_bigquery.run_query")

    mock_run_query.side_effect = [[{"c.name": "command-1"}, {"c.name": "command-2"}], [{"result": True}]]

    item = {"object_id": "123", "name": "Integration1"}

    enhance_integration_data(mock_driver, item)

    assert item["commands"] == ["command-1", "command-2"]
    assert item["has_mirroring"]
    assert mock_run_query.call_count == 2


def test_enhance_integration_data_without_mirroring(mocker):
    """
    Given:
        An integration item without mirroring capabilities.
    When:
        The enhance_integration_data function is called.
    Then:
        The item is enhanced with command names and mirroring is set to False.
    """
    mock_driver = mocker.Mock()
    mock_run_query = mocker.patch("Tests.Marketplace.upload_marketplace_data_to_bigquery.run_query")

    mock_run_query.side_effect = [[{"c.name": "command-1"}], []]

    item = {"object_id": "456", "name": "AnotherIntegration"}

    enhance_integration_data(mock_driver, item)

    assert item["commands"] == ["command-1"]
    assert not item["has_mirroring"]
    assert mock_run_query.call_count == 2


def test_enhance_integration_data_without_commands(mocker):
    """
    Given:
        An integration item without any commands.
    When:
        The enhance_integration_data function is called.
    Then:
        The item is enhanced with an empty commands list and mirroring is set to False.
    """
    mock_driver = mocker.Mock()
    mock_run_query = mocker.patch("Tests.Marketplace.upload_marketplace_data_to_bigquery.run_query")

    mock_run_query.side_effect = [[], []]

    item = {"object_id": "789", "name": "EmptyIntegration"}

    enhance_integration_data(mock_driver, item)

    assert item["commands"] == []
    assert not item["has_mirroring"]
    assert mock_run_query.call_count == 2


def test_enhance_playbook_usage_with_playbooks(mocker):
    """—
    Given:
        A driver mock and an item dictionary.
    When:
        The enhance_playbook_usage function is called with playbooks using the item.
    Then:
        The item dictionary is updated with the correct 'used_in_playbooks' list.
    """
    mock_driver = mocker.Mock()
    mock_run_query = mocker.patch("Tests.Marketplace.upload_marketplace_data_to_bigquery.run_query")
    mock_run_query.return_value = [{"p.name": "Playbook1"}, {"p.name": "Playbook2"}]

    item = {"content_type": "Integration", "object_id": "test_id"}
    enhance_playbook_usage(mock_driver, item)

    mock_run_query.assert_called_once_with(
        mock_driver, GET_PLAYBOOKS_USING_ITEM_QUERY.format(content_type="Integration", object_id="test_id")
    )
    assert item["used_in_playbooks"] == ["Playbook1", "Playbook2"]


def test_enhance_playbook_usage_without_playbooks(mocker):
    """
    Given:
        A driver mock and an item dictionary.
    When:
        The enhance_playbook_usage function is called with no playbooks using the item.
    Then:
        The item dictionary is updated with an empty 'used_in_playbooks' list.
    """
    mock_driver = mocker.Mock()
    mock_run_query = mocker.patch("Tests.Marketplace.upload_marketplace_data_to_bigquery.run_query")
    mock_run_query.return_value = []

    item = {"content_type": "Script", "object_id": "script-id"}
    enhance_playbook_usage(mock_driver, item)

    mock_run_query.assert_called_once_with(
        mock_driver, GET_PLAYBOOKS_USING_ITEM_QUERY.format(content_type="Script", object_id="script-id")
    )
    assert item["used_in_playbooks"] == []


def test_enhance_playbook_usage_query_formatting(mocker):
    """
    Given:
        A driver mock and an item dictionary.
    When:
        The enhance_playbook_usage function is called.
    Then:
        The query is formatted correctly with the item's content_type and object_id.
    """
    mock_driver = mocker.Mock()
    mock_run_query = mocker.patch("Tests.Marketplace.upload_marketplace_data_to_bigquery.run_query")
    mock_run_query.return_value = []

    item = {"content_type": "Command", "object_id": "command-id"}
    enhance_playbook_usage(mock_driver, item)

    expected_query = GET_PLAYBOOKS_USING_ITEM_QUERY.format(content_type="Command", object_id="command-id")
    mock_run_query.assert_called_once_with(mock_driver, expected_query)


def test_enhance_playbook_items(mocker):
    """
    Given:
        A playbook item and a mocked Neo4j driver.
    When:
        The enhance_playbook_items function is called.
    Then:
        The playbook item is enhanced with the correct 'used_by_playbook' information.
    """
    # Mock the driver and run_query function
    mock_driver = mocker.Mock()
    mock_run_query = mocker.patch("Tests.Marketplace.upload_marketplace_data_to_bigquery.run_query")

    # Set up the mock return value
    mock_run_query.return_value = [
        {"item.name": "Item1", "item.content_type": "Integration", "item.object_id": "id-1"},
        {"item.name": "Item2", "item.content_type": "Script", "item.object_id": "id-2"},
    ]

    # Sample playbook item
    playbook_item = {"object_id": "pb-1"}

    enhance_playbook_items(mock_driver, playbook_item)

    assert "used_by_playbook" in playbook_item
    assert len(playbook_item["used_by_playbook"]) == 2
    assert playbook_item["used_by_playbook"][0] == "Item1, Integration, id-1"
    assert playbook_item["used_by_playbook"][1] == "Item2, Script, id-2"

    # Verify that run_query was called with the correct parameters
    mock_run_query.assert_called_once_with(mock_driver, GET_ITEMS_USED_BY_PLAYBOOK_QUERY.format(object_id="pb-1"))


def test_enhance_playbook_items_empty_result(mocker):
    """
    Given:
        A playbook item and a mocked Neo4j driver that returns no results.
    When:
        The enhance_playbook_items function is called.
    Then:
        The playbook item is enhanced with an empty 'used_by_playbook' list.
    """
    # Mock the driver and run_query function
    mock_driver = mocker.Mock()
    mock_run_query = mocker.patch("Tests.Marketplace.upload_marketplace_data_to_bigquery.run_query")

    mock_run_query.return_value = []

    # Sample playbook item
    playbook_item = {"object_id": "pb-1"}

    enhance_playbook_items(mock_driver, playbook_item)

    assert "used_by_playbook" in playbook_item
    assert playbook_item["used_by_playbook"] == []

    # Verify that run_query was called with the correct parameters
    mock_run_query.assert_called_once_with(mock_driver, GET_ITEMS_USED_BY_PLAYBOOK_QUERY.format(object_id="pb-1"))


def test_normalize_item_data_removes_not_relevant_fields():
    """
    Given:
        An item dictionary containing both relevant and not relevant fields.
    When:
        The normalize_item_data function is called with this dictionary.
    Then:
        The function should remove all fields listed in NOT_RELEVANT_FIELDS from the dictionary.
    """
    item = {
        "name": "MyIntegration",
        "content_type": "Integration",
        "updated": "2023-05-01",  # This field should be removed
        "version": 1,
    }
    expected_item = {"name": "MyIntegration", "content_type": "Integration", "version": 1}

    normalize_item_data(item)

    assert item == expected_item
    for field in NOT_RELEVANT_FIELDS:
        assert field not in item


def test_normalize_item_data_does_not_remove_relevant_fields():
    """
    Given:
        A content item dictionary containing only relevant fields.
    When:
        The normalize_item_data function is called with this dictionary.
    Then:
        The function should not modify the dictionary.
    """
    item = {"name": "Playbook", "content_type": "Playbook", "version": 2}
    expected_item = item.copy()
    normalize_item_data(item)
    assert item == expected_item


def test_batch_iterable_normal_batching():
    """
    Given:
        An iterable of 10 dictionaries and a batch size of 3.
    When:
        The batch_iterable function is called.
    Then:
        It should yield 4 batches, with the last batch containing the remaining elements.
    """
    data = [{"id": i, "value": f"item_{i}"} for i in range(10)]
    batches = list(batch_iterable(data, batch_size=3))
    assert len(batches) == 4
    assert batches == [
        [{"id": 0, "value": "item_0"}, {"id": 1, "value": "item_1"}, {"id": 2, "value": "item_2"}],
        [{"id": 3, "value": "item_3"}, {"id": 4, "value": "item_4"}, {"id": 5, "value": "item_5"}],
        [{"id": 6, "value": "item_6"}, {"id": 7, "value": "item_7"}, {"id": 8, "value": "item_8"}],
        [{"id": 9, "value": "item_9"}],
    ]


def test_batch_iterable_small_iterable():
    """
    Given:
        An iterable smaller than the batch size.
    When:
        The batch_iterable function is called.
    Then:
        It should yield a single batch containing all elements.
    """
    data = [{"id": 1, "value": "item_1"}, {"id": 2, "value": "item_2"}]
    batches = list(batch_iterable(data, batch_size=5))
    assert len(batches) == 1
    assert batches == [[{"id": 1, "value": "item_1"}, {"id": 2, "value": "item_2"}]]


def test_batch_iterable_empty_iterable():
    """
    Given:
        An empty iterable.
    When:
        The batch_iterable function is called.
    Then:
        It should yield no batches.
    """
    data = []
    batches = list(batch_iterable(data))
    assert len(batches) == 0


def test_batch_iterable_custom_batch_size():
    """
    Given:
        An iterable of 20 dictionaries and a custom batch size of 7.
    When:
        The batch_iterable function is called.
    Then:
        It should yield 3 batches, with the last batch containing the remaining elements.
    """
    data = [{"id": i, "value": f"item_{i}"} for i in range(20)]
    batches = list(batch_iterable(data, batch_size=7))
    assert len(batches) == 3
    assert batches == [
        [{"id": i, "value": f"item_{i}"} for i in range(7)],
        [{"id": i, "value": f"item_{i}"} for i in range(7, 14)],
        [{"id": i, "value": f"item_{i}"} for i in range(14, 20)],
    ]


def test_batch_iterable_batch_size_larger_than_iterable():
    """
    Given:
        An iterable smaller than the specified batch size.
    When:
        The batch_iterable function is called.
    Then:
        It should yield a single batch containing all elements.
    """
    data = [{"id": i, "value": f"item_{i}"} for i in range(5)]
    batches = list(batch_iterable(data, batch_size=10))
    assert len(batches) == 1
    assert batches == [[{"id": i, "value": f"item_{i}"} for i in range(5)]]
