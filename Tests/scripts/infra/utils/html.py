from typing import Optional

from bs4 import BeautifulSoup
from requests import HTTPError

ALLOWED_HTML_TAGS = ['strong', 'code', 'br', 'pre']


def find_html_attribute(html_content, name: str) -> Optional[str]:
    """Parse html content and return the value of first attribute with requested name, or None if the attribute wasn't found"""
    soup = BeautifulSoup(html_content, features="html.parser")
    if element := soup.find(attrs={"name": name}):
        return element.get('value')
    return None


def find_html_form_action(html_content: str) -> Optional[str]:
    """Parse html content and return the first form action"""
    soup = BeautifulSoup(html_content, features="html.parser")
    if form := soup.find('form'):
        return form.get('action', None)
    return None


def strip_html_tags(html_content: str, allowed_tags: list = ALLOWED_HTML_TAGS) -> BeautifulSoup:
    soup = BeautifulSoup(html_content, features="html.parser")
    for page_element in soup.find_all():
        if page_element.name not in allowed_tags:
            page_element.unwrap()
    return soup


def get_http_error_text(http_error: HTTPError, add_html_tags=False) -> str:
    """Return human-readable text from HTTPError"""
    status_code = http_error.response.status_code
    text = http_error.response.text
    url = http_error.request.url
    method = http_error.request.method
    msg_text = f'<pre><code>{text}</code></pre>' if add_html_tags else text
    return f'Got {status_code=} for {method=} to {url=}. Response text: {msg_text.strip()}'
