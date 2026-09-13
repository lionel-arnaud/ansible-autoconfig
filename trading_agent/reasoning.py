"""The model client.

Thin on purpose. The backend is opencode on serverannah so the provider can be
swapped without touching this code, and nothing provider-specific is allowed to
leak past this module.

The important behaviour is not what it returns but what it does when it cannot
return anything: it raises, and the loop opens no positions. A trading process
that guesses when its reasoning is unavailable is worse than one that stops.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from trading_agent.guardrails import OrderIntent


class ReasoningUnavailable(RuntimeError):
    """Backend unreachable, or its answer unusable. Callers must not trade."""


@dataclass(frozen=True)
class Proposal:
    symbol: str
    side: str
    notional_usd: float
    rationale: str
    correlation_id: str = ""

    def to_intent(self) -> OrderIntent:
        # Deliberately unapproved. A proposal is an opinion; only the guardrail
        # can turn one into something the broker will accept.
        return OrderIntent(
            symbol=self.symbol,
            side=self.side,
            notional_usd=self.notional_usd,
            correlation_id=self.correlation_id,
        )


class ReasoningClient:
    def __init__(self, transport, *, url: str = "") -> None:
        self._transport = transport
        self.url = url

    @classmethod
    def from_config(cls, config) -> "ReasoningClient":
        """Talk to opencode over the LAN.

        A session is created per cycle and deleted afterwards. The agent's
        memory is SQLite, not the model's context — carrying a conversation
        across cycles would let yesterday's reasoning colour today's, and would
        grow context until it had to be compacted mid-decision.
        """
        import httpx

        auth = (config.opencode_user, config.opencode_password)
        base = config.opencode_url.rstrip("/")

        def transport(payload: dict) -> str:
            # The caller sets this for prose; proposals keep the default.
            timeout = float(payload.get("timeout") or 180.0)
            with httpx.Client(auth=auth, timeout=timeout) as http:
                created = http.post(f"{base}/session",
                                    json={"title": "trading-agent cycle"})
                created.raise_for_status()
                session_id = created.json()["id"]
                try:
                    reply = http.post(
                        f"{base}/session/{session_id}/message",
                        json={"parts": [{"type": "text",
                                         "text": _build_prompt(payload)}]},
                    )
                    reply.raise_for_status()
                    return _extract_text(reply.json())
                finally:
                    # Always clean up, including on failure: an abandoned
                    # session per failed cycle would accumulate silently.
                    try:
                        http.delete(f"{base}/session/{session_id}")
                    except Exception:  # noqa: BLE001
                        pass

        return cls(transport, url=config.opencode_url)

    def ask(self, prompt: str, *, timeout: float | None = None) -> str:
        """One prose question, one prose answer.

        Used for research briefs and follow-ups, where the reader is the
        operator rather than the guardrail. Returns "" on any failure: a brief
        the model could not produce is a question asked without one, which is
        worse but survivable. Nothing here reaches an order.
        """
        try:
            payload = {"prompt": prompt}
            if timeout is not None:
                payload["timeout"] = timeout
            return (self._transport(payload) or "").strip()
        except Exception:  # noqa: BLE001 — never raise into the question path
            return ""

    def propose(self, *, catalysts, positions) -> list[Proposal]:
        payload = {"catalysts": catalysts, "positions": positions}
        try:
            raw = self._transport(payload)
        except Exception as exc:  # noqa: BLE001 — every failure is fail-closed
            raise ReasoningUnavailable(f"backend unreachable: {exc}") from exc

        try:
            data = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ReasoningUnavailable(f"unparseable response: {exc}") from exc

        if not isinstance(data, dict) or "proposals" not in data:
            raise ReasoningUnavailable("response missing 'proposals'")
        items = data["proposals"]
        if not isinstance(items, list):
            raise ReasoningUnavailable("'proposals' is not a list")

        out: list[Proposal] = []
        for item in items:
            try:
                out.append(Proposal(
                    symbol=str(item["symbol"]).strip().upper(),
                    side=str(item["side"]).strip().lower(),
                    notional_usd=float(item["notional_usd"]),
                    rationale=str(item.get("rationale", "")),
                    correlation_id=str(item.get("correlation_id", "")),
                ))
            except (KeyError, TypeError, ValueError) as exc:
                # Reject the batch rather than the item: a malformed response
                # suggests a confused model, and cherry-picking the parseable
                # half of a confused answer is how you trade on nonsense.
                raise ReasoningUnavailable(f"malformed proposal {item!r}: {exc}") from exc
        return out


def proposals_or_none(client: ReasoningClient, **kwargs):
    """Loop-facing wrapper. None means do nothing — never a default trade."""
    try:
        return client.propose(**kwargs)
    except ReasoningUnavailable:
        return None


# The model is asked for a decision, not for prose. Anything it returns that is
# not the expected shape is rejected upstream rather than interpreted.
_PROMPT = """You are the reasoning step of an automated biotech trading agent.

Upcoming catalysts (clinical trial readouts and news):
{catalysts}

Current positions:
{positions}

Propose zero or more trades. Prefer proposing nothing over proposing something
speculative: a missed opportunity costs nothing, a bad trade costs money.

Reply with ONLY this JSON, no prose, no code fences:
{{"proposals": [{{"symbol": "TICKER", "side": "buy", "notional_usd": 100,
"rationale": "one sentence"}}]}}

An empty list is a valid and often correct answer."""


def _build_prompt(payload: dict) -> str:
    # A prose question goes through verbatim. The trading prompt exists to pin
    # the model to a JSON contract; a research brief or a follow-up answer is
    # meant to be read by a person, and wrapping it in that contract would ask
    # for the wrong thing entirely.
    if "prompt" in payload:
        return str(payload["prompt"])
    cats = payload.get("catalysts") or []
    pos = payload.get("positions") or []
    return _PROMPT.format(
        catalysts="\n".join(f"- {c}" for c in cats) or "(none)",
        positions="\n".join(f"- {p}" for p in pos) or "(none)",
    )


def _extract_text(reply: dict) -> str:
    """Pull the assistant's text out of an opencode reply.

    The shape has moved between versions, so this checks the known places
    rather than assuming one — and returns '' when it finds nothing, which the
    caller treats as unusable rather than as an empty proposal list.
    """
    parts = reply.get("parts") or reply.get("info", {}).get("parts") or []
    texts = [p.get("text", "") for p in parts if p.get("type") == "text"]
    return texts[-1].strip() if texts else ""
