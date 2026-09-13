"""The deterministic risk layer.

There is no mandatory human approval in this system — the operator removed it
deliberately. That makes this module the only thing standing between the
model's decision and the account. It is written to be read once and believed:
plain arithmetic, explicit order, no cleverness.

Deliberately importable with no I/O of any kind. No network client, no broker,
no model. A test enforces that, because the guarantee is only worth as much as
the thing preventing tomorrow's convenient import.

Time is an argument, never read from the clock, so every day-boundary rule is
testable without waiting for midnight.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import math
from dataclasses import dataclass, field, replace

# Opaque marker proving an intent came through evaluate(). broker.submit()
# refuses anything without it, so the guardrail cannot be skipped by calling the
# broker directly.
_APPROVAL_SALT = "guardrail-v1"


@dataclass(frozen=True)
class OrderIntent:
    symbol: str
    side: str
    notional_usd: float
    correlation_id: str = ""
    approval_token: str = field(default="", compare=False)

    @property
    def idempotency_key(self) -> str:
        """Stable for the same logical decision, so a crash between deciding and
        submitting cannot double-fill when the process comes back."""
        raw = f"{self.symbol}|{self.side}|{self.notional_usd}|{self.correlation_id}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    @property
    def approval_key(self) -> str:
        """Identifies the DECISION, not the cycle. Deliberately excludes the
        correlation id: the operator answers a question about buying $300 of
        XBI, and that answer has to still match when the next cycle re-proposes
        it under a new correlation id. Notional is included, so approving $300
        does not approve $900."""
        raw = f"{self.symbol}|{self.side}|{self.notional_usd}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    def _expected_token(self) -> str:
        return hashlib.sha256(
            f"{_APPROVAL_SALT}|{self.idempotency_key}".encode()
        ).hexdigest()[:32]

    @property
    def is_approved(self) -> bool:
        return bool(self.approval_token) and self.approval_token == self._expected_token()


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str
    intent: OrderIntent | None = None


def evaluate(intent: OrderIntent, *, state, config, now: dt.datetime) -> Decision:
    """Approve or reject an order. Checks run in order of severity."""

    # 1. Kill switch first, before anything that could raise. If the operator
    #    said stop, nothing else about the order matters.
    if state.kill_switch_engaged():
        return Decision(False, "kill_switch: trading halted, /resume to clear")

    # 2. Sanity. NaN compares false against every bound, so a naive `>` check
    #    would let it straight through to the broker.
    n = intent.notional_usd
    if not isinstance(n, (int, float)) or not math.isfinite(n):
        return Decision(False, f"invalid: notional must be finite, got {n!r}")
    if n <= 0:
        return Decision(False, f"invalid: notional must be positive, got {n}")
    if intent.side not in ("buy", "sell"):
        return Decision(False, f"invalid: side must be buy or sell, got {intent.side!r}")

    # 3. Daily loss breaker. Latched: once tripped the day is over, even if the
    #    position recovers. Checked before the P&L itself so a recovery cannot
    #    silently re-arm trading.
    if state.loss_breaker_tripped(now):
        return Decision(False, "daily_loss: circuit breaker latched for today")
    if state.daily_pnl_usd(now) <= -abs(config.daily_loss_limit_usd):
        state.trip_loss_breaker(now)
        return Decision(
            False,
            f"daily_loss: {state.daily_pnl_usd(now):.2f} breached "
            f"-{abs(config.daily_loss_limit_usd):.2f}, halted for today",
        )

    # 4. Trade rate.
    used = state.trades_today(now)
    if used >= config.max_trades_per_day:
        return Decision(
            False, f"max_trades: {used}/{config.max_trades_per_day} already used today"
        )

    # 5. Position size. The boundary belongs to the allowed side — a limit you
    #    cannot reach is a different limit than the one configured.
    if n > config.max_position_usd:
        return Decision(
            False, f"max_position: {n:.2f} exceeds {config.max_position_usd:.2f}"
        )

    # 6. Total capital deployed.
    if intent.side == "buy":
        projected = state.deployed_usd() + n
        if projected > config.max_deployed_usd:
            return Decision(
                False,
                f"max_deployed: {projected:.2f} would exceed "
                f"{config.max_deployed_usd:.2f}",
            )

    # 7. Human approval, last: there is no point asking about an order the risk
    #    layer would have refused anyway. With the threshold at its default of
    #    infinity no finite order reaches this branch, which is the operator's
    #    choice — but the gate is wired, so turning it back on is one env var.
    if n >= config.approval_threshold_usd:
        status = state.approval_status(intent.approval_key)
        if status != "granted":
            return Decision(
                False,
                f"approval_required: {n:.2f} at or above "
                f"{config.approval_threshold_usd:.2f} "
                f"({status or 'not yet requested'})",
            )

    approved = replace(intent, approval_token=intent._expected_token())
    return Decision(True, "approved", approved)


def approve_for_test(intent: OrderIntent) -> OrderIntent:
    """Mint an approval token without the checks. Tests only — production code
    must go through evaluate()."""
    return replace(intent, approval_token=intent._expected_token())
