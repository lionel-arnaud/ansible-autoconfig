"""ACCEPTANCE A6 — the guardrail cannot be bypassed.

This is a structural test rather than a behavioural one. Behaviour can be
correct today and bypassed by tomorrow's convenient import; structure is what
keeps it true.
"""
from __future__ import annotations

import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent / "trading_agent"


def test_a6_only_broker_module_imports_the_alpaca_trading_client():
    offenders = []
    for path in ROOT.rglob("*.py"):
        if path.name == "broker.py":
            continue
        text = path.read_text()
        if "alpaca.trading" in text or "TradingClient" in text:
            offenders.append(path.name)
    assert not offenders, (
        f"only broker.py may import the Alpaca trading client; found in {offenders}"
    )


def test_a6_submit_refuses_an_unapproved_intent():
    """Calling the broker directly, bypassing the guardrail, must fail."""
    from trading_agent.broker import Broker, UnapprovedOrderError
    from trading_agent.guardrails import OrderIntent

    broker = Broker.for_testing()
    with pytest.raises(UnapprovedOrderError):
        broker.submit(OrderIntent(symbol="XBI", side="buy", notional_usd=10.0))


def test_a6_submit_accepts_an_approved_intent():
    from trading_agent.broker import Broker
    from trading_agent.guardrails import OrderIntent, approve_for_test

    broker = Broker.for_testing()
    assert broker.submit(approve_for_test(OrderIntent("XBI", "buy", 10.0)))


def test_a6_idempotency_key_is_stable_for_the_same_intent():
    """D2: a crash between decide and submit must not double-fill on restart."""
    from trading_agent.guardrails import OrderIntent

    a = OrderIntent(symbol="XBI", side="buy", notional_usd=10.0, correlation_id="c1")
    b = OrderIntent(symbol="XBI", side="buy", notional_usd=10.0, correlation_id="c1")
    c = OrderIntent(symbol="XBI", side="buy", notional_usd=10.0, correlation_id="c2")
    assert a.idempotency_key == b.idempotency_key
    assert a.idempotency_key != c.idempotency_key


# --- closing a position is still an order -----------------------------------

def test_closing_a_position_needs_guardrail_approval():
    """An exit reduces risk, which is exactly the argument that would be used
    to let it skip the checks. It does not."""
    from trading_agent.broker import Broker, UnapprovedOrderError
    from trading_agent.guardrails import OrderIntent

    broker = Broker.for_testing()
    with pytest.raises(UnapprovedOrderError):
        broker.close_position(OrderIntent(symbol="BMRN", side="sell",
                                          notional_usd=100.0))


def test_closing_refuses_a_buy():
    from trading_agent.broker import Broker
    from trading_agent.guardrails import OrderIntent, approve_for_test

    broker = Broker.for_testing()
    intent = approve_for_test(OrderIntent(symbol="BMRN", side="buy",
                                          notional_usd=100.0))
    with pytest.raises(ValueError):
        broker.close_position(intent)


def test_an_approved_exit_closes_the_whole_position():
    """By position, not by amount: the value moves between deciding and
    sending, and an order for more than is held is rejected outright."""
    from trading_agent.broker import Broker
    from trading_agent.guardrails import OrderIntent, approve_for_test

    broker = Broker.for_testing()
    intent = approve_for_test(OrderIntent(symbol="BMRN", side="sell",
                                          notional_usd=900.0))
    assert broker.close_position(intent)
    assert broker._client.closed == ["BMRN"]


def test_positions_unavailable_raises_rather_than_reporting_none():
    """Reporting an empty portfolio when the broker is down would look exactly
    like having nothing to manage."""
    from trading_agent.broker import Broker, BrokerUnavailableError

    broker = Broker.for_testing()

    def boom():
        raise OSError("down")

    broker._client.get_all_positions = boom
    with pytest.raises(BrokerUnavailableError):
        broker.open_positions()
