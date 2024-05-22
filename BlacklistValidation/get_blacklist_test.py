import os

import pytest


@pytest.mark.parametrize('pack_path, potential_secret, expected_result',
                         [("./test_data/Pack1", "test", True),
                          ("./test_data/Pack1", "test\"", True),
                          ("./test_data/Pack1", "\"test", True),
                          ("./test_data/Pack2", "test", False)])
def test_is_secret_in_secret_ignore(pack_path, potential_secret, expected_result):
    """

    Given:
    - A pack path and a secret that was found in one of the files in Content repo.

    When:
    - Triggering the secrets run against Content master.

    Then:
    - Ensure that the found secret exists in secrets-ignore file.
    """
    from get_blacklist import is_secret_in_secret_ignore
    assert is_secret_in_secret_ignore(pack_path, potential_secret) == expected_result


def test_get_path_parts_to_ignore_substring_secrets():
    """
    Given:
        - A pack path.

    When:
        - Triggering the secrets run against Content master, and finding the the path parts to ignore substrings from them.

    Then:
        - Ensure that all file names were returned for all files in the pack
    """
    from get_blacklist import get_path_parts_to_ignore_substring_secrets
    pack_path = os.path.abspath('test_data/Packs/Grafana')
    assert get_path_parts_to_ignore_substring_secrets(pack_path) \
           == {'Grafana', 'incidenttype-Grafana_Alert', 'keys_to_lowercase', 'command_examples', 'Grafana_description',
               'Grafana_image', 'Grafana_test', 'README', 'pack_metadata'}


no_path_parts = ('capCo', set(), False)
with_path_part_in_it = ('capCo', {'PcapAnalysis', 'PcapConvert', '2_4_3', 'PcapConvert_test'}, True)
with_path_part_in_it_lower = ('capco', {'PcapConvert'}, True)
with_path_part_in_it_upper = ('capCo', {'Pcapconvert'}, True)
with_path_part_not_in = ('capCo', {'PcapAnalysis', '2_4_3'}, False)
SUBSTRING_PATH_PART_INPUT = [no_path_parts, with_path_part_in_it, with_path_part_in_it_lower, with_path_part_not_in]


@pytest.mark.parametrize('potential_secret,files_path_parts,expected_output', SUBSTRING_PATH_PART_INPUT)
def test_is_substring_of_file_path_part(potential_secret, files_path_parts, expected_output):
    """
    Given:
        - A potential_secret to check if is a substring of one of files_path_parts.

    When:
        - Checking if the given potential secret is a real secret.

    Then:
        - Ensure that we got the expected output.
    """
    from get_blacklist import is_substring_of_file_path_part
    assert is_substring_of_file_path_part(potential_secret, files_path_parts) == expected_output
