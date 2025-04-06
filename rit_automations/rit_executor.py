import difflib
import json
import logging
import os
import shutil
import subprocess
import sys
from collections import OrderedDict
from pathlib import Path

import yaml

from Tests.scripts.utils.log_util import install_logging

RIT_FOLDER_NAME = os.getenv("RIT_FOLDER_NAME", "asset-collection")
RECORDINGS_DIR = os.getenv("RECORDINGS_DIR", "TestData/Recordings")
RIT_ROOT_DIR = Path(f"./{RIT_FOLDER_NAME}")  # RIT folders (aws, azure, gcp)
RECORDINGS_DIR_PATH = Path(f"./{RECORDINGS_DIR}")
EXECUTOR_CMD_DIR = Path("/tmp/cortex-gonzo/src/xdr.panw/collection/cloud-assets", "cmd/rit-executor")
RED = "\033[1;31m"
GREEN = "\033[1;32m"
NC = "\033[0m"  # No Color
BOLD = "\033[1m"  # Bold text
CYAN = "\033[1;36m"  # Cyan for separators and titles


def sort_json(json_obj: dict | list | object) -> object:
    """
    Recursively sorts a JSON object (either a dictionary or list)to ensure consistent ordering.

    - Dicts are sorted by key.
    - Lists of dicts are sorted by their JSON string representation.
    - Lists of primitives maintain their order.

    Args:
        json_obj (dict | list | any): The JSON object to sort.

    Returns:
        any: The sorted JSON object, or the original object if sorting is not possible.
    """
    if isinstance(json_obj, dict):
        return OrderedDict((key, sort_json(value)) for key, value in sorted(json_obj.items()))

    elif isinstance(json_obj, list):
        # If list contains only dicts, sort them by JSON representation
        if all(isinstance(item, dict) for item in json_obj):
            return sorted((sort_json(item) for item in json_obj), key=lambda x: json.dumps(x, sort_keys=True))
        else:
            return [sort_json(item) for item in json_obj]  # Preserve order for non-dict lists

    else:
        return json_obj


def load_json_safely(file_path: str | Path) -> dict | list | None:
    """
    Loads JSON from a file, handling cases where the JSON is invalid,
    contains multiple JSON objects, or needs reformatting.

    Args:
        file_path (Union[str, Path]): The path to the JSON file.

    Returns:
        dict, list, or list[dict]: Parsed JSON data if valid, otherwise None.
    """
    try:
        with open(file_path, encoding="utf-8") as f:
            content = f.read().strip()
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            # Normal parsing failed, try extracting multiple objects
            logging.debug(f"Failed to parse JSON normally in {file_path}: {e}. Attempting fallback formatting.")
            formatted_content = "[{}]".format(content.replace("}\n{", "},{"))
            return json.loads(formatted_content)
    except json.JSONDecodeError as e:
        logging.error(f"❌ JSON decoding error in {file_path}: {e}")
    except Exception as e:
        logging.error(f"❌ Error loading JSON from {file_path}: {e!s}")
    return None


def load_metadata_args(metadata_path: Path) -> str:
    """
    Loads metadata.yaml and returns relevant command-line arguments as a single string.

    Args:
        metadata_path (Path): Path to the metadata.yaml file.

    Returns:
        str: A string containing command-line arguments derived from metadata.
    """
    if not metadata_path.exists():
        return ""

    try:
        with metadata_path.open("r") as meta_file:
            metadata = yaml.safe_load(meta_file) or {}

        return " ".join(f"--{key} {value!s}" for key, value in metadata.items())
    except Exception as e:
        logging.error(f"Error reading metadata.yaml: {e}")
        return ""


