from dataclasses import dataclass
from enum import Enum


class TimeRange(str, Enum):
    HOUR_1 = "1h"
    HOURS_6 = "6h"
    HOURS_12 = "12h"
    DAY_1 = "1d"
    DAYS_7 = "7d"
    DAYS_30 = "30d"
    MONTHS_3 = "3m"
    MONTHS_6 = "6m"
    YEAR_1 = "1y"
    FOREVER = "forever"


@dataclass(frozen=True)
class TimeRangeSpec:
    start: str
    window: str


TIME_RANGE_SPECS = {
    TimeRange.HOUR_1: TimeRangeSpec(start="-1h", window="1m"),
    TimeRange.HOURS_6: TimeRangeSpec(start="-6h", window="5m"),
    TimeRange.HOURS_12: TimeRangeSpec(start="-12h", window="10m"),
    TimeRange.DAY_1: TimeRangeSpec(start="-1d", window="15m"),
    TimeRange.DAYS_7: TimeRangeSpec(start="-7d", window="1h"),
    TimeRange.DAYS_30: TimeRangeSpec(start="-30d", window="6h"),
    TimeRange.MONTHS_3: TimeRangeSpec(start="-3mo", window="12h"),
    TimeRange.MONTHS_6: TimeRangeSpec(start="-6mo", window="1d"),
    TimeRange.YEAR_1: TimeRangeSpec(start="-1y", window="2d"),
    TimeRange.FOREVER: TimeRangeSpec(start="0", window="7d"),
}


def get_time_range_spec(period: TimeRange) -> TimeRangeSpec:
    return TIME_RANGE_SPECS[period]


def get_legacy_hours_spec(hours: int) -> TimeRangeSpec:
    if not 1 <= hours <= 8760:
        raise ValueError("hours must be between 1 and 8760")

    if hours <= 1:
        window = "1m"
    elif hours <= 6:
        window = "5m"
    elif hours <= 12:
        window = "10m"
    elif hours <= 24:
        window = "15m"
    elif hours <= 24 * 7:
        window = "1h"
    elif hours <= 24 * 30:
        window = "6h"
    else:
        window = "1d"

    return TimeRangeSpec(start=f"-{hours}h", window=window)
