"""ACCEPTANCE D1-D2 — coming back safely after a crash or reboot.

The Pi reboots for kernel upgrades and the operator kept unattended upgrades
enabled. So restarting mid-flight is a normal event, not an edge case, and it
must not produce a duplicate order or a forgotten position.
"""
from __future__ import annotations

from trading_agent.broker import Broker, BrokerUnavailableError
from trading_agent.guardrails import OrderIntent, approve_for_test
from trading_agent.state import State


class FakeClient:
    def __init__(self, positions=(), fail=False):
        self._positions = list(positions)
        self._fail = fail
        self.submitted = []

    def get_all_positions(self):
        if self._fail:
            raise RuntimeError("alpaca unreachable")
        return self._positions

    def submit_order(self, **kw):
        self.submitted.append(kw)
        return type("O", (), {"id": f"o{len(self.submitted)}"})()


class Pos:
    def __init__(self, mv):
        self.market_value = mv


def test_d1_alpaca_is_truth_and_local_state_is_corrected(tmp_path):
    s = State(tmp_path / "s.db")
    s.set_deployed_usd(999.0)  # stale local belief
    b = Broker(FakeClient(positions=[Pos(100.0), Pos(50.0)]))

    result = b.reconcile(s)

    assert result["diverged"] is True
    assert result["deployed_cached"] == 999.0
    assert s.deployed_usd() == 150.0, "Alpaca wins"


def test_d1_agreement_is_not_reported_as_divergence(tmp_path):
    s = State(tmp_path / "s.db")
    s.set_deployed_usd(150.0)
    b = Broker(FakeClient(positions=[Pos(100.0), Pos(50.0)]))
    assert b.reconcile(s)["diverged"] is False


def test_d1_unreachable_broker_fails_closed(tmp_path):
    """Never start trading on an unverified picture of the account."""
    s = State(tmp_path / "s.db")
    b = Broker(FakeClient(fail=True))
    try:
        b.reconcile(s)
        raise AssertionError("must raise rather than assume")
    except BrokerUnavailableError:
        pass


def test_d2_resubmitting_the_same_decision_reuses_the_idempotency_key(tmp_path):
    """A crash between deciding and submitting means the restart retries. The
    broker must be able to recognise it as the same order."""
    client = FakeClient()
    b = Broker(client)
    intent = approve_for_test(
        OrderIntent("MRNA", "buy", 100.0, correlation_id="decision-1")
    )
    b.submit(intent)
    b.submit(intent)  # the retry after restart
    keys = [c["client_order_id"] for c in client.submitted]
    assert keys[0] == keys[1], "Alpaca de-duplicates on this; it must be stable"


def test_d2_a_genuinely_different_decision_gets_a_different_key():
    a = OrderIntent("MRNA", "buy", 100.0, correlation_id="d1")
    b = OrderIntent("MRNA", "buy", 100.0, correlation_id="d2")
    assert a.idempotency_key != b.idempotency_key
