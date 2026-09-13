"""ACCEPTANCE H1 — do not try to trade when the market is closed."""
from __future__ import annotations

import datetime as dt

from trading_agent.market import is_market_open

ET = dt.timezone(dt.timedelta(hours=-4))  # EDT; September is daylight time


def at(y, m, d, hh, mm=0):
    return dt.datetime(y, m, d, hh, mm, tzinfo=ET)


def test_open_midday_on_a_weekday():
    assert is_market_open(at(2026, 9, 11, 12, 0))


def test_closed_before_the_bell():
    assert not is_market_open(at(2026, 9, 11, 9, 0))


def test_closed_after_the_bell():
    assert not is_market_open(at(2026, 9, 11, 16, 30))


def test_boundaries():
    assert is_market_open(at(2026, 9, 11, 9, 30)), "open at 09:30 exactly"
    assert not is_market_open(at(2026, 9, 11, 16, 0)), "closed at 16:00 exactly"


def test_closed_at_weekends():
    assert not is_market_open(at(2026, 9, 12, 12, 0))  # Saturday
    assert not is_market_open(at(2026, 9, 13, 12, 0))  # Sunday


def test_closed_on_a_holiday():
    # Christmas Day 2026 is a Friday, so the weekday check alone would pass it.
    assert not is_market_open(at(2026, 12, 25, 12, 0))


def test_utc_input_is_converted_not_assumed():
    """The loop works in UTC; the market does not."""
    utc_1430 = dt.datetime(2026, 9, 11, 14, 30, tzinfo=dt.timezone.utc)  # 10:30 ET
    assert is_market_open(utc_1430)
    utc_0200 = dt.datetime(2026, 9, 11, 2, 0, tzinfo=dt.timezone.utc)  # 22:00 ET prev
    assert not is_market_open(utc_0200)


def test_naive_datetime_is_rejected():
    """Guessing a timezone here would mean trading at the wrong hour."""
    import pytest

    with pytest.raises(ValueError):
        is_market_open(dt.datetime(2026, 9, 11, 12, 0))
