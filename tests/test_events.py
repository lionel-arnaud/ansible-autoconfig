"""Materiality and scoreability are separate judgments."""
from __future__ import annotations

from trading_agent.events import Event, EventKind, Materiality, worth_researching


def ev(kind, trial_id=""):
    return Event(symbol="MRNA", kind=kind, title="t", trial_id=trial_id)


def test_earnings_are_not_scored():
    """Quarterly numbers are not the operator's edge; scoring them would
    dilute the one number meant to measure biotech judgment."""
    assert not ev(EventKind.EARNINGS).is_scoreable


def test_trial_events_are_scored():
    for k in (EventKind.TRIAL_READOUT, EventKind.TRIAL_AMENDMENT,
              EventKind.INTERIM_ANALYSIS, EventKind.REGULATORY):
        assert ev(k).is_scoreable


def test_earnings_are_still_surfaced_just_not_researched():
    """Material enough to mention, not worth spending tokens on."""
    e = ev(EventKind.EARNINGS)
    assert e.materiality == Materiality.LOW
    assert not worth_researching(e, has_view=False)


def test_a_held_view_suppresses_further_research():
    """The cheapest token saving there is: a view is the answer research was
    trying to produce."""
    e = ev(EventKind.INTERIM_ANALYSIS)
    assert worth_researching(e, has_view=False)
    assert not worth_researching(e, has_view=True)


def test_only_genuinely_new_information_overrides_an_existing_view():
    """Superseded by the materiality/invalidation split. This originally also
    asserted that a TRIAL_READOUT re-opens a judged trial, which was wrong:
    a scheduled readout is what the view was formed about, so re-asking is
    noise. Only an amendment or a regulatory action is new."""
    assert worth_researching(ev(EventKind.TRIAL_AMENDMENT), has_view=True)
    assert not worth_researching(ev(EventKind.TRIAL_READOUT), has_view=True)


def test_views_are_keyed_on_the_trial_not_the_item():
    """One read on a trial should carry across its interim analysis, its
    amendments and its final readout."""
    readout = Event("MRNA", EventKind.TRIAL_READOUT, "t", trial_id="NCT123")
    interim = Event("MRNA", EventKind.INTERIM_ANALYSIS, "t2", trial_id="NCT123")
    assert readout.view_key == interim.view_key == "NCT123"


def test_company_level_events_fall_back_to_the_symbol():
    assert ev(EventKind.EARNINGS).view_key == "MRNA"


def test_an_anticipated_readout_is_not_re_asked_once_judged():
    """A scheduled readout is exactly what the existing view was formed about.
    Asking again is noise, not diligence."""
    e = ev(EventKind.TRIAL_READOUT)
    assert not e.invalidates_prior_view
    assert not worth_researching(e, has_view=True)
    assert worth_researching(e, has_view=False)


def test_new_information_does_re_open_a_judged_trial():
    """An amendment or a regulatory action is genuinely new, so the earlier
    read deserves a second look."""
    for kind in (EventKind.TRIAL_AMENDMENT, EventKind.REGULATORY):
        assert ev(kind).invalidates_prior_view
        assert worth_researching(ev(kind), has_view=True)
