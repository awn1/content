import json

from Tests.creating_disposable_tenants.create_disposable_tenants import (
    BUILD_MACHINE_FLOWS,
    XSIAM_VERSION,
    XSOAR_SAAS_DEMISTO_VERSION,
    XsiamClient,
    XsoarClient,
    extract_xsoar_ng_version,
    prepare_outputs,
    save_to_output_file,
)


def test_extract_xsoar_ng_version_valid():
    """
    Given: A valid XSOAR NG version string.
    When: The extract_xsoar_ng_version function is called.
    Then: The function should return the correct extracted version.
    """
    version = "master-v8.8.0-1436883-667f2e66"
    result = extract_xsoar_ng_version(version)
    assert result == "8.8.0"


def test_extract_xsoar_ng_version_invalid():
    """
    Given: An invalid XSOAR NG version string.
    When: The extract_xsoar_ng_version function is called.
    Then: The function should return the original input string.
    """
    version = "invalid-version-string"
    result = extract_xsoar_ng_version(version)
    assert result == version


def test_extract_xsoar_ng_version_empty():
    """
    Given: An empty string as input.
    When: The extract_xsoar_ng_version function is called.
    Then: The function should return an empty string.
    """
    version = ""
    result = extract_xsoar_ng_version(version)
    assert result == ""


def test_prepare_outputs_multiple_flows(mocker):
    """
    Given: A list of tenant IDs and tenant info for multiple flow types.
    When: The prepare_outputs function is called with multiple flow types.
    Then: The function should return correctly formatted output information for all flow types.
    """
    new_tenants_info = {"build": ["123"], "nightly": ["456"], "@test": ["789"]}
    tenants_info = [
        {"lcaas_id": "123", "fqdn": "tenant1.com", "xsoar_version": "master-v8.8.0-1436883-667f2e66"},
        {"lcaas_id": "456", "fqdn": "tenant2.com", "xsoar_version": "master-v8.8.0-1436884-667f2e67"},
        {"lcaas_id": "789", "fqdn": "tenant3.com", "xsoar_version": "master-v8.8.0-1436885-667f2e68"},
    ]

    result = prepare_outputs(new_tenants_info, tenants_info, XsiamClient.SERVER_TYPE, True)

    assert len(result) == 3
    assert result["qa2-test-123"]["flow_type"] == "build"
    assert result["qa2-test-456"]["flow_type"] == "nightly"
    assert result["qa2-test-789"]["flow_type"] == "@test"
    assert all(tenant["xsiam_version"] == XSIAM_VERSION for tenant in result.values())
    assert all(tenant["demisto_version"] == "8.8.0" for tenant in result.values())
    assert all(tenant["build_machine"] is True for tenant in result.values() if tenant["flow_type"] in BUILD_MACHINE_FLOWS)
    assert result["qa2-test-789"]["build_machine"] is False


def test_prepare_outputs_xsiam():
    """
    Given: A list of tenant IDs and tenant info for XSIAM server type.
    When: The prepare_outputs function is called with XSIAM server type and build flow type.
    Then: The function should return correctly formatted output information for XSIAM tenants.
    """
    tenant_ids = ["123", "456"]
    tenant_info = [
        {"lcaas_id": "123", "fqdn": "tenant1.com", "xsoar_version": "master-v8.8.0-1436883-667f2e66"},
        {"lcaas_id": "456", "fqdn": "tenant2.com", "xsoar_version": "master-v8.9.0-1436884-667f2e67"},
    ]
    new_tenants_info = {"build": tenant_ids}

    result = prepare_outputs(new_tenants_info, tenant_info, XsiamClient.SERVER_TYPE, "build")

    assert len(result) == 2
    assert result["qa2-test-123"]["xsiam_version"] == XSIAM_VERSION
    assert result["qa2-test-123"]["demisto_version"] == "8.8.0"
    assert result["qa2-test-123"]["build_machine"] is True
    assert "agent_host_name" in result["qa2-test-123"]
    assert "agent_host_ip" in result["qa2-test-123"]


def test_prepare_outputs_xsoar():
    """
    Given: A list of tenant IDs and tenant info for XSOAR server type.
    When: The prepare_outputs function is called with XSOAR server type and upload flow type.
    Then: The function should return correctly formatted output information for XSOAR tenants.
    """
    tenant_ids = ["789"]
    tenant_info = [{"lcaas_id": "789", "fqdn": "tenant3.com", "xsoar_version": "master-v9.0.0-1436885-667f2e68"}]
    new_tenants_info = {"upload": tenant_ids}

    result = prepare_outputs(new_tenants_info, tenant_info, XsoarClient.SERVER_TYPE, "upload")

    assert len(result) == 1
    assert result["qa2-test-789"]["xsoar_ng_version"] == "9.0.0"
    assert result["qa2-test-789"]["demisto_version"] == XSOAR_SAAS_DEMISTO_VERSION
    assert result["qa2-test-789"]["build_machine"] is True
    assert "agent_host_name" not in result["qa2-test-789"]
    assert "agent_host_ip" not in result["qa2-test-789"]


