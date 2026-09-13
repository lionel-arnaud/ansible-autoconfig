"""The Alpaca boundary — the only module permitted to place an order.

Two structural guarantees, both enforced by tests rather than convention:

  * this is the only file importing the Alpaca trading client, so there is one
    place where money leaves;
  * submit() refuses any intent without a guardrail approval token, so calling
    the broker directly cannot skip the risk checks.

Alpaca is treated as the source of truth about the account. Local state is a
cache, and on any disagreement the cache is wrong.
"""
from __future__ import annotations

from dataclasses import dataclass

from trading_agent.guardrails import OrderIntent


class UnapprovedOrderError(RuntimeError):
    """Raised when an intent reaches the broker without guardrail approval."""


class BrokerUnavailableError(RuntimeError):
    """Raised when the broker cannot be reached. Callers must fail closed."""


@dataclass
class _FakeClient:
    """Stands in for Alpaca in tests. Unit tests never touch the network — a
    guardrail bug must not be able to hide behind a timeout."""

    submitted: list = None

    def __post_init__(self):
        self.submitted = []

    def submit_order(self, **kwargs):
        self.submitted.append(kwargs)
        return type("Order", (), {"id": f"fake-{len(self.submitted)}"})()

    def get_all_positions(self):
        return []

    def get_orders(self):
        return list(getattr(self, "open_orders", []) or [])

    def cancel_order_by_id(self, order_id):
        self.cancelled = getattr(self, "cancelled", [])
        self.cancelled.append(order_id)


class Broker:
    def __init__(self, client, *, paper: bool = True) -> None:
        self._client = client
        self.paper = paper

    @classmethod
    def for_testing(cls) -> "Broker":
        return cls(_FakeClient(), paper=True)

    @classmethod
    def from_config(cls, config) -> "Broker":
        # Imported here, not at module scope, so the test suite can exercise
        # this file without alpaca-py installed.
        from alpaca.trading.client import TradingClient

        client = TradingClient(
            api_key=config.alpaca_key_id,
            secret_key=config.alpaca_secret_key,
            paper=not config.is_live,
        )
        return cls(client, paper=not config.is_live)

    def submit(self, intent: OrderIntent) -> str:
        if not intent.is_approved:
            raise UnapprovedOrderError(
                f"{intent.symbol} {intent.side} {intent.notional_usd}: no guardrail "
                "approval. Route through guardrails.evaluate() — the broker is not "
                "a bypass."
            )
        order = self._client.submit_order(
            symbol=intent.symbol,
            notional=intent.notional_usd,
            side=intent.side,
            time_in_force="day",
            # Alpaca de-duplicates on this, so a retry or a restart mid-flight
            # cannot produce a second fill.
            client_order_id=intent.idempotency_key,
        )
        return str(order.id)

    def cancel_all_orders(self) -> dict:
        """Cancel every open order. Best effort, reporting per order.

        Called after the kill switch is already engaged, never before: the halt
        must not wait on a broker that may be slow or unreachable. Anything that
        cannot be cancelled is reported rather than swallowed, because an order
        the operator believes is cancelled and is not is worse than a failure
        they were told about.
        """
        try:
            orders = self._client.get_orders()
        except Exception as exc:  # noqa: BLE001
            return {"cancelled": 0, "failed": 0, "error": str(exc)}

        cancelled, failures = 0, []
        for order in orders or []:
            oid = str(getattr(order, "id", ""))
            try:
                self._client.cancel_order_by_id(oid)
                cancelled += 1
            except Exception as exc:  # noqa: BLE001 — one failure must not stop the rest
                failures.append({"order_id": oid, "error": str(exc)})
        return {"cancelled": cancelled, "failed": len(failures), "failures": failures}

    def reconcile(self, state) -> dict:
        """Startup reconciliation. Alpaca is truth; local state is a cache.

        Returns what changed, so the divergence is auditable rather than
        silently corrected.
        """
        try:
            positions = self._client.get_all_positions()
        except Exception as exc:  # noqa: BLE001 — any failure must fail closed
            raise BrokerUnavailableError(str(exc)) from exc

        actual = sum(abs(float(getattr(p, "market_value", 0.0))) for p in positions)
        cached = state.deployed_usd()
        state.set_deployed_usd(actual)
        return {
            "positions": len(positions),
            "deployed_actual": actual,
            "deployed_cached": cached,
            "diverged": abs(actual - cached) > 0.01,
        }
