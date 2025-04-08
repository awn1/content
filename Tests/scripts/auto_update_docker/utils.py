import csv
import json
from typing import Any

STATE_FILE_FIELD_NAMES = ["docker_image", "docker_tag", "last_pr_number", "batch_number", "batches_config"]


def load_json_file(path: str) -> dict[str, Any]:
    """
    Load and parse a JSON file from the given path.

    Args:
        path (str): The file path of the JSON file to be loaded.

    Returns:
        dict[str, Any]: A dictionary containing the parsed JSON data.
    """
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json_file(path: str, data: dict[str, Any] | list[Any], sort_keys: bool = True) -> None:
    """
    Save a dictionary to a JSON file sorted in ascending order in the given path.
    Args:
        path (str): The file path of the JSON file to be saved.
        data (dict[str, Any]): A dictionary containing the parsed JSON data.
        sort_keys (bool): Whether to sort keys in the JSON file.
    """
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, sort_keys=sort_keys)


def load_csv_file(file_path: str, index_name: str) -> dict[str, Any]:
    """
    Load a CSV file and convert it to a dictionary.

    This function reads a CSV file from the given path, sets the 'docker_image' column
    as the index.

    Args:
        file_path (str): The path to the CSV file to be loaded.
        index_name (str): The index of the CSV file to be loaded.

    Returns:
        dict[str, Any]: A dictionary where keys are docker image names and values are
        dictionaries containing the corresponding row data from the CSV.
    """
    result: dict = {}
    with open(file_path) as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            index_value = row.pop(index_name)
            result[index_value] = row

    return result


def save_csv_file(file_path: str, data: dict[str, Any], index_name: str, field_names: list[str]) -> None:
    """
    Save a dictionary to a CSV file.

    This function converts the input dictionary to a CSV file, sets the index name
    to 'docker_image'.

    Args:
        file_path (str): The path where the CSV file will be saved.
        data (dict[str, Any]): A dictionary where keys are docker image names and values
                               are dictionaries containing the corresponding data.
        index_name (str): The index of the CSV file to be saved.
        field_names: (list[str]): The names of the fields in the CSV file.

    Returns:
        None

    Note:
        The resulting CSV file will have 'docker_image' as the first column, followed by
        all other key-value pairs from the nested dictionaries as additional columns.
    """
    with open(file_path, "w", newline="") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=field_names)

        writer.writeheader()
        for index, data in data.items():
            row = {index_name: index, **data}
            writer.writerow(row)
