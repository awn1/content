def test_sort_json_list():
    """
    Given: A list of dictionaries with unsorted keys.
    When: The sort_json function is called with this list.
    Then: The function returns a new list with dictionaries having sorted keys.
    """
    from rit_automations.rit_executor import sort_json

    unsorted_list = [{"b": 2, "a": 1}, {"d": 4, "c": 3}]
    expected_result = [{"a": 1, "b": 2}, {"c": 3, "d": 4}]
    assert sort_json(unsorted_list) == expected_result


def test_sort_json_nested():
    """
    Given: A nested structure of dictionaries and lists.
    When: The sort_json function is called with this nested structure.
    Then: The function returns a new structure with all levels sorted.
    """
    from rit_automations.rit_executor import sort_json

    nested_structure = {"b": [{"d": 4, "c": 3}], "a": {"f": 6, "e": 5}}
    expected_result = {"a": {"e": 5, "f": 6}, "b": [{"c": 3, "d": 4}]}
    assert sort_json(nested_structure) == expected_result


def test_load_json_safely_multiple_objects(tmp_path):
    """
    Given: A JSON file containing multiple JSON objects.
    When: The load_json_safely function is called with the file path.
    Then: The function returns a list of parsed JSON objects.
    """
    from rit_automations.rit_executor import load_json_safely

    json_file = tmp_path / "multiple.json"
    json_content = '{"key1": "value1"}\n{"key2": "value2"}'
    json_file.write_text(json_content)

    result = load_json_safely(json_file)
    assert result == [{"key1": "value1"}, {"key2": "value2"}]


def test_load_metadata_args_existing_file(tmp_path, mocker):
    """
    Given: A valid metadata.yaml file with key-value pairs.
    When: The load_metadata_args function is called with the path to this file.
    Then: The function returns a string of command-line arguments based on the metadata content.
    """
    from rit_automations.rit_executor import load_metadata_args

    metadata_content = """
    region: us-east-1
    account-type: organization
    """
    metadata_file = tmp_path / "metadata.yaml"
    metadata_file.write_text(metadata_content)

    mocker.patch("yaml.safe_load", return_value={"region": "us-east-1", "account-type": "organization"})

    result = load_metadata_args(metadata_file)
    assert result == "--region us-east-1 --account-type organization"
