from datetime import datetime, timedelta, timezone

from app.time_ranges import TimeRange


RANGE_DELTAS = {
    TimeRange.HOUR_1: timedelta(hours=1), TimeRange.HOURS_6: timedelta(hours=6),
    TimeRange.HOURS_12: timedelta(hours=12), TimeRange.DAY_1: timedelta(days=1),
    TimeRange.DAYS_7: timedelta(days=7), TimeRange.DAYS_30: timedelta(days=30),
    TimeRange.MONTHS_3: timedelta(days=90), TimeRange.MONTHS_6: timedelta(days=180),
    TimeRange.YEAR_1: timedelta(days=365), TimeRange.FOREVER: timedelta(days=3650),
}


def range_start(period: TimeRange, now: datetime) -> datetime:
    return now - RANGE_DELTAS[period]


def build_intervals(events: list[dict], active_values: set[str], now: datetime) -> list[dict]:
    intervals = []
    active_at = None
    for event in sorted(events, key=lambda item: item["time"]):
        active = str(event["value"]).lower() in active_values
        if active and active_at is None:
            active_at = event["time"]
        elif not active and active_at is not None:
            intervals.append({"start": active_at, "end": event["time"], "active": False})
            active_at = None
    if active_at is not None:
        intervals.append({"start": active_at, "end": now, "active": True})
    return intervals
