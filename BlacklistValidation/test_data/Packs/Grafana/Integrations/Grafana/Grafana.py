import demistomock as demisto  # noqa: F401
from CommonServerPython import *  # noqa: F401
from CommonServerUserPython import *  # noqa

''' CONSTANTS '''

DATE_FORMAT = '%Y-%m-%dT%H:%M:%SZ'  # ISO8601 format with UTC, default in XSOAR


''' HELPER FUNCTIONS '''


def paging_heading(page_number: str = None, page_size: str = None):
    if page_number or page_size:
        return 'Showing' + (f' {page_size}' if page_size else '') + ' results' + \
               (f' from page {page_number}' if page_number else '') + ':\n'
    return ''


''' MAIN FUNCTION '''


def main():
    """main function, parses params and runs command functions
    """
    pass


''' ENTRY POINT '''

if __name__ in ['__main__', 'builtin', 'builtins']:
    main()
