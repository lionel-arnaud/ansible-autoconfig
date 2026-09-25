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

    def submit_order(self, order_data):
        self.submitted.append(order_data)
        return type("Order", (), {"id": f"fake-{len(self.submitted)}"})()

    def get_all_positions(self):
        return list(getattr(self, "positions", []) or [])

    def close_position(self, symbol):
        self.closed = getattr(self, "closed", [])
        self.closed.append(symbol)
        return type("Order", (), {"id": f"fake-close-{len(self.closed)}"})()

    def get_account(self):
        return type("Account", (), {"equity": "1000", "cash": "1000",
                                    "buying_power": "2000"})()

    def get_orders(self):
        return list(getattr(self, "open_orders", []) or [])

    def cancel_order_by_id(self, order_id):
        self.cancelled = getattr(self, "cancelled", [])
        self.cancelled.append(order_id)


class Broker:
    def __init__(self, client, *, paper: bool = True, order_request=None) -> None:
        self._client = client
        self.paper = paper
        self._order_request = order_request or (lambda intent: {
            "symbol": intent.symbol,
            "notional": intent.notional_usd,
            "side": intent.side,
            "time_in_force": "day",
            "client_order_id": intent.idempotency_key,
        })

    @classmethod
    def for_testing(cls) -> "Broker":
        return cls(_FakeClient(), paper=True)

    @classmethod
    def from_config(cls, config) -> "Broker":
        # Imported here, not at module scope, so the test suite can exercise
        # this file without alpaca-py installed.
        from alpaca.trading.client import TradingClient
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import MarketOrderRequest

        client = TradingClient(
            api_key=config.alpaca_key_id,
            secret_key=config.alpaca_secret_key,
            paper=not config.is_live,
        )
        def order_request(intent):
            return MarketOrderRequest(
                symbol=intent.symbol,
                notional=intent.notional_usd,
                side=OrderSide(intent.side),
                time_in_force=TimeInForce.DAY,
                client_order_id=intent.idempotency_key,
            )

        return cls(client, paper=not config.is_live, order_request=order_request)

    def submit(self, intent: OrderIntent) -> str:
        if not intent.is_approved:
            raise UnapprovedOrderError(
                f"{intent.symbol} {intent.side} {intent.notional_usd}: no guardrail "
                "approval. Route through guardrails.evaluate() — the broker is not "
                "a bypass."
            )
        # Alpaca's current SDK accepts one OrderRequest object, not order fields
        # as keyword arguments. The request retains the idempotency key, so a
        # restart between submitting and recording cannot double-fill.
        order = self._client.submit_order(order_data=self._order_request(intent))
        return str(order.id)

    def open_positions(self) -> list[dict]:
        """What is held right now.

        Raises rather than returning nothing on failure: a cycle that cannot
        see the portfolio must not conclude there is nothing to manage.
        """
        try:
            positions = self._client.get_all_positions()
        except Exception as exc:  # noqa: BLE001
            raise BrokerUnavailableError(str(exc)) from exc

        def num(obj, name):
            try:
                return float(getattr(obj, name, 0) or 0)
            except (TypeError, ValueError):
                return 0.0

        return [{"symbol": str(getattr(p, "symbol", "")).upper(),
                 "qty": num(p, "qty"),
                 "market_value": num(p, "market_value"),
                 "unrealized_pl": num(p, "unrealized_pl"),
                 "unrealized_plpc": num(p, "unrealized_plpc")}
                for p in positions or []]

    def close_position(self, intent: OrderIntent) -> str:
        """Close a position completely.

        Same approval rule as submit(): an exit is still an order, and the
        guardrail is not optional merely because this direction reduces risk.

        Closing the position rather than selling an amount: the market value
        moves between deciding and sending, and an order for slightly more than
        is held is rejected outright, which would leave the position open at
        exactly the moment it was meant to be closed.
        """
        if not intent.is_approved:
            raise UnapprovedOrderError(
                f"{intent.symbol} exit: no guardrail approval. Route through "
                "guardrails.evaluate() — the broker is not a bypass."
            )
        if intent.side != "sell":
            raise ValueError(f"close_position is for exits, got {intent.side!r}")
        order = self._client.close_position(intent.symbol)
        return str(getattr(order, "id", "") or "")

    def account_summary(self) -> dict:
        """A read-only picture of the account, for the operator's daily page.

        Never raises. The page is rendered by the nightly backup push, and a
        broker that is down must cost the page its portfolio section, not the
        backup its run. The error text is kept for logs but is not meant to be
        displayed: a broker's error message is not a string to publish.
        """
        try:
            account = self._client.get_account()
            positions = self._client.get_all_positions()
        except Exception as exc:  # noqa: BLE001
            return {"available": False, "error": str(exc)}

        def num(obj, name):
            try:
                return float(getattr(obj, name, 0) or 0)
            except (TypeError, ValueError):
                return 0.0

        return {
            "available": True,
            "paper": self.paper,
            "equity": num(account, "equity"),
            "cash": num(account, "cash"),
            "buying_power": num(account, "buying_power"),
            "positions": [
                {
                    "symbol": str(getattr(p, "symbol", "")),
                    "qty": num(p, "qty"),
                    "market_value": num(p, "market_value"),
                    "cost_basis": num(p, "cost_basis"),
                    "unrealized_pl": num(p, "unrealized_pl"),
                    "unrealized_plpc": num(p, "unrealized_plpc"),
                }
                for p in positions or []
            ],
        }

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
