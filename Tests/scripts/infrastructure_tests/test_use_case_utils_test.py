import json
import tempfile
from unittest.mock import mock_open, patch

import pytest

from Tests.scripts.utils.test_use_case_utils import TestUseCaseDataExtractor

TEST_CASES = [
    (
        """
{
    "marketplaces": ["XSIAM"],
    "additional_needed_packs": {
        "PackOne": "instance_name1",
        "PackTwo": ""
    }
}
    """,
        {"PackOne": "instance_name1", "PackTwo": ""},
    ),
    (
        """
{
    "marketplaces": ["XSOAR"],
    "additional_needed_packs": {
        "PackThree": "instance_name3"
    }
}
    """,
        {"PackThree": "instance_name3"},
    ),
    (
        """
{
    "marketplaces": ["MarketplaceY"],
    "additional_needed_packs": {}
}
    """,
        {},
    ),
    (
        """
{
    "marketplaces": ["AnotherMarket"],
    "additional_needed_packs": {
        "PackA": "instanceA",
        "PackB": "instanceB",
        "PackC": "instanceC"
    }
}
    """,
        {"PackA": "instanceA", "PackB": "instanceB", "PackC": "instanceC"},
    ),
    (
        """
{
    "marketplaces": [],
    "additional_needed_packs": {
        "SinglePack": "single_instance"
    }
}
    """,
        {"SinglePack": "single_instance"},
    ),
]


def create_temp_file_with_docstring(docstring, prefix="temp", suffix=".txt"):
    """
    Create a temporary file with the specified docstring written to it.

    Parameters:
        docstring (str): The content to write to the temporary file.
        prefix (str): The prefix for the temporary file name.
        suffix (str): The suffix for the temporary file name, commonly used to define file type.

    Returns:
        str: The file path of the created temporary file.
    """
    with tempfile.NamedTemporaryFile(mode="w+t", delete=True, suffix=suffix) as temp_file:
        temp_file.write(docstring)
        temp_file.flush()

        return temp_file


@pytest.mark.parametrize("file_content, expected_output", TEST_CASES)
def test_extract_config(file_content, expected_output):
    temp_file = create_temp_file_with_docstring(file_content, suffix=".py")

    with patch("builtins.open", mock_open(read_data='''\n"""''' + file_content + '''\n"""\n''')):
        result = TestUseCaseDataExtractor().extract_config(temp_file.name)
        assert result["additional_needed_packs"] == expected_output

    temp_file.close()


@pytest.mark.parametrize(
    "file_content, expected_packs",
    [
        (TEST_CASES[0][0], ["PackOne", "PackTwo"]),
        (TEST_CASES[1][0], ["PackThree"]),
        (TEST_CASES[2][0], []),
        (TEST_CASES[3][0], ["PackA", "PackB", "PackC"]),
        (TEST_CASES[4][0], ["SinglePack"]),
    ],
)
def test_get_additional_packs_data(file_content, expected_packs):
    with patch("builtins.open", mock_open(read_data=file_content)):
        with patch("Tests.scripts.utils.test_use_case_utils.TestUseCaseDataExtractor.extract_config") as mock_extract:
            mock_extract.return_value = {"additional_needed_packs": json.loads(file_content)["additional_needed_packs"]}
            result = TestUseCaseDataExtractor().get_additional_packs_data("dummy_path")
            assert result == expected_packs
