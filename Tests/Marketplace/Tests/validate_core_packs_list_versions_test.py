import os
from unittest import mock
import json
from Tests.Marketplace.marketplace_services import load_json
from pathlib import Path
from Tests.Marketplace.validate_core_packs_list_versions import LogAggregator


def test_extract_pack_name_from_path_full_path():
    """
    Given
    - A pack path with full prefix of the bucket.
    When
    - Extracting pack name from the path.
    Then
    - Ensure the pack name was extracted successfully.
    """
    from Tests.Marketplace.validate_core_packs_list_versions import extract_pack_name_from_path

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
    from Tests.Marketplace.validate_core_packs_list_versions import extract_pack_name_from_path

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
    from Tests.Marketplace.validate_core_packs_list_versions import extract_pack_version_from_pack_path

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
    from Tests.Marketplace.validate_core_packs_list_versions import extract_pack_version_from_pack_path

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
    from Tests.Marketplace.validate_core_packs_list_versions import extract_pack_version_from_pack_path

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
    from Tests.Marketplace import validate_core_packs_list_versions
    from Tests.Marketplace.validate_core_packs_list_versions import get_core_packs_from_file

    dummy_corepacks_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_data", "corepacks-x.x.x.json")

    mocker.patch.object(validate_core_packs_list_versions, "get_file_blob", return_value=Path(dummy_corepacks_path))
    mock_open = mock.mock_open(read_data=json.dumps(load_json(dummy_corepacks_path)))
    with mock.patch("builtins.open", mock_open):
        core_packs_list_result = get_core_packs_from_file(storage_bucket=dummy_corepacks_path, path="dummy")
    assert core_packs_list_result.get("FeedMitreAttackv2") == {
        "index_zip_path": "/FeedMitreAttackv2/metadata-1.1.39.json",
        "version": "1.1.39",
    }


def test_verify_all_mandatory_dependencies_are_in_corepack_list_invalid(mocker):
    """
    Scenario: Test the verify_all_mandatory_dependencies_are_in_corepack_list function.
    Given:
     - Pack name, pack version, pack dependencies, core pack list.
     - The mandatory dependency of the pack does not appears in the core packs list and
       not a test dependency.
    When:
     - verify_all_mandatory_dependencies_are_in_corepack_list called.
    Then:
    - The method executed with error.
    """
    from Tests.Marketplace import validate_core_packs_list_versions
    from Tests.Marketplace.validate_core_packs_list_versions import verify_all_mandatory_dependencies_are_in_corepack_list

    mocker.patch("Tests.Marketplace.validate_core_packs_list_versions.check_if_test_dependency", return_value=False)
    mocker_logs = mocker.patch.object(validate_core_packs_list_versions.LogAggregator, "add_log")

    dependencies = {
        "Base": {
            "author": "Cortex XSOAR",
            "certification": "certified",
            "mandatory": True,
            "minVersion": "1.34.11",
            "name": "Base",
        }
    }
    core_packs = {"FeedMitreAttackv2": {"index_zip_path": "/FeedMitreAttackv2/metadata-1.1.39.json", "version": "1.1.39"}}
    verify_all_mandatory_dependencies_are_in_corepack_list(
        "FeedMitreAttackv2", "1.1.39", dependencies, core_packs, "corepacks-x.x.x.json", "xsoar", "index.zip", LogAggregator()
    )
    mocker_logs.assert_called()
    assert mocker_logs.call_count == 1
    assert mocker_logs.call_args.args[0] == (
        "The dependency Base with min version number 1.34.11 of the pack "
        "FeedMitreAttackv2/1.1.39 Does not exists"
        " in core pack list corepacks-x.x.x.json."
    )


def test_verify_all_mandatory_dependencies_are_in_corepack_list_invalid_2(mocker):
    """
    Scenario: Test the verify_all_mandatory_dependencies_are_in_corepack_list function.
    Given:
     - Pack name, pack version, pack dependencies, core pack list.
     - The mandatory dependency of the pack appears in the core packs list
       with higher version then the corepack list version
    When:
     - verify_all_mandatory_dependencies_are_in_corepack_list called.
    Then:
    - The method executed with error.
    """
    from Tests.Marketplace import validate_core_packs_list_versions
    from Tests.Marketplace.validate_core_packs_list_versions import verify_all_mandatory_dependencies_are_in_corepack_list

    mocker_logs = mocker.patch.object(validate_core_packs_list_versions.LogAggregator, "add_log")

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
        "FeedMitreAttackv2": {"index_zip_path": "/FeedMitreAttackv2/metadata-1.1.39.json", "version": "1.1.39"},
        "Base": {"index_zip_path": "/FeedMitreAttackv2/metadata-1.1.39.json", "version": "1.1.39"},
    }

    verify_all_mandatory_dependencies_are_in_corepack_list(
        "FeedMitreAttackv2", "1.1.39", dependencies, core_packs, "corepacks-x.x.x.json", "xsoar", "index.zip", LogAggregator()
    )
    mocker_logs.assert_called()
    assert mocker_logs.call_count == 1
    assert mocker_logs.call_args.args[0] == (
        "The dependency Base/1.34.11 of the pack FeedMitreAttackv2/1.1.39"
        " in the index.zip does not meet the conditions for Base/1.1.39"
        " in the corepacks-x.x.x.json list."
    )


def test_verify_all_mandatory_dependencies_are_in_corepack_list_valid(mocker):
    """
    Scenario: Test the verify_all_mandatory_dependencies_are_in_corepack_list function.
    Given:
     - Pack name, pack version, pack dependencies, core pack list.
     - The mandatory dependency of the pack appears in the core packs list
       with higher version then the corepack list version
    When:
     - verify_all_mandatory_dependencies_are_in_corepack_list called.
    Then:
     - The method end successfully.
    """
    from Tests.Marketplace import validate_core_packs_list_versions
    from Tests.Marketplace.validate_core_packs_list_versions import verify_all_mandatory_dependencies_are_in_corepack_list

    mocker_logs = mocker.patch.object(validate_core_packs_list_versions.LogAggregator, "add_log")
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
        "FeedMitreAttackv2": {"index_zip_path": "/FeedMitreAttackv2/metadata-1.1.39.json", "version": "1.1.39"},
        "Base": {"index_zip_path": "/FeedMitreAttackv2/metadata-1.1.39.json", "version": "1.34.11"},
    }

    verify_all_mandatory_dependencies_are_in_corepack_list(
        "FeedMitreAttackv2", "1.1.39", dependencies, core_packs, "corepacks-x.x.x.json", "xsoar", "index.zip", LogAggregator()
    )
    assert mocker_logs.call_count == 0
