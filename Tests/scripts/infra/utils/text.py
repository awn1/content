import hashlib
import random
import string
import uuid
from distutils.util import strtobool
from typing import Any

from faker import Faker
from faker.providers import internet


class ConnectorName:
    """Read-only data descriptor to get the name of a connector"""

    def __set_name__(self, owner, name):
        self.name = owner.__name__.lower()

    def __get__(self, obj, type=None) -> str:
        return self.name

    def __set__(self, instance, value):
        raise AttributeError("Connector name cannot be overwritten")


def generate_random_string(lowercase=True, uppercase=True, digits=True, length=6) -> str:
    if not any((lowercase, uppercase, digits)):
        raise TypeError("at least 1 option lowercase, uppercase or digits must be selected")

    str_options = ""
    if lowercase:
        str_options += string.ascii_lowercase
    if uppercase:
        str_options += string.ascii_uppercase
    if digits:
        str_options += string.digits
    text = "".join(random.choices(str_options, k=length))
    return text


def str_to_bool(text: str | bool) -> bool:
    return text if isinstance(text, bool) else bool(strtobool(text))


def guid_generator() -> uuid.UUID:
    return uuid.uuid4()


def random_ip(as_public_ip: bool = True) -> str:
    faker = Faker()
    return faker.ipv4_public() if as_public_ip else faker.ipv4_private()


def random_domain() -> str:
    faker = Faker()
    faker.add_provider(internet)
    return faker.domain_name()


def random_email() -> str:
    faker = Faker()
    faker.add_provider(internet)
    return faker.email()


def md5_hash(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def sha_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def sha256_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def to_lower_camel_case(text: str) -> str:
    _string = text.title().replace("_", "")
    return _string[:1].lower() + _string[1:]


def to_list(value: Any) -> list[Any]:
    """covert any given value to list, in case of None return empty list"""
    if not isinstance(value, list):
        value = [value] if value is not None else []
    return value


def convert_dot_notation_to_dict(*args) -> dict:
    """
    Convert dot notation string to dicts. For example:
        key = ('foo.bar.baz', 'baz_value')
        key2 = ('foo.bar.baq', 'baq_value')
        key3 = ('foo.baq', 'name_value')
        convert_dot_notation_to_dict(key, key2, key3)
        >> {'foo': {'bar': {'baz': 'baz_value', 'baq': 'baq_value'}, 'baq': 'name_value'}}
    """
    res: dict[Any, Any] = {}
    for k, v in args:
        res_tmp = res
        levels = k.split(".")
        for level in levels[:-1]:
            res_tmp = res_tmp.setdefault(level, {})
        res_tmp[levels[-1]] = v
    return res


def convert_mb_to_bytes(mb: int | float) -> int:
    """Convert MB to Bytes"""
    return int((2**10) ** 2 * mb)


def sanitize_text_for_json_parsing(text: str) -> str:
    """Sanitizes input text by replacing certain characters, ensuring JSON parsability without altering the code block"""
    return text.replace(r"\'", "").replace('"', r"\"").replace("\\n", " ")


def remove_empty_elements(data: dict[str, Any]) -> dict[str, Any]:
    """
    Remove empty elements from a dictionary recursively.

    Args:
        data (dict[str, Any]): The input dictionary to process.

    Returns:
        dict[str, Any]: A new dictionary with empty elements removed.
    """

    def empty(x):
        return x in (None, {}, [], "")

    if not isinstance(data, dict | list):
        return data

    return {k: v for k, v in ((k, remove_empty_elements(v)) for k, v in data.items()) if not empty(v)}
