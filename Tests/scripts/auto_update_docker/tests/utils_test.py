import json
import os
import tempfile

from Tests.scripts.auto_update_docker.utils import load_csv_file, load_json_file, save_csv_file, save_json_file


def test_load_json_file():
    """
    Given:
    - A temporary file with JSON content '{"key": "value"}'

    When:
    - The load_json_file function is called with the path to this temporary file

    Then:
    - The function should return a Python dictionary {"key": "value"}
    - The temporary file should be deleted after the operation
    """
    with tempfile.NamedTemporaryFile(mode="w", delete=False) as temp_file:
        temp_file.write('{"key": "value"}')

    result = load_json_file(temp_file.name)
    assert result == {"key": "value"}
    os.unlink(temp_file.name)


def test_save_json_file_dict():
    """
    Given:
    - A Python dictionary {'b': 2, 'a': 1, 'c': 3}
    - A temporary file path

    When:
    - The save_json_file function is called with this dictionary and file path

    Then:
    - The function should create a JSON file at the specified path
    - The JSON file should contain the dictionary data with keys sorted alphabetically
    - The loaded JSON data should match the original dictionary
    - The keys in the saved file should be in the order ['a', 'b', 'c']
    - The temporary file should be deleted after the operation
    """
    test_data = {"b": 2, "a": 1, "c": 3}
    temp_file = tempfile.NamedTemporaryFile(mode="w", delete=False)
    temp_file.close()

    save_json_file(temp_file.name, test_data)
    with open(temp_file.name) as f:
        saved_data = json.load(f)

    assert saved_data == dict(sorted(test_data.items()))
    assert list(saved_data.keys()), ["a", "b", "c"]

    os.unlink(temp_file.name)


def test_save_json_file_no_sort():
    """
    Given:
    - A Python dictionary {'b': 2, 'a': 1, 'c': 3}
    - A temporary file path

    When:
    - The save_json_file function is called with this dictionary, file path, and sort_keys=False

    Then:
    - The function should create a JSON file at the specified path
    - The JSON file should contain the dictionary data with keys in their original order
    - The 'b' key should appear before the 'a' key in the saved file
    - The temporary file should be deleted after the operation
    """
    test_data = {"b": 2, "a": 1, "c": 3}
    temp_file = tempfile.NamedTemporaryFile(mode="w", delete=False)
    temp_file.close()

    save_json_file(temp_file.name, test_data, sort_keys=False)
    with open(temp_file.name) as f:
        content = f.read()

    assert content.index("b") < content.index("a")

    os.unlink(temp_file.name)


def test_load_csv_file():
    """
    Given:
    - A temporary CSV file with content:
      'docker_image,batch_number
       image1,1
       image2,2'

    When:
    - The load_csv_file function is called with the path to this temporary file and 'docker_image' as the key field

    Then:
    - The function should return a dictionary:
      {
          'image1': {'batch_number': '1'},
          'image2': {'batch_number': '2'}
      }
    - The temporary file should be deleted after the operation
    """
    expected = {"image1": {"batch_number": "1"}, "image2": {"batch_number": "2"}}
    with tempfile.NamedTemporaryFile(mode="w", delete=False) as temp_file:
        temp_file.write("docker_image,batch_number\nimage1,1\nimage2,2")

    result = load_csv_file(temp_file.name, "docker_image")

    assert result == expected

    os.unlink(temp_file.name)


def test_save_csv_file():
    """
    Given:
    - A Python dictionary:
      {
          'image1': {'batch_number': '1'},
          'image2': {'batch_number': '2'}
      }
    - A temporary file path

    When:
    - The save_csv_file function is called with this dictionary, file path, 'docker_image' as the key field,
      and ['docker_image', 'batch_number'] as the field names

    Then:
    - The function should create a CSV file at the specified path
    - The CSV file should contain the data in the correct format
    - Loading the created CSV file should return a dictionary identical to the original input
    - The temporary file should be deleted after the operation
    """
    data = {"image1": {"batch_number": "1"}, "image2": {"batch_number": "2"}}
    with tempfile.NamedTemporaryFile(mode="w", delete=False) as temp_file:
        save_csv_file(temp_file.name, data, "docker_image", ["docker_image", "batch_number"])

    result = load_csv_file(temp_file.name, "docker_image")

    assert result == data
    os.unlink(temp_file.name)
