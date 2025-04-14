import json
import os
from pathlib import Path
from unittest import mock

from Tests.Marketplace import validate_core_packs_list
from Tests.Marketplace.marketplace_services import load_json
from Tests.Marketplace.validate_core_packs_list import (
    METADATA_JSON,
    LogAggregator,
    MarketplaceVersions,
    get_core_packs_data,
    get_dependencies_from_pack_meta_data,
    validate_dependency_supported_modules,
)


class MockNamespace:
    marketplace = "xsoar_saas"
    server_version = "8.8.0"


def test_extract_pack_name_from_path_full_path():
    """
    Given
    - A pack path with full prefix of the bucket.
    When
    - Extracting pack name from the path.
    Then
    - Ensure the pack name was extracted successfully.
    """
    from Tests.Marketplace.validate_core_packs_list import extract_pack_name_from_path

    pack_path = (
        "https://storage.googleapis.com/"
        "marketplace-ci-build/content/builds/"
        "brunch-name/build-number/marketplace/content/"
        "packs/pack-name/1.1.38/pack-name.zip"
    )
    assert "pack-name" == extract_pack_name_from_path(pack_path)


def test_extract_pack_name_from_path_partial_path():
    """
    Given
    - A pack path without any prefix of the bucket.
    When
    - Extracting pack name from the path.
    Then
    - Ensure the pack name was extracted successfully.
    """
    from Tests.Marketplace.validate_core_packs_list import extract_pack_name_from_path

    pack_path = "pack-name/1.1.38/pack-name.zip"
    assert "pack-name" == extract_pack_name_from_path(pack_path)


def test_extract_pack_version_from_path_partial_path():
    """
    Given
    - A pack path and pack name.
    When
    - Extracting pack version from the path.
    Then
    - Ensure the version was extracted successfully.
    """
    from Tests.Marketplace.validate_core_packs_list import extract_pack_version_from_pack_path

    pack_path = "pack-name/1.1.39/pack-name.zip"
    pack_name = "pack-name"
    assert "1.1.39" == extract_pack_version_from_pack_path(pack_path, pack_name)


def test_extract_pack_version_from_path_full_path():
    """
    Given
    - A pack path and pack name.
    When
    - Extracting pack version from the path.
    Then
    - Ensure the version was extracted successfully.
    """
    from Tests.Marketplace.validate_core_packs_list import extract_pack_version_from_pack_path

    pack_path = (
        "https://storage.googleapis.com/marketplace-ci-build"
        "/content/builds/1.0.99137-pr-batch-1/1111111"
        "/xsoar/content/packs/pack-name/1.1.39/pack-name.zip"
    )
    pack_name = "pack-name"
    assert "1.1.39" == extract_pack_version_from_pack_path(pack_path, pack_name)


def test_extract_pack_version_from_path_full_path_2():
    """
    Given
    - A pack path and pack name.
    When
    - Extracting pack version from the path.
    Then
    - Ensure the version was extracted successfully.
    """
    from Tests.Marketplace.validate_core_packs_list import extract_pack_version_from_pack_path

    pack_path = (
        "https://storage.googleapis.com/marketplace-ci-build"
        "/content/builds/AUD-demisto/1.0.0.98891-pr-batch-1/1111111"
        "/xsoar/content/packs/pack-name/1.1.39/pack-name.zip"
    )
    pack_name = "pack-name"
    assert "1.1.39" == extract_pack_version_from_pack_path(pack_path, pack_name)


def test_get_core_pack_from_file(mocker):
    """
    Given
    - A corepacks-x.x.x.json file.
    When
    - Call get_core_pack_from_file.
    Then
    - Ensure the pack was extracted successfully.
    """
    from Tests.Marketplace.validate_core_packs_list import get_core_packs_from_bucket

    dummy_corepacks_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_data", "corepacks-x.x.x.json")

    mocker.patch.object(validate_core_packs_list, "get_file_blob", return_value=Path(dummy_corepacks_path))
    mock_open = mock.mock_open(read_data=json.dumps(load_json(dummy_corepacks_path)))
    with mock.patch("builtins.open", mock_open):
        core_packs_list_result = get_core_packs_from_bucket(storage_bucket=dummy_corepacks_path, path="dummy")
    assert core_packs_list_result.get("FeedMitreAttackv2") == {
        "index_zip_path": "FeedMitreAttackv2/metadata-1.1.39.json",
        "version": "1.1.39",
    }


