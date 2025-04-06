import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from rit_executor import load_json_safely

from Tests.scripts.utils import logging_wrapper as logging
from Tests.scripts.utils.log_util import install_logging

# Running Example:
# python generate_recordings.py
#     /path/to/prisma-collectors/asset-collection/azure/azure-app-service-plan.yaml
#     --executor-dir "/path/to/rit-executor"
#     --output-dir /path/to/prisma-collectors/TestData/Recordings
#     --executor-params "--region eastus"
#     --override


def run_command(command: str) -> bool:
    """
    Executes a shell command and logs its output.

    Args:
        command (str): The shell command to execute.

    Returns:
        bool: True if the command executes successfully, False otherwise.
    """
    try:
        subprocess.run(command, shell=True, check=True, capture_output=True)
        logging.info(f"✅ Command executed successfully: {command}")
        return True
    except subprocess.CalledProcessError as e:
        logging.error(f"❌ Command failed: {command}\nError: {e}")
        return False  # Return False on failure


def create_metadata_file(output_dir: Path) -> None:
    """
    Creates metadata.yaml for running rit-executor in non-default regions.

    Reads expected.json from the given output directory, extracts the __region value,
     and if it's not "us-east1" (the default), generates metadata.yaml.
     This ensures rit-executor runs with the correct region.
    """
    expected_json_path = output_dir / "expected.json"
    metadata_path = output_dir / "metadata.yaml"

    if not expected_json_path.exists():
        logging.warning(f"⚠️ expected.json not found in {output_dir}. Skipping metadata creation.")
        return

    try:
        data = load_json_safely(expected_json_path)
        region = find_region(data)
        if region and region != "us-east1":
            metadata_content = f"region: {region}\n"
            metadata_path.write_text(metadata_content)
            logging.info(f"📝 Created metadata.yaml with region: {region}")
    except Exception as e:
        logging.error(f"❌ Error reading expected.json: {e}")


def find_region(data: dict | list | None) -> str | None:
    """
    Recursively searches for the `__region` key in a nested data structure.

    Args:
        data (dict | list | None): A JSON-compatible data structure that may contain the `__region` key.

    Returns:
        str | None: The value of `__region` if found, otherwise None.
    """
    if isinstance(data, dict):
        for key, value in data.items():
            if key == "__region":
                return value
            result = find_region(value)
            if result:
                return result
    elif isinstance(data, list):
        for item in data:
            result = find_region(item)
            if result:
                return result
    return None  # Return None if `__region` is not found


def delete_json_files(directory: Path):
    """
    Deletes all JSON files in the specified directory.

    Args:
        directory (Path): The directory containing JSON files to be deleted.

    Logs:
        - Info message for each successfully deleted file.
        - Error message if file deletion fails.
    """
    for json_file in directory.glob("*.json"):
        try:
            os.remove(json_file)
            logging.info(f"🗑️ Removed: {json_file.name}")
        except Exception as e:
            logging.error(f"❌ Failed to remove {json_file.name}: {e}")


