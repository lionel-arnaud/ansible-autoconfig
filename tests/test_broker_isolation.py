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