def test_validate_mandatory_dependencies_and_supported_modules_invalid(mocker, tmp_path):
    """
    Scenario: Test the validate_mandatory_dependencies_and_supported_modules function.
    Given:
     - Pack name, pack version, pack dependencies, core pack list.
     - The mandatory dependency of the pack does not appear in the core packs list and
       not a test dependency.
    When:
     - validate_mandatory_dependencies_and_supported_modules called.
    Then:
    - The method executed with error.
    """
    from Tests.Marketplace.validate_core_packs_list import validate_mandatory_dependencies_and_supported_modules

    mocker.patch("Tests.Marketplace.validate_core_packs_list.check_if_test_dependency", return_value=False)
    mocker_logs = mocker.patch.object(validate_core_packs_list.LogAggregator, "add_log")

    dependencies = {
        "Base": {
            "author": "Cortex XSOAR",
            "certification": "certified",
            "mandatory": True,
            "minVersion": "1.34.11",
            "name": "Base",
        }
    }
    core_packs = {"FeedMitreAttackv2": {"index_zip_path": "FeedMitreAttackv2/metadata-1.1.39.json", "version": "1.1.39"}}
    validate_mandatory_dependencies_and_supported_modules(
        "FeedMitreAttackv2",
        "1.1.39",
        [],
        dependencies,
        core_packs,
        "corepacks-x.x.x.json",
        "xsoar",
        "index.zip",
        tmp_path,
        LogAggregator(),
    )
    mocker_logs.assert_called()
    assert mocker_logs.call_count == 1
    assert mocker_logs.call_args.args[0] == (
        "The dependency Base with min version number 1.34.11 of the pack "
        "FeedMitreAttackv2/1.1.39 Does not exists"
        " in core pack list corepacks-x.x.x.json."
    )


def test_validate_mandatory_dependencies_and_supported_modules_invalid_2(mocker, tmp_path):
    """
    Scenario: Test the validate_mandatory_dependencies_and_supported_modules function.
    Given:
     - Pack name, pack version, pack dependencies, core pack list.
     - The mandatory dependency of the pack appears in the core packs list
       with higher version then the corepack list version
    When:
     - validate_mandatory_dependencies_and_supported_modules called.
    Then:
    - The method executed with error.
    """
    from Tests.Marketplace.validate_core_packs_list import validate_mandatory_dependencies_and_supported_modules

    mocker_logs = mocker.patch.object(validate_core_packs_list.LogAggregator, "add_log")

    dependencies = {
        "Base": {
            "author": "Cortex XSOAR",
            "certification": "certified",
            "mandatory": True,
            "minVersion": "1.34.11",
            "name": "Base",
        }
    }
    core_packs = {
        "FeedMitreAttackv2": {"index_zip_path": "FeedMitreAttackv2/metadata-1.1.39.json", "version": "1.1.39"},
        "Base": {"index_zip_path": "FeedMitreAttackv2/metadata-1.1.39.json", "version": "1.1.39"},
    }

    validate_mandatory_dependencies_and_supported_modules(
        "FeedMitreAttackv2",
        "1.1.39",
        [],
        dependencies,
        core_packs,
        "corepacks-x.x.x.json",
        "xsoar",
        "index.zip",
        tmp_path,
        LogAggregator(),
    )
    mocker_logs.assert_called()
    assert mocker_logs.call_count == 1
    assert mocker_logs.call_args.args[0] == (
        "The dependency Base/1.34.11 of the pack FeedMitreAttackv2/1.1.39"
        " in the index.zip does not meet the conditions for Base/1.1.39"
        " in the corepacks-x.x.x.json list."
    )


