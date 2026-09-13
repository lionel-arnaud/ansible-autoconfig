"""Market hours.

Kept deliberately simple and local rather than asking the broker: this is
consulted on every loop iteration, it must work when the network does not, and
"is it 10am in New York" does not need an API call.

US equities regular session only — no pre/post market, matching the v1 decision
to stay long-only in regular hours.
"""
from __future__ import annotations

import datetime as dt

_NY = dt.timezone(dt.timedelta(hours=-5))  # EST; the -4 offset applies in DST

OPEN = dt.time(9, 30)
CLOSE = dt.time(16, 0)

# Full-day NYSE closures. Half-days (early closes) are deliberately treated as
# full trading days: the cost of that is a few late-afternoon attempts the
# broker rejects, whereas mis-treating a trading day as a holiday costs a
# missed catalyst, which is the expensive direction.
_HOLIDAYS_2026 = {
    dt.date(2026, 1, 1), dt.date(2026, 1, 19), dt.date(2026, 2, 16),
    dt.date(2026, 4, 3), dt.date(2026, 5, 25), dt.date(2026, 6, 19),
    dt.date(2026, 7, 3), dt.date(2026, 9, 7), dt.date(2026, 11, 26),
    dt.date(2026, 12, 25),
}


def _to_market_time(now: dt.datetime) -> dt.datetime:
    if now.tzinfo is None:
        # Refusing beats guessing: assuming the wrong zone here means trading at
        # the wrong hour, silently.
        raise ValueError("is_market_open() requires a timezone-aware datetime")
    # Second Sunday in March to first Sunday in November, approximated by month
    # boundaries. Off by at most a few days a year, and only ever by one hour,
    # which cannot move a midday check across the open or the close.
    offset = -4 if 3 <= now.month <= 11 else -5
    return now.astimezone(dt.timezone(dt.timedelta(hours=offset)))


def is_market_open(now: dt.datetime) -> bool:
    local = _to_market_time(now)
    if local.weekday() >= 5:
        return False
    if local.date() in _HOLIDAYS_2026:
        return False
    return OPEN <= local.time() < CLOSE
