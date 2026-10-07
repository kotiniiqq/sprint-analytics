from datetime import datetime, timezone, timedelta

import pytest

from sprint_analytics.worktime import business_hours

UTC = timezone.utc


def dt(day, hour, minute=0):
    # 2026-09-07 is a Monday
    return datetime(2026, 9, day, hour, minute, tzinfo=UTC)


def test_same_day_span():
    assert business_hours(dt(7, 10), dt(7, 13, 30)) == 3.5


def test_weekend_and_off_hours():
    # Fri 16:00 -> Mon 11:00 = 2h Friday + 2h Monday
    assert business_hours(dt(11, 16), dt(14, 11)) == 4.0
    # starts before 09:00 and ends after 18:00 on the same day = full 9h
    assert business_hours(dt(8, 6), dt(8, 22)) == 9.0
    # entirely on a Saturday
    assert business_hours(dt(12, 10), dt(12, 15)) == 0.0


def test_multi_day_span():
    # Mon 09:00 -> Wed 18:00 = 27h
    assert business_hours(dt(7, 9), dt(9, 18)) == 27.0


def test_end_before_start_is_zero():
    assert business_hours(dt(9, 12), dt(9, 10)) == 0.0


def test_other_timezone_is_converted_to_utc():
    kyiv = timezone(timedelta(hours=3))
    start = datetime(2026, 9, 7, 13, 0, tzinfo=kyiv)  # 10:00 UTC
    end = datetime(2026, 9, 7, 15, 0, tzinfo=kyiv)    # 12:00 UTC
    assert business_hours(start, end) == 2.0


def test_naive_datetime_rejected():
    with pytest.raises(ValueError):
        business_hours(datetime(2026, 9, 7, 10), dt(7, 12))
