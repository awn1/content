import pytest
from requests_mock import MockerCore

from Tests.sdk_release.create_release import compile_changelog, fetch_changelog


@pytest.fixture
def mock_changelog():
    return """
## 1.2.3 (2024-11-04)

### Breaking
- Breaking change 1 [#123](https://github.com/example/repo/pull/123)

### Feature
- New feature 1 [#124](https://github.com/example/repo/pull/124)
- New feature 2 [#125](https://github.com/example/repo/pull/125)

### Fix
- Bug fix 1 [#126](https://github.com/example/repo/pull/126)

### Internal
- Internal change 1 [#127](https://github.com/example/repo/pull/127)

## 1.2.2

### Breaking
- Breaking change 1 [#123](https://github.com/example/repo/pull/123)
"""


def test_compile_changelog(mock_changelog: str):
    result = compile_changelog(mock_changelog)

    expected_output = """
### Breaking
- Breaking change 1 [#123](https://github.com/example/repo/pull/123)

### Feature
- New feature 1 [#124](https://github.com/example/repo/pull/124)
- New feature 2 [#125](https://github.com/example/repo/pull/125)

### Fix
- Bug fix 1 [#126](https://github.com/example/repo/pull/126)

### Internal
- Internal change 1 [#127](https://github.com/example/repo/pull/127)
"""

    assert result.strip() == expected_output.strip()


def test_compile_changelog_slack_format(mock_changelog: str):
    result = compile_changelog(mock_changelog, text_format="slack")

    expected_output = """### Breaking
- Breaking change 1 <https://github.com/example/repo/pull/123|#123>

### Feature
- New feature 1 <https://github.com/example/repo/pull/124|#124>
- New feature 2 <https://github.com/example/repo/pull/125|#125>

### Fix
- Bug fix 1 <https://github.com/example/repo/pull/126|#126>

### Internal
- Internal change 1 <https://github.com/example/repo/pull/127|#127>
"""

    assert result.strip() == expected_output.strip()


def test_fetch_changelog(requests_mock: MockerCore):
    requests_mock.get("https://raw.githubusercontent.com/demisto/demisto-sdk/1.2.3/CHANGELOG.md", text="Mocked changelog")
    result = fetch_changelog("1.2.3")
    assert result == "Mocked changelog"
