from requests import HTTPError
from requests.adapters import HTTPAdapter

from infra.utils.html import get_http_error_text

import logging
logger = logging.getLogger(__name__)


def raise_for_status(response):
    """Pretty format and log the HTTP Error if it happens"""
    try:
        truncated_text = f'{response.text[:200]}...' if len(response.text) > 200 else response.text
        logger.debug(f'Response {response.status_code=} text: {truncated_text.strip()}')
        response.raise_for_status()
    except HTTPError as e:
        msg = get_http_error_text(e)
        logger.error(msg)
        raise


class TimeoutHTTPAdapter(HTTPAdapter):
    def __init__(self, *args, **kwargs):
        if "timeout" in kwargs:
            self.timeout = kwargs["timeout"]
            del kwargs["timeout"]
        super().__init__(*args, **kwargs)

    def send(self, request, **kwargs):
        timeout = kwargs.get("timeout")
        if not timeout and hasattr(self, 'timeout'):
            kwargs["timeout"] = self.timeout
        return super().send(request, **kwargs)
