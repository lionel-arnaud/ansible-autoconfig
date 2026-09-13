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
from trading_agent.guardrails import evaluate
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


def run_cycle(*, state, config, broker, feed, reasoner, audit, views=None,
              ask=None, now: dt.datetime | None = None) -> CycleResult:
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

    catalysts = feed.upcoming_trials() + feed.recent_news()
    audit.record("catalysts", cid, {"count": len(catalysts)})

    # None means the backend is unreachable or its answer was unusable. Open
    # nothing — do not retry into a trade, do not guess.
    proposals = proposals_or_none(
        reasoner,
        catalysts=[c.summary() for c in catalysts],
        positions=[],
    )
    if proposals is None:
        audit.record("reasoning_unavailable", cid, {})
        return CycleResult(skipped_reason="reasoning unavailable")

    result = CycleResult(ran=True, proposed=len(proposals))
    for p in proposals:
        intent = p.to_intent()
        intent = type(intent)(**{**intent.__dict__, "correlation_id": cid})
        audit.record("proposal", cid, {
            "symbol": p.symbol, "side": p.side,
            "notional": p.notional_usd, "rationale": p.rationale,
        })

        # O-07: opening a position requires a view the operator recorded
        # BEFORE the outcome was known. That makes their judgment the alpha
        # source rather than the model's, and makes every trade traceable to a
        # prediction that can be scored afterwards.
        #
        # Selling is exempt: getting out is risk reduction and must not wait on
        # anyone's availability.
        if views is not None and p.side == "buy":
            view = views.for_symbol(p.symbol, now=now)
            if view is None or not view.is_actionable:
                why = "no view recorded" if view is None else "no_opinion recorded"
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
