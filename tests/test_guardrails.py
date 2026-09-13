"""ACCEPTANCE A1-A7, C1, C4 — the deterministic risk layer.

These run with no network, no LLM and no real clock. That is the point: this
layer is the only thing between the agent and the account now that mandatory
human approval has been removed, so it must be provable in isolation.

Rejections are tested harder than approvals. An approval bug costs a missed
trade; a rejection bug costs money.
"""
from __future__ import annotations

import datetime as dt

import pytest

from trading_agent.config import Config, ConfigError
from trading_agent.guardrails import OrderIntent, evaluate
from trading_agent.state import State

NOW = dt.datetime(2026, 9, 11, 15, 0, tzinfo=dt.timezone.utc)


@pytest.fixture
def cfg() -> Config:
    return Config.for_testing(
        max_position_usd=150.0,
        max_deployed_usd=750.0,
        max_trades_per_day=5,
        daily_loss_limit_usd=50.0,
        account_equity_usd=1000.0,
    )


@pytest.fixture
def state(tmp_path) -> State:
    return State(tmp_path / "state.db")


def intent(notional: float, symbol: str = "XBI", side: str = "buy") -> OrderIntent:
    return OrderIntent(symbol=symbol, side=side, notional_usd=notional)


# --- A1 position size -------------------------------------------------------

def test_a1_rejects_position_above_max(cfg, state):
    d = evaluate(intent(150.01), state=state, config=cfg, now=NOW)
    assert not d.allowed
    assert "max_position" in d.reason


def test_a1_allows_position_exactly_at_max(cfg, state):
    # Boundary belongs to the allowed side; a limit you cannot reach is a
    # different limit than the one configured.
    assert evaluate(intent(150.00), state=state, config=cfg, now=NOW).allowed


def test_a1_rejects_zero_and_negative(cfg, state):
    for bad in (0.0, -1.0):
        d = evaluate(intent(bad), state=state, config=cfg, now=NOW)
        assert not d.allowed, f"notional {bad} must be rejected"


def test_a1_rejects_nan(cfg, state):
    d = evaluate(intent(float("nan")), state=state, config=cfg, now=NOW)
    assert not d.allowed
    # NaN compares false against every bound, so a naive `>` check would let it
    # through. This asserts the explicit finiteness guard exists.
    assert "finite" in d.reason or "invalid" in d.reason


# --- A2 total deployed ------------------------------------------------------

def test_a2_rejects_when_total_deployed_would_exceed_cap(cfg, state):
    state.set_deployed_usd(700.0)
    d = evaluate(intent(100.0), state=state, config=cfg, now=NOW)
    assert not d.allowed
    assert "max_deployed" in d.reason


def test_a2_allows_up_to_the_cap(cfg, state):
    state.set_deployed_usd(700.0)
    assert evaluate(intent(50.0), state=state, config=cfg, now=NOW).allowed


# --- A3 trade rate ----------------------------------------------------------

def test_a3_rejects_trade_beyond_daily_count(cfg, state):
    for _ in range(5):
        state.record_trade(NOW)
    d = evaluate(intent(100.0), state=state, config=cfg, now=NOW)
    assert not d.allowed
    assert "max_trades" in d.reason


def test_a3_counter_resets_next_day(cfg, state):
    for _ in range(5):
        state.record_trade(NOW)
    tomorrow = NOW + dt.timedelta(days=1)
    assert evaluate(intent(100.0), state=state, config=cfg, now=tomorrow).allowed


# --- A4 daily loss ----------------------------------------------------------

def test_a4_halts_after_daily_loss_breached(cfg, state):
    state.set_daily_pnl_usd(-50.01, NOW)
    d = evaluate(intent(10.0), state=state, config=cfg, now=NOW)
    assert not d.allowed
    assert "daily_loss" in d.reason


def test_a4_halt_persists_for_rest_of_day_even_if_pnl_recovers(cfg, state):
    # Once tripped, the day is over. A breaker that un-trips when the market
    # bounces is not a breaker.
    state.set_daily_pnl_usd(-60.0, NOW)
    assert not evaluate(intent(10.0), state=state, config=cfg, now=NOW).allowed
    state.set_daily_pnl_usd(-1.0, NOW)
    d = evaluate(intent(10.0), state=state, config=cfg, now=NOW + dt.timedelta(hours=1))
    assert not d.allowed, "circuit breaker must latch for the day"


