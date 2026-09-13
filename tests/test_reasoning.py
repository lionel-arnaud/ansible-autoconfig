"""The model client, and the rule that matters more than its output.

O-02: reasoning runs through opencode on serverannah, so the Pi now depends on
another host. For a process that can hold positions that is a real failure mode,
so losing the backend must mean "open no new positions" — never a retry into a
trade, never a guess.
"""
from __future__ import annotations

import pytest

from trading_agent.reasoning import (
    ReasoningClient,
    ReasoningUnavailable,
    proposals_or_none,
)


def test_unavailable_backend_raises_rather_than_guessing():
    def boom(_payload):
        raise OSError("connection refused")

    with pytest.raises(ReasoningUnavailable):
        ReasoningClient(transport=boom).propose(catalysts=[], positions=[])


def test_unavailable_backend_yields_no_proposals_not_a_default_trade():
    """The safe-wrapper used by the loop: None means do nothing at all."""
    def boom(_payload):
        raise OSError("connection refused")

    assert proposals_or_none(ReasoningClient(transport=boom), catalysts=[], positions=[]) is None


def test_malformed_response_is_rejected_not_coerced():
    """A model that returns nonsense must not be massaged into an order."""
    for junk in ("not json", '{"unexpected": true}', "[]", '{"proposals": "buy"}'):
        client = ReasoningClient(transport=lambda _p, j=junk: j)
        with pytest.raises(ReasoningUnavailable):
            client.propose(catalysts=[], positions=[])


def test_wellformed_response_is_parsed():
    good = '{"proposals": [{"symbol": "MRNA", "side": "buy", "notional_usd": 100, "rationale": "phase 3 readout"}]}'
    client = ReasoningClient(transport=lambda _p: good)
    out = client.propose(catalysts=[], positions=[])
    assert len(out) == 1 and out[0].symbol == "MRNA"


def test_proposal_is_only_a_proposal():
    """It carries no approval token — it must still pass the guardrail."""
    good = '{"proposals": [{"symbol": "MRNA", "side": "buy", "notional_usd": 100, "rationale": "x"}]}'
    out = ReasoningClient(transport=lambda _p: good).propose(catalysts=[], positions=[])
    assert not out[0].to_intent().is_approved


# --- opencode transport shape ------------------------------------------------

def test_prompt_asks_for_json_only_and_permits_doing_nothing():
    from trading_agent.reasoning import _build_prompt

    text = _build_prompt({"catalysts": ["MRNA | PHASE3 | readout"], "positions": []})
    assert "MRNA" in text
    assert "(none)" in text, "empty positions must render explicitly, not blankly"
    assert "ONLY this JSON" in text
    # The model must be told that proposing nothing is acceptable, or it will
    # feel obliged to produce a trade every cycle.
    assert "empty list is a valid" in text


def test_extract_text_handles_both_reply_shapes():
    from trading_agent.reasoning import _extract_text

    assert _extract_text({"parts": [{"type": "text", "text": "a"}]}) == "a"
    assert _extract_text({"info": {"parts": [{"type": "text", "text": "b"}]}}) == "b"
    # Takes the last text part: opencode emits reasoning parts before the answer.
    assert _extract_text({"parts": [
        {"type": "text", "text": "thinking"},
        {"type": "text", "text": "final"},
    ]}) == "final"


def test_extract_text_returns_empty_when_it_finds_nothing():
    """Empty is treated as unusable upstream, never as 'no proposals'."""
    from trading_agent.reasoning import _extract_text

    assert _extract_text({}) == ""
    assert _extract_text({"parts": [{"type": "tool", "name": "x"}]}) == ""


def test_empty_reply_is_unavailable_not_an_empty_proposal_list():
    from trading_agent.reasoning import ReasoningClient, ReasoningUnavailable
    import pytest

    with pytest.raises(ReasoningUnavailable):
        ReasoningClient(transport=lambda _p: "").propose(catalysts=[], positions=[])


# --- prose questions, for the operator rather than the guardrail -------------

def test_ask_sends_the_prompt_verbatim():
    """The trading prompt pins the model to a JSON contract. A research brief
    is meant to be read by a person, and that contract asks for the wrong
    thing entirely."""
    seen = []

    def transport(payload):
        seen.append(payload)
        return "  a brief  "

    client = ReasoningClient(transport=transport)
    assert client.ask("what happened in the phase 2?") == "a brief"
    assert seen[0]["prompt"] == "what happened in the phase 2?"


def test_ask_degrades_to_nothing_rather_than_raising():
    """research() and the follow-up path both run inside the operator's
    conversation. A raised error there costs the question, not just the brief."""
    def transport(_payload):
        raise OSError("opencode down")

    assert ReasoningClient(transport=transport).ask("anything") == ""


def test_the_prose_path_does_not_go_through_the_json_prompt():
    from trading_agent.reasoning import _build_prompt

    assert _build_prompt({"prompt": "hello"}) == "hello"
    assert "JSON" in _build_prompt({"catalysts": [], "positions": []}).upper()
