"""The audit trail.

The requirement is not "log things" — it is that any order can be traced back
to what caused it, months later, without the author present. So every step of a
decision carries the same correlation id, and the log is JSON lines so it can be
grepped, filtered and parsed without a tool.

It is also read by humans and pasted into tickets, so secrets are redacted on
the way in rather than trusted not to be passed.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import logging.handlers
import uuid
from pathlib import Path

# Substring match, not exact keys: whatever wraps a credential tends to keep the
# word in the name, and over-redacting an audit log costs nothing.
_SECRET_HINTS = ("secret", "token", "password", "api_key", "apikey", "passphrase")
_REDACTED = "[redacted]"


def new_correlation_id() -> str:
    return uuid.uuid4().hex[:16]


def _scrub(value):
    if isinstance(value, dict):
        return {
            k: (_REDACTED if any(h in k.lower() for h in _SECRET_HINTS) else _scrub(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


class AuditLog:
    def __init__(self, path: Path | str, *, max_bytes: int = 5_000_000,
                 backup_count: int = 3) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._logger = logging.getLogger(f"audit.{self.path}")
        self._logger.setLevel(logging.INFO)
        self._logger.propagate = False
        # Size-capped and rotated: this runs continuously on an SD card, so an
        # unbounded log is a matter of time rather than an edge case.
        if not self._logger.handlers:
            h = logging.handlers.RotatingFileHandler(
                self.path, maxBytes=max_bytes, backupCount=backup_count
            )
            h.setFormatter(logging.Formatter("%(message)s"))
            self._logger.addHandler(h)

    def record(self, event: str, correlation_id: str, payload: dict) -> None:
        self._logger.info(json.dumps({
            "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
            "event": event,
            "correlation_id": correlation_id,
            "data": _scrub(payload),
        }, sort_keys=True))

    def _entries(self):
        for path in [self.path] + sorted(self.path.parent.glob(self.path.name + ".*")):
            try:
                for line in path.read_text().splitlines():
                    if line.strip():
                        try:
                            yield json.loads(line)
                        except json.JSONDecodeError:
                            continue  # a torn last line after rotation
            except OSError:
                continue

    def day_report(self, day: str) -> str:
        """What the agent did on one day, and why, in a form that reads on a
        phone.

        Built from the audit log rather than from a second running tally: the
        log is what actually happened, and a summary that can disagree with it
        is worse than no summary.
        """
        events = [e for e in self._entries() if str(e.get("ts", "")).startswith(day)]
        if not events:
            return f"{day}: nothing recorded."

        def of(kind):
            return [e for e in events if e.get("event") == kind]

        lines = [f"*{day}*", ""]

        cycles = of("catalysts")
        lines.append(
            f"{len(cycles)} cycles, "
            f"{max((e['data'].get('count', 0) for e in cycles), default=0)} "
            f"catalysts tracked."
        )

        for e in of("question_sent"):
            lines.append(f"• asked you about *{e['data']['symbol']}* — "
                         f"{e['data'].get('title', '')[:120]}")
        for e in of("view_recorded"):
            lines.append(f"• you said *{e['data']['stance']}* "
                         f"{e['data'].get('confidence')}/5 on "
                         f"{e['data']['symbol']}")

        orders = of("order")
        for e in orders:
            why = next((p["data"].get("rationale", "") for p in of("proposal")
                        if p.get("correlation_id") == e.get("correlation_id")
                        and p["data"].get("symbol") == e["data"].get("symbol")), "")
            lines.append(f"• BOUGHT *{e['data']['symbol']}* — {why[:200]}")

        # Refusals are the interesting half: this is a system designed to say no.
        refusals: dict[str, int] = {}
        for e in of("guardrail") + of("view_gate"):
            if e["event"] == "view_gate" or not e["data"].get("allowed", True):
                reason = str(e["data"].get("reason", "")).split(":")[0]
                refusals[reason] = refusals.get(reason, 0) + 1
        for reason, n in sorted(refusals.items(), key=lambda kv: -kv[1]):
            lines.append(f"• declined {n}x — {reason}")

        if not orders:
            lines += ["", "No trades. That is a normal day for this agent: it "
                      "needs a catalyst, your view on it, and room inside every "
                      "limit before it buys anything."]
        return "\n".join(lines)

    def chain_for_order(self, broker_order_id: str) -> list[dict]:
        """Every step that led to one order, oldest first."""
        entries = list(self._entries())
        cid = next(
            (e["correlation_id"] for e in entries
             if e.get("event") == "order"
             and e.get("data", {}).get("broker_order_id") == broker_order_id),
            None,
        )
        if cid is None:
            return []
        return sorted(
            (e for e in entries if e.get("correlation_id") == cid),
            key=lambda e: e["ts"],
        )
