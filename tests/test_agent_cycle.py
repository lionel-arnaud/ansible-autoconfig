"""The cycle's ordering guarantees — each stage can only narrow what reaches
the broker, and any failure stops rather than falling through to a default."""
from __future__ import annotations

import datetime as dt

from trading_agent.agent import run_cycle
from trading_agent.audit import AuditLog
from trading_agent.broker import Broker
from trading_agent.config import Config
from trading_agent.reasoning import ReasoningClient
from trading_agent.state import State

OPEN = dt.datetime(2026, 9, 11, 14, 30, tzinfo=dt.timezone.utc)   # 10:30 ET
CLOSED = dt.datetime(2026, 9, 12, 14, 30, tzinfo=dt.timezone.utc)  # Saturday


class Feed:
    def upcoming_trials(self, **k):
        return []

    def recent_news(self, **k):
        return []


def mk(tmp_path, proposals_json):
    return dict(
        state=State(tmp_path / "s.db"),
        config=Config.for_testing(),
        broker=Broker.for_testing(),
        feed=Feed(),
        reasoner=ReasoningClient(transport=lambda _p: proposals_json),
        audit=AuditLog(tmp_path / "a.log"),
    )


BUY = '{"proposals":[{"symbol":"MRNA","side":"buy","notional_usd":100,"rationale":"r"}]}'


def test_a_clean_cycle_submits(tmp_path):
    r = run_cycle(**mk(tmp_path, BUY), now=OPEN)
    assert r.ran and r.submitted == 1


def test_market_closed_does_nothing(tmp_path):
    r = run_cycle(**mk(tmp_path, BUY), now=CLOSED)
    assert not r.ran and r.submitted == 0 and "closed" in r.skipped_reason


def test_kill_switch_stops_the_cycle_before_any_work(tmp_path):
    kw = mk(tmp_path, BUY)
    kw["state"].set_kill_switch(True)
    r = run_cycle(**kw, now=OPEN)
    assert not r.ran and r.submitted == 0 and "kill switch" in r.skipped_reason


def test_unreachable_reasoning_opens_nothing(tmp_path):
    kw = mk(tmp_path, BUY)
    kw["reasoner"] = ReasoningClient(transport=lambda _p: (_ for _ in ()).throw(OSError("down")))
    r = run_cycle(**kw, now=OPEN)
    assert r.submitted == 0 and "reasoning unavailable" in r.skipped_reason


def test_a_proposal_over_the_limit_is_rejected_not_clamped(tmp_path):
    """Silently shrinking an oversized order would hide a misbehaving model."""
    big = '{"proposals":[{"symbol":"MRNA","side":"buy","notional_usd":10000,"rationale":"r"}]}'
    r = run_cycle(**mk(tmp_path, big), now=OPEN)
    assert r.submitted == 0 and any("max_position" in x for x in r.rejected)


def test_the_full_chain_is_auditable_from_the_order_id(tmp_path):
    kw = mk(tmp_path, BUY)
    r = run_cycle(**kw, now=OPEN)
    chain = kw["audit"].chain_for_order(r.orders[0])
    assert [e["event"] for e in chain][-3:] == ["proposal", "guardrail", "order"]


def test_daily_trade_budget_is_spent_only_on_accepted_orders(tmp_path):
    kw = mk(tmp_path, BUY)
    run_cycle(**kw, now=OPEN)
    assert kw["state"].trades_today(OPEN) == 1


# --- O-07: a stored view gates every opening trade ---------------------------

def test_no_view_means_no_opening_trade(tmp_path):
    """The operator's judgment is the alpha source. Without it the agent does
    nothing — correct behaviour, not a fault."""
    from trading_agent.views import ViewStore

    kw = mk(tmp_path, BUY)
    kw["views"] = ViewStore(tmp_path / "v.db")
    r = run_cycle(**kw, now=OPEN)
    assert r.submitted == 0
    assert any("no view" in x for x in r.rejected)


