"""Trial amendments — the signal is what changed, not what it says now."""
from __future__ import annotations

import datetime as dt

from trading_agent.trial_watch import TrialWatcher, extract_fields

NOW = dt.datetime(2026, 9, 11, tzinfo=dt.timezone.utc)


def study(*, endpoint="OS at 24 months", status="RECRUITING", enrol=500,
          completion="2026-12-01", phases=("PHASE3",)):
    return {"protocolSection": {
        "statusModule": {"overallStatus": status,
                         "primaryCompletionDateStruct": {"date": completion}},
        "designModule": {"enrollmentInfo": {"count": enrol}, "phases": list(phases)},
        "outcomesModule": {"primaryOutcomes": [{"measure": endpoint}]}}}


def test_first_sighting_reports_nothing(tmp_path):
    """Every field would look changed against no prior snapshot — that is noise."""
    w = TrialWatcher(tmp_path / "t.db")
    assert w.observe("NCT1", study(), now=NOW) == []


def test_an_unchanged_trial_reports_nothing(tmp_path):
    w = TrialWatcher(tmp_path / "t.db")
    w.observe("NCT1", study(), now=NOW)
    assert w.observe("NCT1", study(), now=NOW) == []


def test_a_changed_primary_endpoint_is_high_severity(tmp_path):
    """The loudest signal available: changing what you measure, late."""
    w = TrialWatcher(tmp_path / "t.db")
    w.observe("NCT1", study(), now=NOW)
    out = w.observe("NCT1", study(endpoint="PFS at 12 months"), now=NOW)
    assert len(out) == 1
    assert out[0].field == "primary_outcomes" and out[0].severity == "high"


def test_a_slipping_completion_date_is_caught(tmp_path):
    w = TrialWatcher(tmp_path / "t.db")
    w.observe("NCT1", study(), now=NOW)
    out = w.observe("NCT1", study(completion="2027-06-01"), now=NOW)
    assert [a.field for a in out] == ["primary_completion_date"]


def test_termination_is_caught(tmp_path):
    w = TrialWatcher(tmp_path / "t.db")
    w.observe("NCT1", study(), now=NOW)
    out = w.observe("NCT1", study(status="TERMINATED"), now=NOW)
    assert out[0].field == "overall_status" and out[0].severity == "high"


def test_several_simultaneous_changes_are_all_reported(tmp_path):
    w = TrialWatcher(tmp_path / "t.db")
    w.observe("NCT1", study(), now=NOW)
    out = w.observe("NCT1", study(endpoint="PFS", enrol=200), now=NOW)
    assert {a.field for a in out} == {"primary_outcomes", "enrollment"}


def test_a_malformed_record_does_not_explode(tmp_path):
    assert extract_fields({})["primary_outcomes"] == []
