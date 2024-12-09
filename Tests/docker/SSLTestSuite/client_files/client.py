import argparse

import demistomock as demisto  # noqa: F401
from CommonServerPython import *  # noqa: F401


class Client(BaseClient):
    def get_test(self) -> Dict[str, Any]:
        return self._http_request(
            method="GET",
            url_suffix="/",
        )


def main(verify=True):
    client = Client(
        base_url="https://nginx-container",
        verify=verify,
    )
    res = client.get_test()
    print(res)


if __name__ in ("__main__", "__builtin__", " builtins"):
    parser = argparse.ArgumentParser(description="Base Client to send requests.")
    parser.add_argument("-v", "--verify", help="verify parameter to requests", action="store_true")
    options = parser.parse_args()
    main(verify=options.verify)