def test_a_positive_view_permits_the_trade(tmp_path):
    import datetime as dt
    from trading_agent.views import View, ViewStore

    kw = mk(tmp_path, BUY)
    vs = ViewStore(tmp_path / "v.db")
    vs.record(View("MRNA", "MRNA", "positive", 4, "phase 3 looks strong", OPEN))
    kw["views"] = vs
    r = run_cycle(**kw, now=OPEN)
    assert r.submitted == 1


def test_no_opinion_blocks_the_trade(tmp_path):
    """Explicitly declining to judge must not read as consent."""
    from trading_agent.views import View, ViewStore

    kw = mk(tmp_path, BUY)
    vs = ViewStore(tmp_path / "v.db")
    vs.record(View("MRNA", "MRNA", "no_opinion", 0, "outside my area", OPEN))
    kw["views"] = vs
    r = run_cycle(**kw, now=OPEN)
    assert r.submitted == 0
    assert any("no view" in x or "no_opinion" in x for x in r.rejected)


def test_closing_a_position_needs_no_view(tmp_path):
    """Getting out is risk reduction and must not wait on anyone."""
    from trading_agent.views import ViewStore

    sell = '{"proposals":[{"symbol":"MRNA","side":"sell","notional_usd":100,"rationale":"exit"}]}'
    kw = mk(tmp_path, sell)
    kw["views"] = ViewStore(tmp_path / "v.db")
    r = run_cycle(**kw, now=OPEN)
    assert r.submitted == 1, "a sell must not be gated on a view"


# --- ACCEPTANCE C1, C3 — the approval gate inside a real cycle --------------

GATED = ('{"proposals":[{"symbol":"MRNA","side":"buy","notional_usd":300,'
         '"rationale":"phase 3 readout"}]}')


def _gated(tmp_path):
    kw = mk(tmp_path, GATED)
    kw["config"] = Config.for_testing(approval_threshold_usd=250.0,
                                      max_position_usd=1000.0,
                                      max_deployed_usd=1000.0)
    return kw


def test_c1_a_gated_order_is_asked_about_and_not_submitted(tmp_path):
    kw = _gated(tmp_path)
    asked = []
    r = run_cycle(**kw, ask=lambda key, payload: asked.append((key, payload)),
                  now=OPEN)
    assert r.submitted == 0
    assert any("approval_required" in x for x in r.rejected)
    assert len(asked) == 1
    assert asked[0][1]["notional_usd"] == 300
    assert kw["state"].pending_approvals()


def test_c1_the_question_is_asked_once_not_every_cycle(tmp_path):
    kw = _gated(tmp_path)
    asked = []
    for _ in range(3):
        run_cycle(**kw, ask=lambda key, payload: asked.append(key), now=OPEN)
    assert len(asked) == 1


def test_c1_a_granted_approval_lets_the_next_cycle_submit(tmp_path):
    kw = _gated(tmp_path)
    keys = []
    run_cycle(**kw, ask=lambda key, _p: keys.append(key), now=OPEN)
    kw["state"].set_approval(keys[0], "granted")

    r = run_cycle(**kw, now=OPEN)
    assert r.submitted == 1, r.rejected


def test_c3_silence_past_the_deadline_denies_rather_than_submits(tmp_path):
    kw = _gated(tmp_path)
    kw["config"] = Config.for_testing(approval_threshold_usd=250.0,
                                      max_position_usd=1000.0,
                                      max_deployed_usd=1000.0,
                                      approval_ttl_seconds=3600.0)
    run_cycle(**kw, ask=lambda *_: None, now=OPEN)

    later = OPEN + dt.timedelta(hours=2)
    r = run_cycle(**kw, now=later)
    assert r.submitted == 0
    assert any("denied" in x for x in r.rejected), r.rejected
    assert not kw["state"].pending_approvals()


def test_c1_a_failing_notification_does_not_open_the_gate(tmp_path):
    """If Telegram is down the operator never sees the question — which must
    mean the order waits, not that it goes through unasked."""
    kw = _gated(tmp_path)

    def boom(_key, _payload):
        raise OSError("telegram down")

    r = run_cycle(**kw, ask=boom, now=OPEN)
    assert r.submitted == 0
