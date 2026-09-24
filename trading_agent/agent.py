"""The decision cycle.

One pass: reconcile -> check we may trade at all -> gather catalysts -> ask the
model -> put every proposal through the guardrail -> submit what survives.

The ordering is the design. Each stage can only reduce what reaches the broker,
never expand it, and every stage that fails stops the cycle rather than falling
through to a default. There is no path from a proposal to an order that skips
guardrails.evaluate(); broker.submit() refuses anything without the token it
mints.

Deliberately NOT LangGraph, which the original brief named. See DECISIONS A-11:
the graph's value is branching, tool orchestration and human-in-the-loop nodes.
Reasoning now happens inside opencode, mandatory approval was removed, and what
remains is this linear pipeline. Adding langchain+langgraph to a Raspberry Pi to
express a straight line would be weight without benefit, and every dependency
near an order path is a liability. Easy to revisit if the flow grows branches.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from trading_agent.audit import new_correlation_id
from trading_agent.guardrails import OrderIntent, evaluate
from trading_agent.market import is_market_open
from trading_agent.reasoning import proposals_or_none


@dataclass
class CycleResult:
    ran: bool = False
    skipped_reason: str = ""
    proposed: int = 0
    submitted: int = 0
    rejected: list[str] = field(default_factory=list)
    orders: list[str] = field(default_factory=list)
    exits: list[str] = field(default_factory=list)


def run_cycle(*, state, config, broker, feed, reasoner, audit, views=None,
              ask=None, notify=None, now: dt.datetime | None = None) -> CycleResult:
    """`ask` is called with (approval_key, payload) when an order needs the
    operator's explicit yes. It is optional, and its absence does not soften
    the gate: an unanswered request stays unanswered and the order stays
    refused."""
    now = now or dt.datetime.now(dt.timezone.utc)
    cid = new_correlation_id()

    # C3: sweep deadlines before reading any status, so a request whose window
    # closed is read as denied on this very cycle rather than the next one.
    for expired in state.expire_approvals(now, config.approval_ttl_seconds):
        audit.record("approval_expired", cid, {"approval_key": expired})

    # The kill switch is checked here as well as inside the guardrail. Cheap,
    # and it means a halted agent does no work at all rather than doing the
    # work and discarding it.
    if state.kill_switch_engaged():
        return CycleResult(skipped_reason="kill switch engaged")

    if not is_market_open(now):
        return CycleResult(skipped_reason="market closed")

    # Never act on a stale picture of the account.
    try:
        recon = broker.reconcile(state)
        audit.record("reconcile", cid, recon)
    except Exception as exc:  # noqa: BLE001 — unverified account means no trading
        audit.record("reconcile_failed", cid, {"error": str(exc)})
        return CycleResult(skipped_reason=f"reconcile failed: {exc}")

    # What is actually held. Fail closed: a cycle that cannot see the portfolio
    # would mistake a broker outage for having nothing to manage.
    try:
        held = broker.open_positions()
    except Exception as exc:  # noqa: BLE001
        audit.record("positions_unavailable", cid, {"error": str(exc)})
        return CycleResult(skipped_reason=f"positions unavailable: {exc}")

    result = CycleResult(ran=True)
    _exit_flipped_views(held, state=state, config=config, broker=broker,
                        views=views, audit=audit, notify=notify, now=now,
                        cid=cid, result=result)

    catalysts = feed.upcoming_trials() + feed.recent_news()
    audit.record("catalysts", cid, {"count": len(catalysts)})

    # None means the backend is unreachable or its answer was unusable. Open
    # nothing — do not retry into a trade, do not guess.
    proposals = proposals_or_none(
        reasoner,
        catalysts=[c.summary() for c in catalysts],
        # The model was previously shown an empty portfolio, so it could not
        # reason about what was already held, let alone propose leaving it.
        positions=[f"{p['symbol']}: {p['market_value']:.0f} USD "
                   f"({p['unrealized_plpc'] * 100:+.1f}%)" for p in held],
    )
    if proposals is None:
        audit.record("reasoning_unavailable", cid, {})
        return CycleResult(skipped_reason="reasoning unavailable")

    result.proposed = len(proposals)
    for p in proposals:
        intent = p.to_intent()
        intent = type(intent)(**{**intent.__dict__, "correlation_id": cid})
        audit.record("proposal", cid, {
            "symbol": p.symbol, "side": p.side,
            "notional": p.notional_usd, "rationale": p.rationale,
        })

        # Paper trading is a bounded warm-up: it lets the operator see the
        # system work while consultations build a useful history. Real-money
        # buys still require a view recorded BEFORE the outcome was known.
        # That makes their judgment the alpha source rather than the model's,
        # and makes every live trade traceable to a prediction that can be
        # scored afterwards.
        #
        # Selling is exempt: getting out is risk reduction and must not wait on
        # anyone's availability.
        if config.is_live and views is not None and p.side == "buy":
            view = views.for_symbol(p.symbol, now=now)
            # Positive only. is_actionable means "the operator holds an
            # opinion", which is true of "no" as well — so this gate used to
            # let a trial the operator had called a failure be bought anyway.
            if view is None or view.stance != "positive":
                why = ("no view recorded" if view is None
                       else f"{view.stance} view recorded")
                audit.record("view_gate", cid, {"symbol": p.symbol, "reason": why})
                result.rejected.append(f"{p.symbol}: {why}")
                continue
            audit.record("view_gate", cid, {
                "symbol": p.symbol, "stance": view.stance,
                "confidence": view.confidence, "note": view.note,
            })

        decision = evaluate(intent, state=state, config=config, now=now)
        audit.record("guardrail", cid, {
            "symbol": p.symbol, "allowed": decision.allowed, "reason": decision.reason,
        })
        if not decision.allowed:
            result.rejected.append(f"{p.symbol}: {decision.reason}")
            # Refused for want of an answer: record the question and ask it
            # once. The order stays refused either way — asking is what makes
            # the gate usable, not what opens it.
            if decision.reason.startswith("approval_required"):
                key = intent.approval_key
                if state.approval_status(key) is None:
                    payload = {"symbol": p.symbol, "side": p.side,
                               "notional_usd": p.notional_usd,
                               "rationale": p.rationale}
                    state.add_pending_approval(key, payload, now)
                    audit.record("approval_requested", cid,
                                 {"approval_key": key, **payload})
                    if ask is not None:
                        try:
                            ask(key, payload)
                        except Exception as exc:  # noqa: BLE001
                            audit.record("approval_ask_failed", cid,
                                         {"approval_key": key, "error": str(exc)})
            continue

        try:
            order_id = broker.submit(decision.intent)
        except Exception as exc:  # noqa: BLE001 — one bad order must not end the cycle
            audit.record("order_failed", cid, {"symbol": p.symbol, "error": str(exc)})
            result.rejected.append(f"{p.symbol}: submit failed: {exc}")
            continue

        # Counted only after the broker accepted it. Counting on intent would
        # let failed submissions burn the daily trade budget.
        state.record_trade(now)
        audit.record("order", cid, {"symbol": p.symbol, "broker_order_id": order_id})
        result.submitted += 1
        result.orders.append(order_id)

    return result


def _exit_flipped_views(held, *, state, config, broker, views, audit, notify,
                        now, cid, result) -> None:
    """Sell what the operator has changed their mind about.

    A position exists because of a recorded call. When that call is changed to
    "no" or "skip" before the results, the reason for holding is gone, and the
    honest response is to leave rather than to keep paying for a risk whose
    justification has been withdrawn.

    Deliberately not triggered by a *missing* view. Views expire after ninety
    days by design, and liquidating a portfolio because an opinion aged out
    would be a surprise, not a decision. That case is recorded and left alone.
    """
    if views is None:
        return
    for position in held:
        symbol = position["symbol"]
        view = views.for_symbol(symbol, now=now)
        if view is None:
            audit.record("held_without_view", cid, {"symbol": symbol})
            continue
        # Anything other than a positive call withdraws the reason to hold.
        if view.stance == "positive":
            continue

        intent = OrderIntent(symbol=symbol, side="sell",
                             notional_usd=abs(position["market_value"]),
                             correlation_id=cid)
        decision = evaluate(intent, state=state, config=config, now=now)
        audit.record("exit_guardrail", cid, {
            "symbol": symbol, "allowed": decision.allowed,
            "reason": decision.reason, "view": view.stance,
        })
        if not decision.allowed:
            result.rejected.append(f"{symbol}: exit refused: {decision.reason}")
            continue

        try:
            order_id = broker.close_position(decision.intent)
        except Exception as exc:  # noqa: BLE001 — one failure must not end the cycle
            audit.record("exit_failed", cid, {"symbol": symbol, "error": str(exc)})
            result.rejected.append(f"{symbol}: exit failed: {exc}")
            continue

        state.record_trade(now)
        audit.record("exit", cid, {"symbol": symbol, "broker_order_id": order_id,
                                   "view": view.stance, "note": view.note})
        result.exits.append(order_id)
        if notify is not None:
            try:
                notify(f"Sold {symbol}. You changed your call to "
                       f"{'no' if view.stance == 'negative' else 'skip'}, so the "
                       f"reason for holding it was gone.")
            except Exception as exc:  # noqa: BLE001 — telling you is not the trade
                audit.record("exit_notify_failed", cid,
                             {"symbol": symbol, "error": str(exc)})