def test_a4_resets_next_trading_day(cfg, state):
    state.set_daily_pnl_usd(-60.0, NOW)
    assert evaluate(
        intent(10.0), state=state, config=cfg, now=NOW + dt.timedelta(days=1)
    ).allowed


# --- A5 kill switch ---------------------------------------------------------

def test_a5_rejects_everything_while_stopped(cfg, state):
    state.set_kill_switch(True)
    d = evaluate(intent(1.0), state=state, config=cfg, now=NOW)
    assert not d.allowed
    assert "kill_switch" in d.reason


def test_a5_kill_switch_beats_every_other_check(cfg, state):
    # A perfectly valid order is still refused. Ordering matters: the kill
    # switch must be evaluated before anything that could raise.
    state.set_kill_switch(True)
    assert not evaluate(intent(10.0), state=state, config=cfg, now=NOW).allowed


# --- A7 no hidden dependencies ---------------------------------------------

def test_a7_guardrails_import_nothing_that_does_io():
    """The layer must not be able to reach the network even by accident."""
    import trading_agent.guardrails as g

    src = __import__("pathlib").Path(g.__file__).read_text()
    for forbidden in ("import httpx", "import requests", "alpaca", "telegram", "openai"):
        assert forbidden not in src, f"guardrails must not import {forbidden}"


# --- ACCEPTANCE C1, C4 — the approval gate ---------------------------------


def _intent(notional: float = 300.0):
    return OrderIntent(symbol="XBI", side="buy", notional_usd=notional,
                       correlation_id="c1")


def test_c1_order_at_or_above_threshold_is_refused_without_approval(tmp_path):
    state = State(tmp_path / "s.db")
    config = Config.for_testing(approval_threshold_usd=250.0,
                                max_position_usd=1000.0, max_deployed_usd=1000.0)
    decision = evaluate(_intent(), state=state, config=config, now=NOW)
    assert not decision.allowed
    assert "approval_required" in decision.reason
    # No token minted means broker.submit() refuses it even if something tried.
    assert decision.intent is None


def test_c1_granted_approval_lets_the_same_order_through(tmp_path):
    state = State(tmp_path / "s.db")
    config = Config.for_testing(approval_threshold_usd=250.0,
                                max_position_usd=1000.0, max_deployed_usd=1000.0)
    intent = _intent()
    state.add_pending_approval(intent.approval_key, {"symbol": "XBI"}, NOW)
    state.set_approval(intent.approval_key, "granted")

    decision = evaluate(intent, state=state, config=config, now=NOW)
    assert decision.allowed, decision.reason
    assert decision.intent.is_approved


def test_c1_denied_and_expired_approvals_both_refuse(tmp_path):
    config = Config.for_testing(approval_threshold_usd=250.0,
                                max_position_usd=1000.0, max_deployed_usd=1000.0)
    for outcome in ("denied", "expired"):
        state = State(tmp_path / f"{outcome}.db")
        intent = _intent()
        state.add_pending_approval(intent.approval_key, {}, NOW)
        if outcome == "denied":
            state.set_approval(intent.approval_key, "denied")
        else:
            state.expire_approvals(NOW + dt.timedelta(hours=2), 3600)
        assert not evaluate(intent, state=state, config=config, now=NOW).allowed


def test_c1_below_threshold_never_asks(tmp_path):
    state = State(tmp_path / "s.db")
    config = Config.for_testing(approval_threshold_usd=250.0,
                                max_position_usd=1000.0, max_deployed_usd=1000.0)
    assert evaluate(_intent(249.99), state=state, config=config, now=NOW).allowed


def test_c4_threshold_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY_ID", "k")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "s")

    assert Config.from_env().approval_threshold_usd == float("inf")

    monkeypatch.setenv("APPROVAL_THRESHOLD_USD", "250")
    monkeypatch.setenv("APPROVAL_TTL_SECONDS", "900")
    config = Config.from_env()
    assert config.approval_threshold_usd == 250.0
    assert config.approval_ttl_seconds == 900.0


def test_c4_a_nan_limit_is_refused_rather_than_disabling_the_limit(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY_ID", "k")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "s")
    monkeypatch.setenv("MAX_POSITION_USD", "nan")
    with pytest.raises(ConfigError):
        Config.from_env()
