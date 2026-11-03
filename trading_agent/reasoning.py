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

        # OpenCode V2 uses a fixed HTTP Basic username.  Keep the configuration
        # field for older environment files, but do not let an old "lion" value
        # make a V2 request authenticate as the wrong user.
        auth = ("opencode", config.opencode_password)
        base = config.opencode_url.rstrip("/")

        def transport(payload: dict) -> str:
            # The caller sets this for prose; proposals keep the default.
            timeout = float(payload.get("timeout") or 180.0)
            with httpx.Client(auth=auth, timeout=timeout) as http:
                return _request_v2_reply(http, base, _build_prompt(payload))

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


def _request_v2_reply(http, base: str, prompt: str) -> str:
    """Send one request through the V2 API and return its final text.

    V2 prompt delivery is asynchronous.  Waiting for the session to settle
    before reading its messages prevents a trading cycle from treating an
    accepted inbox item as an answer.  Each temporary session is deleted even
    when any V2 request fails.
    """
    created = http.post(f"{base}/api/session", json={"title": "trading-agent cycle"})
    created.raise_for_status()
    data = created.json().get("data") or {}
    session_id = data["id"]
    try:
        submitted = http.post(
            f"{base}/api/session/{session_id}/prompt",
            json={"text": prompt},
        )
        submitted.raise_for_status()

        settled = http.post(f"{base}/api/experimental/session/{session_id}/wait")
        settled.raise_for_status()

        messages = http.get(f"{base}/api/session/{session_id}/message")
        messages.raise_for_status()
        return _extract_text(messages.json())
    finally:
        # A cycle gets a fresh session by design. Do not leave either failed or
        # successful cycles in the server's history.
        try:
            http.delete(f"{base}/api/session/{session_id}")
        except Exception:  # noqa: BLE001
            pass


def _extract_text(reply: dict) -> str:
    """Pull the assistant's text out of an opencode reply.

    V2 returns a ``data`` list of messages with assistant ``content`` parts.
    Accept the historic shapes too, so this parsing boundary remains defensive.
    It returns '' when it finds nothing, which the caller treats as unusable
    rather than as an empty proposal list.
    """
    messages = reply.get("data")
    if isinstance(messages, list):
        for message in reversed(messages):
            if message.get("type") != "assistant":
                continue
            texts = [part.get("text", "") for part in message.get("content", [])
                     if part.get("type") == "text"]
            if texts:
                return texts[-1].strip()

    parts = reply.get("parts") or reply.get("info", {}).get("parts") or []
    texts = [part.get("text", "") for part in parts if part.get("type") == "text"]
    return texts[-1].strip() if texts else ""