def test_prepare_outputs_empty_input():
    """
    Given: Empty lists for tenant IDs and tenant info.
    When: The prepare_outputs function is called with empty inputs.
    Then: The function should return an empty dictionary.
    """
    result = prepare_outputs({}, [], "XSOAR", "nightly")

    assert result == {}


def test_prepare_outputs_missing_tenant_info(mocker):
    """
    Given: A list of tenant IDs with missing tenant info.
    When: The prepare_outputs function is called with incomplete tenant info.
    Then: The function should handle missing information gracefully and return partial output.
    """
    mocker.patch("Tests.creating_disposable_tenants.create_disposable_tenants.extract_xsoar_ng_version", return_value="")

    tenant_ids = ["123", "456"]
    tenant_info = [
        {"lcaas_id": "123", "fqdn": "tenant1.com"},
    ]
    new_tenants_info = {"upload": tenant_ids}

    result = prepare_outputs(new_tenants_info, tenant_info, XsiamClient.SERVER_TYPE, "nightly")

    assert len(result) == 2
    assert result["qa2-test-123"]["ui_url"] == "https://tenant1.com/"
    assert result["qa2-test-456"]["ui_url"] == "https://None/"
    assert result["qa2-test-456"]["demisto_version"] == ""


def test_save_to_output_file_new_file(tmp_path, mocker):
    """
    Given: A new output file path and output data.
    When: save_to_output_file is called.
    Then: The function should create a new file with the provided data.
    """
    output_path = tmp_path / "new_output.json"
    output_data = {"test1": {"server_type": "XSOAR", "flow_type": "build"}}

    mock_logger = mocker.patch("Tests.creating_disposable_tenants.create_disposable_tenants.logging")

    save_to_output_file(output_path, output_data)

    assert output_path.exists()
    with open(output_path) as f:
        saved_data = json.load(f)
    assert saved_data == output_data
    mock_logger.debug.assert_any_call(f"Attempting to save output data to: {output_path}")
    mock_logger.debug.assert_any_call(f"No existing data found at: {output_path}, starting fresh.")
    mock_logger.info.assert_called_once_with(f"Output data successfully saved to: {output_path}")


def test_save_to_output_file_existing_file(tmp_path, mocker):
    """
    Given: An existing output file with data and new output data.
    When: save_to_output_file is called.
    Then: The function should merge the existing data with the new data and save it sorted.
    """
    output_path = tmp_path / "existing_output.json"
    existing_data = {
        "test1": {"server_type": "XSOAR", "flow_type": "build"},
        "test2": {"server_type": "XSIAM", "flow_type": "nightly"},
    }
    output_path.write_text(json.dumps(existing_data))

    new_output_data = {
        "test3": {"server_type": "XSOAR", "flow_type": "upload"},
        "test4": {"server_type": "XSIAM", "flow_type": "build"},
    }

    mock_logger = mocker.patch("Tests.creating_disposable_tenants.create_disposable_tenants.logging")

    save_to_output_file(output_path, new_output_data)

    with open(output_path) as f:
        saved_data = json.load(f)

    expected_data = {
        "test2": {"server_type": "XSIAM", "flow_type": "nightly"},
        "test4": {"server_type": "XSIAM", "flow_type": "build"},
        "test1": {"server_type": "XSOAR", "flow_type": "build"},
        "test3": {"server_type": "XSOAR", "flow_type": "upload"},
    }

    assert saved_data == expected_data
    mock_logger.debug.assert_any_call(f"Attempting to save output data to: {output_path}")
    mock_logger.debug.assert_any_call(f"Loaded existing data from: {output_path}")
    mock_logger.info.assert_called_once_with(f"Output data successfully saved to: {output_path}")


def test_save_to_output_file_json_decode_error(tmp_path, mocker):
    """
    Given: An existing output file with invalid JSON data.
    When: save_to_output_file is called.
    Then: The function should log an error about decoding JSON.
    """
    output_path = tmp_path / "invalid_output.json"
    output_path.write_text("invalid json data")

    output_data = {"test1": {"server_type": "XSOAR", "flow_type": "build"}}

    mock_logger = mocker.patch("Tests.creating_disposable_tenants.create_disposable_tenants.logging")

    save_to_output_file(output_path, output_data)

    mock_logger.error.assert_called_once_with(f"Error loading JSON file at: {output_path}")


def test_save_to_output_file_unexpected_error(tmp_path, mocker):
    """
    Given: A scenario where an unexpected error occurs.
    When: save_to_output_file is called.
    Then: The function should log an error about the unexpected occurrence.
    """
    output_path = tmp_path / "error_output.json"
    output_data = {"test1": {"server_type": "XSOAR", "flow_type": "build"}}

    mock_logger = mocker.patch("Tests.creating_disposable_tenants.create_disposable_tenants.logging")
    mocker.patch("builtins.open", side_effect=Exception("Unexpected error"))

    save_to_output_file(output_path, output_data)

    mock_logger.error.assert_called_once_with("Unexpected error occurred: Unexpected error")
