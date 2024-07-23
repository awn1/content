"""
Various utility methods for working with files
"""

import json
import logging
from json import JSONDecodeError
from pathlib import Path

logger = logging.getLogger(__name__)


def read_json_file(path: Path) -> dict:
    """Read json file from path, raises exception if file doesn't exist/invalid json"""
    try:
        return json.loads(path.read_text())
    except (JSONDecodeError, FileNotFoundError) as e:
        logger.error(f"Failed parsing json file at {path}: {e}")
        raise
