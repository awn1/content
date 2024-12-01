import json

import yaml

from Pipelines.override_content.add_packid_to_content_items import (
    adding_pack_id_to_file,
    options_handler,
)


def test_validate_content_items_marketplace_paths_yml_file():
    """
    Given: args with valid integration path - yml file
    When: Running adding_pack_id_to_file().
    Then: Ensure the command wrote the correct data to the file, and then empties the file content.
    """

    args = [
        "--paths",
        "Tests/scripts/infrastructure_tests/tests_data/yml_file_for_testing.yml",
    ]
    options = options_handler(args=args)

    adding_pack_id_to_file(options)

    with open("Tests/scripts/infrastructure_tests/tests_data/yml_file_for_testing.yml") as file:
        data = yaml.safe_load(file)  # reads the file content

    with open("Tests/scripts/infrastructure_tests/tests_data/yml_file_for_testing.yml", "w") as file:
        yaml.dump({"test": "test"}, file)  # resets the file

    assert data["contentitemexportablefields"]["contentitemfields"]["packID"] == "scripts"


def test_validate_content_items_marketplace_paths_json_file():
    """
    Given: args with valid integration path - json file
    When: Running adding_pack_id_to_file().
    Then: Ensure the command wrote the correct data to the file, and then empties the file content.
    """

    args = [
        "--paths",
        "Tests/scripts/infrastructure_tests/tests_data/json_file_for_testing.json",
    ]
    options = options_handler(args=args)

    adding_pack_id_to_file(options)

    with open("Tests/scripts/infrastructure_tests/tests_data/json_file_for_testing.json") as file:
        data = json.load(file)  # reads the file content

    with open("Tests/scripts/infrastructure_tests/tests_data/json_file_for_testing.json", "w") as file:
        json.dump({"test": "test"}, file)  # resets the file

    assert data["PackID"] == "scripts"
