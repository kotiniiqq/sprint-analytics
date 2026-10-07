"""Business-hours arithmetic: Mon–Fri, 09:00–18:00 UTC.

Cycle time measured in calendar hours punishes a ticket for the weekend it sat
through; teams reason in working hours, so every duration here is one.
"""
from datetime import datetime, time, timedelta, timezone

DAY_START = time(9, 0)
DAY_END = time(18, 0)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"naive datetime {value!r}: pass a timezone-aware value")
    return value.astimezone(timezone.utc)


def business_hours(start: datetime, end: datetime) -> float:
    """Working hours between two moments, clipped to 09:00–18:00 on weekdays."""
    start, end = _utc(start), _utc(end)
    if end <= start:
        return 0.0
    total = timedelta()
    day = start.date()
    while day <= end.date():
        if day.weekday() < 5:
            window_start = datetime.combine(day, DAY_START, tzinfo=timezone.utc)
            window_end = datetime.combine(day, DAY_END, tzinfo=timezone.utc)
            lo, hi = max(start, window_start), min(end, window_end)
            if hi > lo:
                total += hi - lo
        day += timedelta(days=1)
    return round(total.total_seconds() / 3600, 2)
