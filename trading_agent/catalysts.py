"""Catalyst discovery — clinical trial readouts and company news.

The operator's edge is judging whether a trial will read out well. This module
does not attempt that judgment; it finds dated, upcoming, binary events and
presents enough context for a human who knows the field to form a view.

Read-only and non-fatal by construction: a failure here returns nothing and the
loop simply has no new catalysts this cycle. A data-source outage must never
take the agent down or, worse, produce half a picture it then trades on.
"""
from __future__ import annotations

import datetime as dt
import time
from dataclasses import dataclass

from trading_agent.sources import RateLimited

CTGOV_API = "https://clinicaltrials.gov/api/v2/studies"


@dataclass(frozen=True)
class Catalyst:
    symbol: str
    title: str
    date: str
    source: str
    url: str = ""
    phase: str = ""

    def summary(self) -> str:
        bits = [self.symbol, self.phase, self.title]
        return " | ".join(b for b in bits if b)


# One request per symbol per sweep, and the universe is the holdings of two
# ETFs. At a fifteen-minute cycle that would be hundreds of requests an hour to
# a public government API for data that changes daily at most. Six hours is
# still four sweeps a day, which is more than a trial registry ever needs.
TRIALS_TTL_SECONDS = 6 * 3600
# Spacing between registry requests. ClinicalTrials.gov answered 429 to an
# unspaced sweep of 149 symbols, and still throttled at a third of a second.
# A full sweep now takes about two and a half minutes, four times a day.
REQUEST_DELAY_SECONDS = 1.0
# A sweep that was cut short is retried soon rather than held for the full
# window: caching a partial picture for six hours is worse than not caching.
DEGRADED_TTL_SECONDS = 600
# How many symbols in a row may exhaust their retries before the sweep gives
# up. One is too few — a single throttled symbol is normal — and continuing
# indefinitely into a wall of 429s is how an address gets blocked.
MAX_CONSECUTIVE_RATE_LIMITS = 3
# Retries for one symbol, each after a longer pause.
RATE_LIMIT_RETRIES = 2


class CatalystFeed:
    def __init__(self, universe, *, http=None, news=None,
                 trials_ttl_seconds: float = TRIALS_TTL_SECONDS,
                 request_delay: float = REQUEST_DELAY_SECONDS,
                 clock=None, sleep=None) -> None:
        self._universe = universe
        self._http = http
        self._news = news
        self._ttl = trials_ttl_seconds
        self._clock = clock or time.monotonic
        self._delay = request_delay
        self._sleep = sleep or time.sleep
        self._trials_cache: list[Catalyst] = []
        self._trials_at: float | None = None
        self._ttl_now = trials_ttl_seconds

    def upcoming_trials(self, *, within_days: int = 30) -> list[Catalyst]:
        """Late-phase trials with a completion date inside the window.

        Phase 2/3 only: early-phase results rarely move a stock the way a
        pivotal readout does, and the whole premise here is binary events.

        Cached: a registry entry does not change between two cycles fifteen
        minutes apart, and sweeping it every cycle would be rude to a public
        API for no new information.
        """
        if self._http is None:
            return []
        now = self._clock()
        if self._trials_at is not None and now - self._trials_at < self._ttl_now:
            return list(self._trials_cache)
        cutoff = dt.date.today() + dt.timedelta(days=within_days)
        out: list[Catalyst] = []
        degraded = False
        throttled_in_a_row = 0
        for symbol in sorted(self._universe.symbols()):
            try:
                studies = self._fetch_studies(symbol)
            except RateLimited:
                throttled_in_a_row += 1
                if throttled_in_a_row >= MAX_CONSECUTIVE_RATE_LIMITS:
                    # Hammering past a rate limit gets the address blocked, and
                    # the rest of the sweep would return nothing anyway.
                    degraded = True
                    break
                continue
            except Exception:  # noqa: BLE001 — one bad symbol must not end the sweep
                continue
            throttled_in_a_row = 0
            for study in studies or []:
                try:
                    c = _parse_study(symbol, study)
                except Exception:  # noqa: BLE001
                    continue
                if c and c.date and c.date <= cutoff.isoformat():
                    out.append(c)
        if degraded:
            # Merge rather than replace. A sweep that stopped at the letter B
            # knows nothing about the rest of the universe — it is not evidence
            # that those trials went away, and letting it overwrite the cache
            # dropped the agent from 76 catalysts to 6.
            known = {(c.symbol, c.url): c for c in self._trials_cache}
            known.update({(c.symbol, c.url): c for c in out})
            out = list(known.values())
        self._trials_cache = out
        self._trials_at = now
        self._ttl_now = DEGRADED_TTL_SECONDS if degraded else self._ttl
        return list(out)

    def _fetch_studies(self, symbol: str) -> list:
        """One symbol, spaced, with a single backoff on a rate limit."""
        # By sponsor, not by free text. "query.term=ACAD" returned trials
        # containing "Academy" and "Acute" — the agent asked the operator to
        # judge an obesity study run by a company it cannot trade.
        sponsor = self._universe.company_name(symbol)
        if not sponsor:
            return []
        params = {
            "query.spons": sponsor,
            "filter.overallStatus": "RECRUITING,ACTIVE_NOT_RECRUITING",
            "pageSize": 5,
        }
        pause = self._delay
        for attempt in range(RATE_LIMIT_RETRIES + 1):
            try:
                studies = self._http(CTGOV_API, params)
            except RateLimited:
                if attempt == RATE_LIMIT_RETRIES:
                    raise
                pause *= 4
                self._sleep(pause)
                continue
            self._sleep(self._delay)
            return studies
        raise AssertionError("unreachable")

    def recent_news(self, *, limit: int = 20) -> list[Catalyst]:
        if self._news is None:
            return []
        try:
            items = self._news(sorted(self._universe.symbols()), limit)
        except Exception:  # noqa: BLE001 — degrade to no news, never raise
            return []
        return [
            Catalyst(
                symbol=(i.get("symbol") or "").upper(),
                title=i.get("headline", ""),
                date=i.get("created_at", ""),
                source="alpaca-news",
                url=i.get("url", ""),
            )
            for i in items or []
        ]


def _parse_study(symbol: str, study: dict) -> Catalyst | None:
    protocol = study.get("protocolSection", {})
    ident = protocol.get("identificationModule", {})
    design = protocol.get("designModule", {})
    status = protocol.get("statusModule", {})
    phases = design.get("phases", []) or []
    if not any(p in ("PHASE2", "PHASE3") for p in phases):
        return None
    completion = (status.get("primaryCompletionDateStruct", {}) or {}).get("date", "")
    return Catalyst(
        symbol=symbol,
        title=ident.get("briefTitle", ""),
        date=completion,
        source="clinicaltrials.gov",
        url=f"https://clinicaltrials.gov/study/{ident.get('nctId','')}",
        phase="/".join(phases),
    )