def process_rit_file(rit_file: Path, executor_cmd_dir: Path, output_dir: Path, executor_params: str, override: bool) -> None:
    """
    Processes a given RIT file using `rit-executor`. Skips processing if the output directory exists
    (unless overridden) or execution fails.

    Steps:
    1. Runs `record` (`--mock record`) to capture API interactions (produces API JSON files).
    2. Runs `replay` (`--mock replay`) using the recorded data to validate outputs (generates `expected.json`).
    3. Moves generated files to the appropriate locations.
    4. Calls `create_metadata_file()` if needed.

    If `expected.json` is empty (`{"Objects": []}`), the test is skipped.

    Args:
        rit_file (Path): The path to the RIT file being processed.
        executor_cmd_dir (Path): The directory containing the `rit-executor` binary.
        output_dir (Path): The directory where processed outputs should be stored.
        executor_params (str): Additional parameters to pass to `rit-executor` - region/account-type/account-override.
        override (bool): Whether to overwrite existing recording folder.

    Returns:
        None
    """
    rit_name = rit_file.stem
    rit_output_dir = output_dir / rit_name

    if rit_output_dir.exists():
        if override:
            logging.info(f"🔄 Overriding {rit_file.name}: Removing existing output folder.")
            shutil.rmtree(rit_output_dir)  # Delete existing directory
        else:
            logging.info(f"⏩ Skipping {rit_file.name}: Output folder already exists.")
            return

    executor_cmd = executor_cmd_dir / "rit-executor"

    # Run the commands (skip to next RIT file if any fails)
    record_command = f"cd {executor_cmd_dir} && {executor_cmd} {rit_file} {executor_params} --mock record"
    if not run_command(record_command):
        logging.warning(f"⚠️ Skipping {rit_file.name} due to failed record command.")
        return

    replay_command = f"cd {executor_cmd_dir} && {executor_cmd} {rit_file} {executor_params} --mock replay > expected.json"

    if not run_command(replay_command):
        logging.warning(f"⚠️ Skipping {rit_file.name} due to failed replay.")
        delete_json_files(executor_cmd_dir)
        return

    expected_file = executor_cmd_dir / "expected.json"
    if expected_file.exists():
        data = load_json_safely(expected_file)
        if data == {"Objects": []}:
            logging.info("🗑️ Expected file is empty. Deleting JSON files...")
            delete_json_files(executor_cmd_dir)
            return

    # Move generated files
    apis_dir = rit_output_dir / "apis"
    apis_dir.mkdir(parents=True, exist_ok=True)

    for file in executor_cmd_dir.glob("*.json"):
        dest = rit_output_dir if file.name == "expected.json" else apis_dir
        shutil.move(str(file), str(dest / file.name))
        logging.info(f"📁 Moved {file.name} to {dest}")

    create_metadata_file(rit_output_dir)


def options_handler() -> argparse.Namespace:
    """
    Parses and handles command-line arguments.

    Returns:
        argparse.Namespace: The parsed command-line arguments.
    """
    parser = argparse.ArgumentParser(description="Process RIT files with rit-executor.")
    parser.add_argument("rit_paths", nargs="+", help="List of RIT file paths or directories to process.")
    parser.add_argument("--executor-dir", required=True, help="Path to the rit-executor directory.")
    parser.add_argument("--output-dir", required=True, help="Path to the output recordings directory.")
    parser.add_argument("--executor-params", default="", help="Additional parameters for rit-executor.")
    parser.add_argument("--override", action="store_true", help="If set, existing recordings will be overwritten.")

    return parser.parse_args()


def main() -> None:
    """
    Main function that processes a list of RIT files using `rit-executor`.

    Steps:
    1. Initializes logging.
    2. Parses command-line arguments.
    3. Resolves paths for the executor and output directory.
    4. Collects RIT files from the provided paths.
    5. Iterates over each RIT file and processes it using `process_rit_file()`.

    If no valid RIT files are found, the script exits with an error.
    """
    install_logging("generate_recordings.log", logger=logging)
    args = options_handler()

    executor_cmd_dir = Path(args.executor_dir).resolve()
    output_dir = Path(args.output_dir).resolve()

    rit_files: list[Path] = []
    for path in args.rit_paths:
        path = Path(path)
        if path.is_dir():
            rit_files.extend(path.glob("*.yaml"))
            rit_files.extend(path.glob("*.yml"))
        elif path.is_file():
            rit_files.append(path)
        else:
            logging.warning(f"⚠️ Skipping {path}: Not a valid file or directory.")

    if not rit_files:
        logging.warning("⚠️ No RIT files found.")
        sys.exit(1)  # Exit if no files are found

    for rit_file in rit_files:
        logging.info(f"▶️ Processing {rit_file}...")
        process_rit_file(rit_file, executor_cmd_dir, output_dir, args.executor_params, args.override)

    logging.info("✅ All RIT files processed successfully.")


if __name__ == "__main__":
    main()
