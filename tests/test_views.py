"""Operator views — the predictions that gate trading, and get scored later.

A view is a judgment recorded BEFORE an outcome is known. That ordering is what
makes it both a trading signal and, afterwards, a measurable prediction.
"""
from __future__ import annotations

import datetime as dt

from trading_agent.views import View, ViewStore

NOW = dt.datetime(2026, 9, 11, 12, 0, tzinfo=dt.timezone.utc)
LATER = NOW + dt.timedelta(days=10)


def store(tmp_path):
    return ViewStore(tmp_path / "v.db")


def test_a_view_is_recorded_and_retrieved(tmp_path):
    s = store(tmp_path)
    s.record(View("MRNA", "NCT123", "positive", 4, "strong phase 2", NOW))
    v = s.for_event("MRNA", "NCT123", now=NOW)
    assert v and v.stance == "positive" and v.confidence == 4


def test_no_view_means_no_view_not_a_default(tmp_path):
    """Absence must never be read as neutral-and-tradable."""
    assert store(tmp_path).for_event("MRNA", "NCT999", now=NOW) is None


def test_no_opinion_is_a_real_answer_and_blocks_trading(tmp_path):
    """Saying 'I don't know' is information, and must not be mistaken for
    not having been asked."""
    s = store(tmp_path)
    s.record(View("MRNA", "NCT123", "no_opinion", 0, "outside my area", NOW))
    v = s.for_event("MRNA", "NCT123", now=NOW)
    assert v is not None and not v.is_actionable


def test_a_view_expires_and_stops_being_actionable(tmp_path):
    """A read on a readout is about that readout. It must not silently license
    a trade months later."""
    s = store(tmp_path)
    s.record(View("MRNA", "NCT123", "positive", 4, "r", NOW, expires_at=NOW + dt.timedelta(days=5)))
    assert s.for_event("MRNA", "NCT123", now=NOW) is not None
    assert s.for_event("MRNA", "NCT123", now=LATER) is None


def test_a_newer_view_supersedes_an_older_one(tmp_path):
    s = store(tmp_path)
    s.record(View("MRNA", "NCT123", "positive", 4, "first", NOW))
    s.record(View("MRNA", "NCT123", "negative", 5, "changed my mind", NOW + dt.timedelta(hours=1)))
    assert s.for_event("MRNA", "NCT123", now=NOW + dt.timedelta(hours=2)).stance == "negative"


def test_outcomes_are_recorded_against_the_original_view(tmp_path):
    s = store(tmp_path)
    s.record(View("MRNA", "NCT123", "positive", 4, "r", NOW))
    s.record_outcome("MRNA", "NCT123", "positive", LATER)
    scored = s.scored()
    assert len(scored) == 1 and scored[0]["correct"] is True


def test_scoreboard_separates_hits_from_misses(tmp_path):
    s = store(tmp_path)
    for i, (stance, outcome) in enumerate(
        [("positive", "positive"), ("positive", "negative"), ("negative", "negative")]
    ):
        s.record(View("S%d" % i, "N%d" % i, stance, 3, "r", NOW))
        s.record_outcome("S%d" % i, "N%d" % i, outcome, LATER)
    board = s.scoreboard()
    assert board["scored"] == 3 and board["correct"] == 2


def test_no_opinion_views_are_excluded_from_scoring(tmp_path):
    """Scoring 'I don't know' as wrong would punish honesty and make the
    scoreboard useless as a learning signal."""
    s = store(tmp_path)
    s.record(View("MRNA", "NCT1", "no_opinion", 0, "r", NOW))
    s.record_outcome("MRNA", "NCT1", "positive", LATER)
    assert s.scoreboard()["scored"] == 0


# --- accuracy is meaningless without a base rate -----------------------------

def test_edge_is_measured_against_a_base_rate(tmp_path):
    """Being right 55% of the time is only an edge if chance is 50%."""
    s = store(tmp_path)
    for i in range(10):
        s.record(View(f"S{i}", f"N{i}", "positive", 3, "r", NOW))
        s.record_outcome(f"S{i}", f"N{i}", "positive" if i < 6 else "negative", LATER)
    board = s.scoreboard(base_rate=0.5)
    assert board["accuracy"] == 0.6
    assert abs(board["edge_over_base"] - 0.1) < 1e-9


def test_a_small_sample_is_flagged_as_not_significant(tmp_path):
    """Ten lucky calls are not an edge, and must not be presented as one."""
    s = store(tmp_path)
    for i in range(10):
        s.record(View(f"S{i}", f"N{i}", "positive", 3, "r", NOW))
        s.record_outcome(f"S{i}", f"N{i}", "positive", LATER)
    assert s.scoreboard()["significant"] is False


def test_phase_base_rates_differ(tmp_path):
    """Phase 2 is far harder than phase 3; scoring them alike would flatter
    the wrong calls."""
    s = store(tmp_path)
    assert s.BASE_RATES["PHASE2"] < s.BASE_RATES["PHASE3"]


def test_empty_scoreboard_reports_nothing_rather_than_zero(tmp_path):
    """No data is not the same as no skill."""
    board = store(tmp_path).scoreboard()
    assert board["accuracy"] is None and board["edge_over_base"] is None


def test_financial_outcomes_are_recorded_but_not_scored(tmp_path):
    """Surfaced and remembered, deliberately ungraded — the scoreboard is
    supposed to measure biotech judgment, not quarterly numbers."""
    s = store(tmp_path)
    s.record(View("MRNA", "MRNA", "positive", 3, "beat expected", NOW))
    s.record_outcome("MRNA", "MRNA", "positive", LATER, scoreable=False)
    assert s.scoreboard()["scored"] == 0


def test_a_view_on_a_trial_covers_its_later_events(tmp_path):
    """One read on NCT123 answers for its interim analysis and its readout —
    cheaper, and closer to how the judgment actually works."""
    s = store(tmp_path)
    s.record(View("MRNA", "NCT123", "positive", 4, "strong mechanism", NOW))
    assert s.for_event("MRNA", "NCT123", now=NOW + dt.timedelta(days=3)) is not None