def process_test(rit_file: Path, rit_name: str, rit_recording_path: Path) -> bool:
    """
    Executes a single test, compares the actual output with the expected JSON,
    and returns whether the test passed or failed.

    Args:
        rit_file (Path): The path to the RIT YAML file to execute.
        rit_name (str): The name of the RIT test (used for logging).
        rit_recording_path (str): The path to the folder containing the test's recordings (expected JSON).

    Returns:
        bool: True if the test passed, False if it failed.
    """
    actual_output_path = Path(EXECUTOR_CMD_DIR, "actual.json")
    expected_output_path = Path(rit_recording_path, "expected.json")
    metadata_path = Path(rit_recording_path, "metadata.yaml")
    metadata_args = load_metadata_args(metadata_path)

    # Run the executor with the RIT file
    cmd = ["./rit-executor", str(rit_file.absolute()), "--mock", "replay"] + metadata_args.split()
    try:
        # Run executor and capture the output
        with open(actual_output_path, "w") as output_file:
            subprocess.run(cmd, cwd=EXECUTOR_CMD_DIR, check=True, stdout=output_file, stderr=subprocess.PIPE)
        # Check if expected JSON exists
        if not expected_output_path.exists():
            logging.error(f"Expected JSON missing for {rit_name}: {expected_output_path}")
            return False

        expected_json = load_json_safely(expected_output_path)
        actual_json = load_json_safely(actual_output_path)

        sorted_expected_json = sort_json(expected_json)
        sorted_actual_json = sort_json(actual_json)

        if sorted_expected_json != sorted_actual_json:
            diff = "\n".join(
                difflib.unified_diff(
                    json.dumps(sorted_expected_json, indent=4).splitlines(),
                    json.dumps(sorted_actual_json, indent=4).splitlines(),
                    fromfile="expected.json",
                    tofile="actual.json",
                )
            )
            logging.error(f"❌{RED} Mismatch in output for {rit_name}:\n{diff}" + NC)
            return False
        else:
            logging.info(f"✅{GREEN} Success: {rit_name} output matches expected JSON!" + NC)
            return True

    except subprocess.CalledProcessError as e:
        logging.error(f"❌ Execution failed for {rit_name}: {e.stderr.decode().strip()}")
    except json.JSONDecodeError:
        logging.error(f"❌ JSON decoding error for {rit_name}: Check actual.json or expected.json")

    return False


def find_rit_files() -> list[Path]:
    """
    Find all YAML files inside aws, azure, gcp folders.

    Returns:
        List[Path]: A list of paths to RIT YAML files.
    """
    return list(RIT_ROOT_DIR.rglob("*.yml")) + list(RIT_ROOT_DIR.rglob("*.yaml"))


def copy_recordings(rit_recording_path: Path) -> None:
    """
    Copy recordings to executor cmd directory.

    Args:
        rit_recording_path (Path): The path to the folder containing the test's recordings.
    """
    for item in rit_recording_path.rglob("*"):
        if item.is_file():
            shutil.copy2(item, EXECUTOR_CMD_DIR)


def cleanup_recordings(rit_recording_path: Path) -> None:
    """
    Delete the copied files from the destination folder after execution.

    Args:
        rit_recording_path (Path): The path to the folder containing the test's recordings.
    """
    for item in rit_recording_path.rglob("*"):
        if item.is_file():
            try:
                (EXECUTOR_CMD_DIR / item.name).unlink()
                logging.debug(f"✅ Deleted {item.name} from {EXECUTOR_CMD_DIR}")
            except Exception as e:
                logging.error(f"❌ Failed to delete {item.name}: {e!s}")


def log_results(passed_tests: list[str], failed_tests: list[str], total_tests: int) -> None:
    """
    Log the test results.

    Args:
        passed_tests (List[str]): List of passed tests names.
        failed_tests (List[str]): List of failed test names.
        total_tests (int): Total number of tests.
    """
    logging.info(
        f"\n{CYAN}{BOLD}Test Results:\nTotal: {total_tests}\n{NC}"
        f"✅{GREEN}{BOLD} Passed: {len(passed_tests)}{NC}\n"
        f"{RED}{BOLD}❌ Failed: {len(failed_tests)}ֿ{NC}"
    )
    if failed_tests:
        logging.error(f"{RED}{BOLD}❌ Failed RIT tests:\n" + "\n".join(failed_tests) + NC)
        sys.exit(1)
    else:
        logging.debug("✅ Passed RIT tests:\n" + "\n".join(failed_tests))
        logging.info(f"{GREEN}{BOLD}All RIT tests passed successfully!{NC}")


def main():
    """
    Main function that initializes logging, processes each RIT test file,
    runs the tests, and logs the results.

    It handles all aspects of test execution, including file management,
    comparing outputs, and providing a summary of test successes and failures.
    """
    install_logging("rit_executor.log")
    passed_tests = []
    failed_tests = []

    if not EXECUTOR_CMD_DIR.exists():
        logging.error(f"Executor directory not found: {EXECUTOR_CMD_DIR}")
        sys.exit(1)

    rit_files = find_rit_files()

    for rit_file in rit_files:
        rit_name = rit_file.stem
        rit_recording_path = RECORDINGS_DIR_PATH / rit_name

        if not rit_recording_path.exists():
            logging.warning(f"Recording folder not found for {rit_name}: {rit_recording_path}")
            continue

        copy_recordings(rit_recording_path)

        if process_test(rit_file, rit_name, rit_recording_path):
            passed_tests.append(rit_name)
        else:
            failed_tests.append(rit_name)

        cleanup_recordings(rit_recording_path)

    log_results(passed_tests, failed_tests, len(rit_files))


if __name__ == "__main__":
    main()
