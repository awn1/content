from unittest.mock import MagicMock
from Tests.scripts.split_packs_to_machines import (
    build_pack_information,
    machine_assignment,
    calculate_average_execution_time,
    PackInfo,
    ARTIFACTS_BUCKET,
    MAX_REPORT_FILES,
)


def test_calculate_average_execution_time(mocker):
    """
    Given: XML files with playbook execution times in a GCP bucket.
    When: Calculating average execution times for test playbooks.
    Then: Returns a dictionary with average execution times for each playbook.
    """
    mock_storage_client = mocker.patch("Tests.scripts.split_packs_to_machines.storage.Client")
    mock_blob1 = MagicMock()
    mock_blob1.download_as_string.return_value = """
    <testsuites>
        <testsuite name="playbook1" tests="1" errors="0" failures="0" skipped="1" time="0.0">
        </testsuite>
        <testsuite name="playbook2" tests="1" errors="0" failures="0" skipped="1" time="0.001">
        </testsuite>
    </testsuites>
    """
    mock_blob1.updated = "2023-06-30T12:00:00Z"
    mock_blob1.content_type = "application/xml"
    mock_blob2 = MagicMock()
    mock_blob2.download_as_string.return_value = """
    <testsuites>
        <testsuite name="playbook1" tests="1" errors="0" failures="0" skipped="0" time="429.734">
        </testsuite>
        <testsuite name="playbook3" tests="1" errors="0" failures="0" skipped="0" time="433.691">
        </testsuite>
    </testsuites>
    """
    mock_blob2.updated = "2023-06-30T13:00:00Z"
    mock_blob2.content_type = "application/xml"
    mock_blob3 = MagicMock()
    mock_blob3.download_as_string.return_value = """
    <testsuites>
        <testsuite name="playbook2" tests="1" errors="0" failures="0" skipped="0" time="504.126">
        </testsuite>
        <testsuite name="playbook3" tests="1" errors="0" failures="0" skipped="0" time="549.472">
        </testsuite>
    </testsuites>
    """
    mock_blob3.updated = "2023-06-30T14:00:00Z"
    mock_blob3.content_type = "application/xml"
    mock_storage_client.list_blobs.return_value = [mock_blob1, mock_blob2, mock_blob3]

    test_playbooks = ["playbook1", "playbook2", "playbook3"]
    avg_times = calculate_average_execution_time(
        ARTIFACTS_BUCKET, "server_type", test_playbooks, mock_storage_client, MAX_REPORT_FILES
    )

    assert avg_times["playbook1"] == 429.734
    assert avg_times["playbook2"] == 504.126
    assert avg_times["playbook3"] == 491.5815


def test_build_pack_information():
    """
    Given: Playbooks with associated packs and dependencies and their execution times.
    When: The build_pack_information function is called with these inputs.
    Then: Returns pack objects with correct playbooks, dependencies, and total execution times.
    """
    playbooks = {
        "playbook1": {"pack": "pack1", "dependencies": ["pack2", "pack3"]},
        "playbook2": {"pack": "pack1", "dependencies": ["pack4"]},
        "playbook3": {"pack": "pack2", "dependencies": []},
    }
    playbook_times = {
        "playbook1": 100.0,
        "playbook2": 200.0,
        "playbook3": 150.0,
    }

    expected_packs = {
        "pack1": PackInfo("pack1"),
        "pack2": PackInfo("pack2"),
    }
    expected_packs["pack1"].test_playbooks_to_run = {"playbook1", "playbook2"}
    expected_packs["pack1"].dependencies = {"pack2", "pack3", "pack4"}
    expected_packs["pack1"].total_expected_execution_time = 300.0
    expected_packs["pack2"].test_playbooks_to_run = {"playbook3"}
    expected_packs["pack2"].dependencies = set()
    expected_packs["pack2"].total_expected_execution_time = 150.0

    packs_objects_to_install = build_pack_information(playbooks, playbook_times)
    for pack_name, expected_pack_info in expected_packs.items():
        actual_pack_info = packs_objects_to_install.get(pack_name)
        assert actual_pack_info is not None, f"PackInfo for '{pack_name}' is missing"
        assert (
            actual_pack_info.test_playbooks_to_run == expected_pack_info.test_playbooks_to_run
        ), f"test_playbooks_to_run for '{pack_name}' does not match"
        assert actual_pack_info.dependencies == expected_pack_info.dependencies, f"dependencies for '{pack_name}' does not match"
        assert (
            actual_pack_info.total_expected_execution_time == expected_pack_info.total_expected_execution_time
        ), f"total_expected_execution_time for '{pack_name}' does not match"


def test_machine_assignment():
    """
    Given: Packs to install with their execution times and dependencies, and a list of machines.
    When: Assigning packs and playbooks to machines based on execution times.
    Then: Packs and playbooks are correctly assigned to machines with balanced loads.
    """
    pack1 = PackInfo("pack1")
    pack1.test_playbooks_to_run = {"playbook1", "playbook2"}
    pack1.dependencies = {"pack2"}
    pack1.total_expected_execution_time = 300.0

    pack2 = PackInfo("pack2")
    pack2.test_playbooks_to_run = {"playbook3"}
    pack2.dependencies = set()
    pack2.total_expected_execution_time = 150.0

    packs_objects_to_install = {"pack1": pack1, "pack2": pack2}
    machines = {"machine1", "machine2"}
    packs_to_install_from_file = ["pack1", "pack2", "pack3"]
    marketplace = "xsoar"
    expected_machine_split_1 = {
        "packs_to_install": ["pack2", "DeveloperTools", "pack3", "Base"],
        "playbooks_to_run": ["playbook3"],
    }
    expected_machine_split_2 = {
        "packs_to_install": ["pack1", "pack2", "DeveloperTools", "Base"],
        "playbooks_to_run": ["playbook2", "playbook1"],
    }

    assignments = machine_assignment(packs_objects_to_install, machines, packs_to_install_from_file, marketplace)

    for machine in assignments.values():
        assert set(machine["packs_to_install"]) in [
            set(expected_machine_split_1["packs_to_install"]),
            set(expected_machine_split_2["packs_to_install"]),
        ]
        assert set(machine["playbooks_to_run"]) in [
            set(expected_machine_split_1["playbooks_to_run"]),
            set(expected_machine_split_2["playbooks_to_run"]),
        ]
