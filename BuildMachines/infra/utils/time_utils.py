from datetime import datetime

import pendulum


def to_epoch_timestamp(date: pendulum.DateTime = None) -> int:
    """Return int epoch timestamp in milliseconds from date object"""
    date = date or time_now()
    timestamp = date.timestamp() * 1000
    return int(round(timestamp))


def time_now() -> pendulum.DateTime:
    return pendulum.now(tz='UTC')


class RocketDateTime(pendulum.DateTime):
    """RocketDateTime inherits pendulum DateTime and can be used as a type for Pydantic by parsing any time format"""

    def __new__(
        cls,
        year=0,
        month=0,
        day=0,
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
        tzinfo=None,
        fold=0,
        timestamp=None,
    ):
        date_value = cls._parse(timestamp) if timestamp else pendulum.datetime(year, month, day, hour, minute, second,
                                                                               microsecond, tzinfo)
        return super().__new__(
            cls,
            year=date_value.year,
            month=date_value.month,
            day=date_value.day,
            hour=date_value.hour,
            minute=date_value.minute,
            second=date_value.second,
            microsecond=date_value.microsecond,
            tzinfo=date_value.tzinfo,
        )

    @classmethod
    def __get_validators__(cls):
        yield cls.validate_type

    @classmethod
    def validate_type(cls, value):
        return cls(timestamp=value)

    @classmethod
    def _parse(cls, value) -> pendulum.DateTime:
        if isinstance(value, pendulum.DateTime):
            return value
        if isinstance(value, int):
            return pendulum.from_timestamp(value / 1000, tz='UTC')
        if isinstance(value, datetime):
            return pendulum.instance(value).in_tz('UTC')
        return pendulum.parse(value, tz='UTC')
