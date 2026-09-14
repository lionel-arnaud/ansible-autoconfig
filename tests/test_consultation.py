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


# --- replies as the operator actually dictates them -------------------------

def test_a_confidence_followed_by_a_comma_is_still_the_confidence():
    """Dictation produces "no, 2, distrust the protocol change". The "2," used
    to fail the match, fall back to 3 and bury the real number in the note."""
    from trading_agent.consultation import parse_reply

    r = parse_reply("no, 2, distrust changes in the trial protocol")
    assert r.stance == "negative" and r.confidence == 2 and r.explicit_confidence
    assert r.note == "distrust changes in the trial protocol"


def test_a_confidence_out_of_five_is_understood():
    from trading_agent.consultation import parse_reply

    assert parse_reply("yes 4/5 good team").confidence == 4


def test_a_view_whose_note_ends_in_a_question_mark_is_still_a_view():
    """The operator's real reply: "yes, 1, design is sound and inefficacious
    comparator...?" was routed as a question and never recorded."""
    from trading_agent.consultation import is_answer

    assert is_answer("yes, 1, CT design is sound and inefficacious comparator...?")


def test_a_question_that_happens_to_start_with_no_is_not_a_view():
    """"no idea what the endpoint is?" starts with a stance word. Without a
    committed number it must stay a question."""
    from trading_agent.consultation import is_answer

    assert not is_answer("no idea what the endpoint is?")
    assert is_answer("no 2")  # without a question mark, a bare answer stands


def test_one_message_can_answer_two_trials():
    from trading_agent.consultation import split_answers

    msg = ("MYGN : no, 2, distrust changes in CT protocol\n"
           "IBRX : yes, 1, CT design is sound and inefficacious comparator...?")
    assert split_answers(msg) == [
        ("MYGN", "no, 2, distrust changes in CT protocol"),
        ("IBRX", "yes, 1, CT design is sound and inefficacious comparator...?"),
    ]


def test_a_wrapped_dictated_note_is_not_split_into_answers():
    from trading_agent.consultation import split_answers

    msg = "IBRX: yes 3 the earlier data were solid\nNote: the trial is small\nand old"
    assert split_answers(msg) == [
        ("IBRX", "yes 3 the earlier data were solid Note: the trial is small and old"),
    ]


def test_an_answer_without_a_ticker_is_kept_whole():
    from trading_agent.consultation import split_answers

    assert split_answers("yes 4 strong mechanism") == [(None, "yes 4 strong mechanism")]


def test_the_question_is_readable():
    """Company named, date in words, the registry link, and no markup the
    fallback to plain text would print as stray asterisks."""
    from trading_agent.consultation import build_question
    from trading_agent.events import Event, EventKind

    q = build_question(Event(symbol="IBRX", kind=EventKind.TRIAL_READOUT,
                             title="BCG with ALT-803 in bladder cancer",
                             trial_id="NCT02138734", date="2026-09-30",
                             company="ImmunityBio"))
    assert "ImmunityBio (IBRX)" in q
    assert "30 September 2026" in q
    assert "https://clinicaltrials.gov/study/NCT02138734" in q
    assert "**" not in q
    assert "IBRX: yes" in q  # the example shows the ticker-prefixed form
