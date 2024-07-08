import pytest

from Grafana import paging_heading

no_page_number = (None, '100', 'Showing 100 results:\n')
no_page_size = ('50', None, 'Showing results from page 50:\n')
no_page_number_size = (None, None, '')
page_number_size = ('1', '20', 'Showing 20 results from page 1:\n')
PAGING_HEADING = (no_page_number, no_page_size, no_page_number_size, page_number_size)


@pytest.mark.parametrize('page_number, page_size, expected_output', PAGING_HEADING)
def test_paging_heading(page_number, page_size, expected_output):
    """

    Given:
        - 'page_number' and 'page_size' arguments are or aren't given to commands that have paging

    When:
        - A command that has paging is executed

    Then:
        - Returns the right sentence to write in the beginning of the readable output

    """
    assert paging_heading(page_number, page_size) == expected_output
