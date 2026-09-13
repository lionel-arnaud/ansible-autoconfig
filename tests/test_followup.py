"""Follow-up questions — and the rule that they cannot move money."""
from __future__ import annotations

from trading_agent.followup import (
    Thread,
    build_followup_prompt,
    looks_like_a_question,
    route,
)

T = Thread(event_key="NCT05933577", symbol="MRNA")


def test_questions_are_recognised():
    for q in ("what is the powering?", "why did they change the endpoint",
              "tell me more about the CEO", "can you explain the comparator",
              "How derisked is this really?"):
        assert looks_like_a_question(q), q


def test_answers_are_not_mistaken_for_questions():
    for a in ("yes 4 strong mechanism", "no, the comparator is too weak",
              "skip", "yes 5 I know this team well"):
        assert not looks_like_a_question(a), a


def test_an_ambiguous_message_is_treated_as_a_question_not_a_view():
    """Asymmetric on purpose: an answer misread as a question gets asked back,
    but a question misread as an answer would record a view never given."""
    assert route("could you say more", thread=T)[0] == "question"


def test_nothing_is_routed_without_an_open_thread():
    assert route("what about the endpoint?", thread=None)[0] == "ignore"


def test_empty_messages_are_ignored():
    assert route("   ", thread=T)[0] == "ignore"


def test_the_prompt_forbids_bluffing():
    """A confident guess here becomes an input to a real trading decision."""
    p = " ".join(build_followup_prompt(T, "what is the powering?").split())
    assert "do not know, say so" in p
    assert "costs money" in p


def test_the_prompt_carries_the_question_and_the_context():
    p = build_followup_prompt(T, "why change the endpoint?", "Phase 3 melanoma")
    assert "why change the endpoint?" in p
    assert "MRNA" in p and "Phase 3 melanoma" in p


def test_followups_cannot_place_trades():
    """Structural: nothing in this module can reach the broker or the guardrail.
    Positions change only through a recorded view."""
    import pathlib

    src = pathlib.Path("trading_agent/followup.py").read_text()
    for forbidden in ("broker", "submit", "OrderIntent", "evaluate("):
        assert forbidden not in src, f"followup must not reference {forbidden}"
