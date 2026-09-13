"""ACCEPTANCE B1, C2, C3 — safety state must survive a restart."""
from __future__ import annotations

import datetime as dt

import pytest

from trading_agent.state import State

NOW = dt.datetime(2026, 9, 11, 15, 0, tzinfo=dt.timezone.utc)


def test_b1_kill_switch_survives_restart(tmp_path):
    path = tmp_path / "s.db"
    State(path).set_kill_switch(True)
    assert State(path).kill_switch_engaged() is True, "must be on disk, not in memory"


def test_b3_only_explicit_resume_clears_it(tmp_path):
    path = tmp_path / "s.db"
    s = State(path)
    s.set_kill_switch(True)
    assert s.kill_switch_engaged()
    s.set_kill_switch(False)
    assert not s.kill_switch_engaged()


def test_c2_pending_approval_survives_restart(tmp_path):
    path = tmp_path / "s.db"
    State(path).add_pending_approval("req1", {"symbol": "XBI"})
    assert "req1" in State(path).pending_approvals()


def test_trade_counter_is_per_day(tmp_path):
    s = State(tmp_path / "s.db")
    s.record_trade(NOW)
    s.record_trade(NOW)
    assert s.trades_today(NOW) == 2
    assert s.trades_today(NOW + dt.timedelta(days=1)) == 0


def test_c3_pending_approval_expires_to_denied_never_approved(tmp_path):
    now = dt.datetime(2026, 9, 11, 12, 0, tzinfo=dt.timezone.utc)
    state = State(tmp_path / "s.db")
    state.add_pending_approval("req1", {"symbol": "XBI"}, now)

    # Inside the window nothing moves: expiry is a deadline, not a poller.
    assert state.expire_approvals(now + dt.timedelta(minutes=59), 3600) == []
    assert state.approval_status("req1") == "pending"

    assert state.expire_approvals(now + dt.timedelta(minutes=61), 3600) == ["req1"]
    assert state.approval_status("req1") == "denied"
    assert "req1" not in state.pending_approvals()


def test_c3_answer_after_expiry_cannot_resurrect_the_request(tmp_path):
    now = dt.datetime(2026, 9, 11, 12, 0, tzinfo=dt.timezone.utc)
    state = State(tmp_path / "s.db")
    state.add_pending_approval("req1", {}, now)
    state.expire_approvals(now + dt.timedelta(hours=2), 3600)

    state.set_approval("req1", "granted")  # the operator's late "yes"
    assert state.approval_status("req1") == "denied"


def test_c3_expiry_survives_restart(tmp_path):
    path = tmp_path / "s.db"
    now = dt.datetime(2026, 9, 11, 12, 0, tzinfo=dt.timezone.utc)
    State(path).add_pending_approval("req1", {}, now)
    State(path).expire_approvals(now + dt.timedelta(hours=2), 3600)
    assert State(path).approval_status("req1") == "denied"


def test_approval_status_is_none_when_never_requested(tmp_path):
    assert State(tmp_path / "s.db").approval_status("nope") is None


def test_set_approval_rejects_a_status_that_is_not_an_outcome(tmp_path):
    state = State(tmp_path / "s.db")
    state.add_pending_approval("req1", {})
    with pytest.raises(ValueError):
        state.set_approval("req1", "pending")


def test_a_second_handle_opens_while_the_first_holds_the_database(tmp_path):
    """The command loop and the work loop each hold their own handle, and a
    restart opens a third while the dying process still has the file. This
    raised "database is locked" on the Pi and crash-looped the unit."""
    path = tmp_path / "s.db"
    first = State(path)
    first.set_kill_switch(True)

    second = State(path)  # must not raise
    assert second.kill_switch_engaged()
    assert second._db.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
