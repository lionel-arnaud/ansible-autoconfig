"""The consultation session: asking for views, and parsing the replies.

This is the part the operator actually wanted Telegram for. It must be easy to
answer from a phone, tolerant of imprecise replies, and it must never read
silence or confusion as consent.
"""
from __future__ import annotations

import datetime as dt

from trading_agent.consultation import (
    build_question,
    parse_reply,
    pending_questions,
)
from trading_agent.events import Event, EventKind
from trading_agent.views import View, ViewStore

NOW = dt.datetime(2026, 9, 11, 12, 0, tzinfo=dt.timezone.utc)


def ev(kind=EventKind.TRIAL_READOUT, trial="NCT123"):
    return Event("MRNA", kind, "Phase 3 readout in NSCLC", trial_id=trial,
                 date="2026-10-01")


def test_a_question_names_the_event_and_how_to_answer(tmp_path):
    q = build_question(ev(), digest="Pipeline is single-asset; CEO ex-Genentech.")
    assert "MRNA" in q and "NCT123" in q
    assert "Pipeline is single-asset" in q, "the digest must reach the question"
    # Answering from a phone has to be trivial or it will not happen.
    for token in ("yes", "no", "skip"):
        assert token in q.lower()


def test_plain_answers_are_understood():
    assert parse_reply("yes").stance == "positive"
    assert parse_reply("no").stance == "negative"
    assert parse_reply("skip").stance == "no_opinion"


def test_confidence_is_optional_and_parsed_when_given():
    assert parse_reply("yes 5").confidence == 5
    assert parse_reply("no 2").confidence == 2
    # Unstated confidence must not become certainty.
    assert parse_reply("yes").confidence == 3


def test_free_text_is_kept_as_the_note():
    r = parse_reply("yes 4 mechanism is derisked by the phase 2")
    assert r.stance == "positive" and r.confidence == 4
    assert "mechanism is derisked" in r.note


def test_an_unparseable_reply_is_not_a_view():
    """Confusion must never become consent. Better to ask again."""
    for junk in ("maybe?", "", "what do you think", "🤷"):
        assert parse_reply(junk) is None


def test_confidence_out_of_range_is_clamped_not_rejected():
    """A fat-fingered 9 should not throw away a real opinion."""
    assert parse_reply("yes 9").confidence == 5
    assert parse_reply("yes 0").confidence == 1


def test_only_unanswered_material_events_are_asked_about(tmp_path):
    """Two filters at once: do not ask about noise, do not ask twice."""
    vs = ViewStore(tmp_path / "v.db")
    vs.record(View("MRNA", "NCT_ANSWERED", "positive", 4, "r", NOW))
    events = [
        ev(trial="NCT_ANSWERED"),                       # already judged
        ev(trial="NCT_NEW"),                            # worth asking
        ev(kind=EventKind.EARNINGS, trial=""),          # not the operator's edge
    ]
    out = pending_questions(events, views=vs, now=NOW)
    assert [e.trial_id for e in out] == ["NCT_NEW"]


def test_a_high_materiality_event_is_asked_again_despite_a_view(tmp_path):
    """An amendment can invalidate an earlier read, so it is worth re-asking."""
    vs = ViewStore(tmp_path / "v.db")
    vs.record(View("MRNA", "NCT123", "positive", 4, "r", NOW))
    out = pending_questions([ev(kind=EventKind.TRIAL_AMENDMENT)], views=vs, now=NOW)
    assert len(out) == 1


# --- regression: found by the first real reply -------------------------------

def test_decimal_confidence_is_parsed():
    """The first real reply to this system was "Yes 4.5 ..." and the original
    integer-only match silently recorded it as the default 3, burying the 4.5
    in the note."""
    r = parse_reply("Yes 4.5 I have strong positive opinions of mRNA vaccines")
    assert r.stance == "positive"
    assert r.confidence == 5, "4.5 rounds up: it reads as more than 4"
    assert "4.5" not in r.note, "the confidence must not leak into the note"
    assert "strong positive opinions" in r.note


def test_comma_decimals_are_accepted():
    """The operator's locale is French; dictation produces commas."""
    assert parse_reply("yes 4,5 solid data").confidence == 5


def test_a_long_dictated_reply_keeps_all_of_it():
    """Dictation produces sentences, not tokens. Nothing may be discarded."""
    spoken = ("yes 4 the phase two data was strong and the partnership with "
              "Merck means the commercial risk is shared which matters for a "
              "company with a single pivotal asset")
    r = parse_reply(spoken)
    assert r.stance == "positive" and r.confidence == 4
    assert "single pivotal asset" in r.note


def test_rounding_is_half_up_not_bankers():
    assert parse_reply("yes 2.5 x").confidence == 3
    assert parse_reply("yes 3.5 x").confidence == 4
