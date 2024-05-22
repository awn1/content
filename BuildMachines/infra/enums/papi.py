from enum import Enum

from more_itertools import first


class SearchByPeriod(Enum):
    """
    Consts from xsoar server code: https://gitlab.xdr.pan.local/xdr/xsoar/server/-/blob/dev/domain/filters.go#L15
    User to search incidents via Public API by period of time.
    """

    MINUTES = "minutes"
    HOURS = "hours"
    DAYS = "days"
    WEEKS = "weeks"
    MONTHS = "months"
    YEARS = "years"

    def get_time_to_abstract_by_period(self, diff: int) -> dict[str, int]:
        return {self.value: diff}


class KeySecurityLevel(Enum):
    """API Key has one of two security levels, normal or advanced"""

    STANDARD = "standard", "SEC_010_NORMAL"
    ADVANCED = "advanced", "SEC_020_HIGH"

    def __init__(self, common_name: str, internal_name: str):
        self.common_name = common_name
        self.internal_name = internal_name

    @classmethod
    def _missing_(cls, value):
        return first(i for i in cls if i.value == value or i.internal_name == value)

    @property
    def value(self):
        return self.common_name
