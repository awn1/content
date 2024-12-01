import unittest

import pytest
from demisto_sdk.commands.content_graph.interface.neo4j.neo4j_graph import Neo4jContentGraphInterface

from Pipelines.override_content.override_content_validations import (
    ENV_TYPE_OPTIONS,
    options_handler,
    validate_content_items_marketplace,
    validate_file_types,
    validate_variables,
)


def test_validate_content_items_marketplace_paths(mocker):
    """
    Given: args with valid integration path
    When: Running validate_content_items_marketplace() with different values of mandatory_only.
    Then: Ensure the command runs without exceptions.
    """
    args = [
        "--paths",
        "tests_data/fake_integration/fake_integration.yml",
        "--packs",
        "",
        "--marketplace",
        "xsoar_saas",
        "--tenant_ids",
        "qa2-test-1234",
        "--env_type",
        "dev",
    ]
    options = options_handler(args=args)

    mocker.patch.object(Neo4jContentGraphInterface, "search", return_value=True)
    assert validate_content_items_marketplace(options)


def test_validate_variables_no_packs_no_paths(mocker):
    """
    Given: args without paths and packs
    When: Running validate_variables().
    Then: Ensure the exception has the correct message.
    """
    args = [
        "--paths",
        "",
        "--packs",
        "",
        "--marketplace",
        "xsoar_saas",
        "--tenant_ids",
        "qa2-test-1234",
        "--env_type",
        "dev",
    ]
    options = options_handler(args=args)

    mocker.patch.object(Neo4jContentGraphInterface, "search", return_value=True)
    with pytest.raises(Exception) as e:
        validate_variables(options)  # exception

    assert str(e) == "Specify a pack or content item to override."


def test_validate_variables_packs_and_paths(mocker):
    """
    Given: args with paths and packs together.
    When: Running validate_variables().
    Then: Ensure the exception has the correct message.
    """
    args = [
        "--paths",
        "mockPath",
        "--packs",
        "mockPackName",
        "--marketplace",
        "xsoar_saas",
        "--tenant_ids",
        "qa2-test-1234",
        "--env_type",
        "dev",
    ]
    options = options_handler(args=args)

    mocker.patch.object(Neo4jContentGraphInterface, "search", return_value=True)
    with pytest.raises(Exception) as e:
        validate_variables(options)  # exception

    assert str(e) == "Specify a pack or a content items, not both."


def test_validate_variables_env_type(mocker):
    """
    Given: args with incorrect env_type.
    When: Running validate_variables().
    Then: Ensure the exception has the correct message.
    """
    args = [
        "--paths",
        "",
        "--packs",
        "mockPackName",
        "--marketplace",
        "xsoar_saas",
        "--tenant_ids",
        "qa2-test-1234",
        "--env_type",
        "mock_dev_type",
    ]
    options = options_handler(args=args)

    mocker.patch.object(Neo4jContentGraphInterface, "search", return_value=True)
    with pytest.raises(Exception) as e:
        validate_variables(options)  # exception

    assert str(e) == f"Got invalid env_type: mock_dev_type. Specify one of the possible values: {ENV_TYPE_OPTIONS}"


def test_validate_variables_invalid_tenant_id(mocker):
    """
    Given: args with incorrect tenant id.
    When: Running validate_variables().
    Then: Ensure the exception has the correct message.
    """
    args = [
        "--paths",
        "",
        "--packs",
        "mockPackName",
        "--marketplace",
        "xsoar_saas",
        "--tenant_ids",
        "invalidTenantID",
        "--env_type",
        "dev",
    ]
    options = options_handler(args=args)

    mocker.patch.object(Neo4jContentGraphInterface, "search", return_value=True)
    with pytest.raises(Exception) as e:
        validate_variables(options)  # exception

    assert (
        str(e) == "Got invalid tenant ids: invalidTenantID for dev environment. "
        "Make sure to use the 'qa2-test-<numbers>' template."
    )


def test_validate_file_types():
    """
    Given: args with valid integration path
    When: Running validate_file_types().
    Then: Ensure the command runs without exceptions.
    """
    args = [
        "--paths",
        "tests_data/fake_integration/fake_integration.yml, tests_data/fake_json.json",
    ]
    options = options_handler(args=args)
    assert validate_file_types(options)


def test_validate_file_types_invalid_file_type(mocker):
    """
    Given: args with invalid file extention.
    When: Running validate_file_types().
    Then: Ensure the exception has the correct message.
    """
    args = [
        "--paths",
        "fake_integration.txt",
    ]
    options = options_handler(args=args)

    with pytest.raises(Exception) as e:
        validate_file_types(options)  # exception

    assert (
        str(e) == "Invalid file types detected in the following content items: fake_integration.txt .\n"
        "Make sure to select a valid file for override: either a .yml or a .json file."
    )


if __name__ == "__main__":
    unittest.main()