def test_validate_mandatory_dependencies_and_supported_modules_valid(mocker, tmp_path):
    """
    Scenario: Test the validate_mandatory_dependencies_and_supported_modules function.
    Given:
     - Pack name, pack version, pack dependencies, core pack list.
     - The mandatory dependency of the pack appears in the core packs list
       with higher version then the corepack list version
    When:
     - validate_mandatory_dependencies_and_supported_modules called.
    Then:
     - The method end successfully.
    """
    from Tests.Marketplace.validate_core_packs_list import validate_mandatory_dependencies_and_supported_modules

    mocker_logs = mocker.patch.object(validate_core_packs_list.LogAggregator, "add_log")
    dependencies = {
        "Base": {
            "author": "Cortex XSOAR",
            "certification": "certified",
            "mandatory": True,
            "minVersion": "1.34.10",
            "name": "Base",
        }
    }
    core_packs = {
        "FeedMitreAttackv2": {"index_zip_path": "FeedMitreAttackv2/metadata-1.1.39.json", "version": "1.1.39"},
        "Base": {"index_zip_path": "FeedMitreAttackv2/metadata-1.1.39.json", "version": "1.34.11"},
    }

    validate_mandatory_dependencies_and_supported_modules(
        "FeedMitreAttackv2",
        "1.1.39",
        [],
        dependencies,
        core_packs,
        "corepacks-x.x.x.json",
        "xsoar",
        "index.zip",
        tmp_path,
        LogAggregator(),
    )
    assert mocker_logs.call_count == 0


def test_get_core_packs_data():
    """
    Given:
     - The data of a core packs list file.
    When:
     - Calling get_core_packs_content to parse the content of the file in the way we want.
    Then:
     - Retrieve the information in the expected format.
    """
    from Tests.Marketplace.validate_core_packs_list import get_core_packs_data

    core_packs_file_data = {
        "corePacks": ["pack1/1.1.34/pack1.zip", "pack2/1.0.9/pack2.zip"],
        "upgradeCorePacks": ["pack1", "pack2"],
    }
    expected_result = {
        "pack1": {"version": "1.1.34", "index_zip_path": "pack1/metadata-1.1.34.json"},
        "pack2": {"version": "1.0.9", "index_zip_path": "pack2/metadata-1.0.9.json"},
    }
    assert expected_result == get_core_packs_data(core_packs_file_data)


def test_get_core_packs_data_platform():
    """
    Given:
     - The data of a core packs list file for the platform.
    When:
     - Calling get_core_packs_data with MarketplaceVersions.PLATFORM.value.
    Then:
     - Retrieve the information in the expected format for platform packs.
    """
    core_packs_file_data = {"packs": [{"id": "TestPack", "version": "1.0.0", "supportedModules": ["X1", "X3", "X5", "ENT_PLUS"]}]}
    expected_result = {
        "TestPack": {
            "version": "1.0.0",
            "supportedModules": ["X1", "X3", "X5", "ENT_PLUS"],
            "index_zip_path": "TestPack/metadata-1.0.0.json",
        }
    }
    assert expected_result == get_core_packs_data(core_packs_file_data, MarketplaceVersions.PLATFORM.value)


def test_get_dependencies_from_pack_meta_data(tmp_path):
    """
    Given:
     - A temporary path and metadata content for a test pack.
    When:
     - Calling get_dependencies_from_pack_meta_data with the metadata path.
    Then:
     - Return the dependencies from the metadata content.
    """
    metadata_content = {"name": "TestPack", "dependencies": {"BasePack": {"mandatory": True, "minVersion": "1.0.0"}}}
    metadata_path = tmp_path / METADATA_JSON
    with open(metadata_path, "w") as f:
        json.dump(metadata_content, f)

    result = get_dependencies_from_pack_meta_data(metadata_path)
    assert result == metadata_content["dependencies"]


