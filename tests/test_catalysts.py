"""Catalyst discovery must degrade, never raise into the loop."""
from __future__ import annotations

from trading_agent.catalysts import CatalystFeed, _parse_study
from trading_agent.sources import RateLimited
from trading_agent.universe import Universe


def _no_sleep(_seconds):
    """The sweep spaces its requests; tests must not pay for that."""


class U:
    def symbols(self):
        return {"MRNA"}


def test_no_transport_configured_yields_nothing():
    feed = CatalystFeed(U())
    assert feed.upcoming_trials() == []
    assert feed.recent_news() == []


def test_a_failing_source_degrades_to_empty(tmp_path):
    def boom(*a, **k):
        raise OSError("ctgov down")

    feed = CatalystFeed(U(), http=boom, news=boom, sleep=_no_sleep)
    assert feed.upcoming_trials() == []
    assert feed.recent_news() == []


def test_only_late_phase_trials_count():
    early = {"protocolSection": {
        "identificationModule": {"briefTitle": "t", "nctId": "NCT1"},
        "designModule": {"phases": ["PHASE1"]},
        "statusModule": {"primaryCompletionDateStruct": {"date": "2026-10-01"}}}}
    assert _parse_study("MRNA", early) is None

    pivotal = {"protocolSection": {
        "identificationModule": {"briefTitle": "t", "nctId": "NCT2"},
        "designModule": {"phases": ["PHASE3"]},
        "statusModule": {"primaryCompletionDateStruct": {"date": "2026-10-01"}}}}
    c = _parse_study("MRNA", pivotal)
    assert c and c.symbol == "MRNA" and "NCT2" in c.url


def test_a_malformed_study_is_skipped_not_fatal():
    assert _parse_study("MRNA", {"unexpected": True}) is None


# --- the registry is swept on a timer, not every cycle -----------------------

class _Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _counting_http(counter):
    def http(url, params):
        counter.append(params.get("query.term"))
        return []
    return http


class _Uni:
    def symbols(self):
        return {"MRNA", "BNTX", "VRTX"}

    def company_name(self, symbol):
        # The registry is searched by sponsor, so the sweep needs a name.
        return {"MRNA": "ModernaTX", "BNTX": "BioNTech",
                "VRTX": "Vertex Pharmaceuticals"}[symbol]


def test_trials_are_not_re_swept_every_cycle():
    calls, clock = [], _Clock()
    feed = CatalystFeed(_Uni(), http=_counting_http(calls), clock=clock,
                        sleep=_no_sleep)

    feed.upcoming_trials()
    first = len(calls)
    assert first == 3, "one request per symbol on a real sweep"

    for _ in range(10):
        feed.upcoming_trials()
    assert len(calls) == first, "a cached sweep must make no requests"


def test_the_sweep_runs_again_once_the_window_passes():
    calls, clock = [], _Clock()
    feed = CatalystFeed(_Uni(), http=_counting_http(calls),
                        trials_ttl_seconds=3600, clock=clock, sleep=_no_sleep)
    feed.upcoming_trials()
    clock.t += 3601
    feed.upcoming_trials()
    assert len(calls) == 6


# --- the registry rate-limits an unspaced sweep ------------------------------

def test_requests_are_spaced_so_the_registry_does_not_rate_limit_us():
    """A 149-symbol sweep with no spacing came back 429 for most of it, and the
    agent reasoned over a partial picture without knowing it was partial."""
    slept = []
    feed = CatalystFeed(_Uni(), http=lambda u, p: [], clock=_Clock(),
                        sleep=slept.append)
    feed.upcoming_trials()
    assert len(slept) == 3 and all(s > 0 for s in slept)


def test_a_rate_limit_is_retried_once_before_giving_up():
    calls = []

    def http(url, params):
        calls.append(params["query.spons"])
        if len(calls) == 1:
            raise RateLimited(url)
        return []

    feed = CatalystFeed(_Uni(), http=http, clock=_Clock(), sleep=lambda _s: None)
    feed.upcoming_trials()
    assert calls[:2] == [calls[0], calls[0]], "the same symbol is retried"
    assert len(calls) == 4, "and the sweep continues through the universe"


def test_a_persistent_rate_limit_stops_the_sweep_and_shortens_the_cache():
    """Hammering past a rate limit gets the address blocked, and a partial
    sweep must not be held for the full six hours."""
    def http(url, params):
        raise RateLimited(url)

    clock = _Clock()
    calls = []
    feed = CatalystFeed(_Uni(), http=http, clock=clock, sleep=calls.append)
    feed.upcoming_trials()
    assert feed._ttl_now < feed._ttl

    # And it tries again well before the normal window.
    clock.t += feed._ttl_now + 1
    before = len(calls)
    feed.upcoming_trials()
    assert len(calls) > before


def test_a_cut_short_sweep_does_not_erase_what_was_already_known():
    """A sweep that stopped at the letter B knows nothing about the rest of the
    universe. It is not evidence those trials went away — letting it overwrite
    the cache dropped the live agent from 76 catalysts to 6."""
    state = {"limit": False}

    def http(url, params):
        if state["limit"]:
            raise RateLimited(url)
        return [{
            "protocolSection": {
                "identificationModule": {"briefTitle": "T", "nctId": "NCT1"},
                "designModule": {"phases": ["PHASE3"]},
                "statusModule": {
                    "primaryCompletionDateStruct": {"date": "2026-09-20"}},
            }
        }]

    clock = _Clock()
    feed = CatalystFeed(_Uni(), http=http, clock=clock, sleep=lambda _s: None)
    full = feed.upcoming_trials()
    assert len(full) == 3

    state["limit"] = True
    clock.t += feed._ttl + 1
    after = feed.upcoming_trials()
    assert len(after) == 3, "the known catalysts survive a throttled sweep"


def test_one_throttled_symbol_does_not_end_the_sweep():
    """A single 429 is normal. Giving up on it would make a full sweep depend
    on every one of 147 requests succeeding."""
    calls = []

    def http(url, params):
        calls.append(params["query.spons"])
        # Every attempt for the first symbol is throttled; the rest are fine.
        if params["query.spons"] == "BioNTech":
            raise RateLimited(url)
        return []

    feed = CatalystFeed(_Uni(), http=http, clock=_Clock(), sleep=lambda _s: None)
    feed.upcoming_trials()
    assert "ModernaTX" in calls and "Vertex Pharmaceuticals" in calls