def test_validate_dependency_supported_modules_success(mocker, tmp_path):
    """
    Given:
     - Core packs mapping with supported modules.
     - A pack and its dependency with matching supported modules.
    When:
     - Calling validate_dependency_supported_modules.
    Then:
     - The validation succeeds and returns True.
    """
    mocker.patch.object(validate_core_packs_list.LogAggregator, "add_log")
    mocker.patch("Tests.Marketplace.validate_core_packs_list.get_pack_supported_modules", return_value={"X1", "X3", "X5", "C1"})

    core_packs_mapping = {
        "PackA": {
            "version": "1.0.0",
            "supportedModules": ["X1", "X3", "X5", "C1", "C3"],
            "index_zip_path": "PackA/metadata-1.0.0.json",
        },
        "PackB": {
            "version": "1.0.0",
            "supportedModules": ["X1", "X3", "X5", "C1"],
            "index_zip_path": "PackB/metadata-1.0.0.json",
        },
    }
    pack_name = "PackA"
    pack_supported_modules = ["X1", "X3", "X5", "C1", "C3"]
    dependency_name = "PackB"
    index_folder_path = tmp_path

    assert validate_dependency_supported_modules(
        core_packs_mapping, pack_name, pack_supported_modules, dependency_name, index_folder_path, LogAggregator()
    )


def test_validate_dependency_supported_modules_missing_modules(mocker, tmp_path):
    """
    Given:
     - Core packs mapping with supported modules.
     - A pack and its dependency with mismatched supported modules.
    When:
     - Calling validate_dependency_supported_modules.
    Then:
     - The validation fails and returns False.
    """
    mocker.patch.object(validate_core_packs_list.LogAggregator, "add_log")
    mocker.patch(
        "Tests.Marketplace.validate_core_packs_list.get_pack_supported_modules", return_value={"C1", "C3", "X0", "X1", "X3"}
    )

    core_packs_mapping = {
        "PackA": {
            "version": "1.0.0",
            "supportedModules": ["X1", "X3", "X5", "C1", "C3"],
            "index_zip_path": "PackA/metadata-1.0.0.json",
        },
        "PackB": {"version": "1.0.0", "supportedModules": ["C1", "C3", "X0"], "index_zip_path": "PackB/metadata-1.0.0.json"},
    }
    pack_name = "PackA"
    pack_supported_modules = ["X1", "X3", "C1", "C3"]
    dependency_name = "PackB"
    index_folder_path = tmp_path

    assert not validate_dependency_supported_modules(
        core_packs_mapping, pack_name, pack_supported_modules, dependency_name, index_folder_path, LogAggregator()
    )


def test_validate_dependency_supported_modules_mixed_scenario(mocker, tmp_path):
    """
    Given:
     - Core packs mapping with supported modules.
     - A pack and its dependency with a mix of matching and non-matching supported modules.
    When:
     - Calling validate_dependency_supported_modules.
    Then:
     - The validation succeeds and returns True.
    """
    mocker.patch.object(validate_core_packs_list.LogAggregator, "add_log")
    mocker.patch("Tests.Marketplace.validate_core_packs_list.get_pack_supported_modules", return_value={"X1", "X3", "C1", "X0"})

    core_packs_mapping = {
        "PackA": {
            "version": "1.0.0",
            "supportedModules": ["X1", "X3", "X5", "C1", "C3"],
            "index_zip_path": "PackA/metadata-1.0.0.json",
        },
        "PackB": {
            "version": "1.0.0",
            "supportedModules": ["X1", "X3", "C1", "X0"],
            "index_zip_path": "PackB/metadata-1.0.0.json",
        },
    }
    pack_name = "PackA"
    pack_supported_modules = ["X1", "X3", "X5", "C1", "C3"]
    dependency_name = "PackB"
    index_folder_path = tmp_path

    assert validate_dependency_supported_modules(
        core_packs_mapping, pack_name, pack_supported_modules, dependency_name, index_folder_path, LogAggregator()
    )
