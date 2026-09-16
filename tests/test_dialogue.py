"""The conversation with the operator, end to end without a network.

This is the layer that was missing entirely: every piece of it existed and was
tested, and nothing connected them, so the agent could find a readout, propose
a trade, and then refuse itself forever for want of a view it never asked for.
"""
from __future__ import annotations

import datetime as dt

from trading_agent.audit import AuditLog
from trading_agent.catalysts import Catalyst
from trading_agent.dialogue import ask_next, handle_reply, to_events
from trading_agent.events import EventKind
from trading_agent.state import State
from trading_agent.views import ViewStore

NOW = dt.datetime(2026, 9, 11, 15, 0, tzinfo=dt.timezone.utc)

TRIAL = Catalyst(symbol="BMRN", title="Phase 3 VOXZOGO in hypochondroplasia",
                 date="2026-10-01", source="clinicaltrials.gov",
                 url="https://clinicaltrials.gov/study/NCT04265651",
                 phase="PHASE3")
NEWS = Catalyst(symbol="MRNA", title="Moderna names a new CFO",
                date="2026-09-11", source="alpaca-news", url="http://x")


class Tg:
    def __init__(self, ok=True):
        self.sent = []
        self.ok = ok

    def send(self, text):
        self.sent.append(text)
        return self.ok


class Reasoner:
    def __init__(self, answer="a brief"):
        self.answer = answer
        self.prompts = []

    def ask(self, prompt, **kwargs):
        self.prompts.append(prompt)
        return self.answer


def _kit(tmp_path):
    return dict(views=ViewStore(tmp_path / "v.db"),
                state=State(tmp_path / "s.db"),
                telegram=Tg(), reasoner=Reasoner(),
                audit=AuditLog(tmp_path / "a.log"), now=NOW)


# --- catalysts become the right kind of event -------------------------------

def test_a_registry_entry_is_a_readout_and_carries_its_trial_id():
    event = to_events([TRIAL])[0]
    assert event.kind == EventKind.TRIAL_READOUT
    assert event.trial_id == "NCT04265651"
    assert event.is_scoreable


def test_a_headline_is_not_a_readout():
    """Asking about every headline is how you train someone to stop reading
    the questions."""
    event = to_events([NEWS])[0]
    assert event.kind == EventKind.NEWS
    assert not event.is_scoreable


# --- asking ------------------------------------------------------------------

def test_a_readout_produces_a_question_with_a_brief(tmp_path):
    kit = _kit(tmp_path)
    key = ask_next(to_events([TRIAL]), **kit)

    assert key == "NCT04265651"
    assert len(kit["telegram"].sent) == 1
    message = kit["telegram"].sent[0]
    assert "BMRN" in message and "a brief" in message
    assert kit["state"].open_thread()["symbol"] == "BMRN"


def test_news_alone_produces_no_question(tmp_path):
    kit = _kit(tmp_path)
    assert ask_next(to_events([NEWS]), **kit) == ""
    assert kit["telegram"].sent == []


def test_only_one_question_is_open_at_a_time(tmp_path):
    """A reply that silently lands on the wrong trial is worse than a question
    never asked."""
    kit = _kit(tmp_path)
    other = Catalyst(symbol="VRTX", title="Phase 3 readout", date="2026-09-20",
                     source="clinicaltrials.gov",
                     url="https://clinicaltrials.gov/study/NCT99999999")
    ask_next(to_events([TRIAL, other]), **kit)
    ask_next(to_events([TRIAL, other]), **kit)
    assert len(kit["telegram"].sent) == 1


def test_a_question_that_could_not_be_sent_leaves_no_thread_open(tmp_path):
    """Unsent means unasked: the next cycle must try again rather than wait
    forever for an answer to a question that never arrived."""
    kit = _kit(tmp_path)
    kit["telegram"] = Tg(ok=False)
    assert ask_next(to_events([TRIAL]), **kit) == ""
    assert kit["state"].open_thread() is None


def test_an_answered_event_is_not_asked_again(tmp_path):
    kit = _kit(tmp_path)
    ask_next(to_events([TRIAL]), **kit)
    handle_reply("yes 4", **_reply_kit(kit))
    ask_next(to_events([TRIAL]), **kit)
    assert len(kit["telegram"].sent) == 2, "question, acknowledgement, nothing more"


def _reply_kit(kit):
    return dict(views=kit["views"], state=kit["state"], telegram=kit["telegram"],
                reasoner=kit["reasoner"], audit=kit["audit"], now=kit["now"])


# --- answering ---------------------------------------------------------------

def test_an_answer_becomes_a_view_that_licenses_the_trade(tmp_path):
    kit = _kit(tmp_path)
    ask_next(to_events([TRIAL]), **kit)

    assert handle_reply("yes 4.5 mechanism is derisked", **_reply_kit(kit)) == "view"
    view = kit["views"].for_symbol("BMRN", now=NOW)
    assert view.stance == "positive" and view.confidence == 5
    assert "derisked" in view.note
    assert view.is_actionable
    assert kit["state"].open_thread() is None


def test_a_view_is_found_by_symbol_although_it_was_filed_by_trial(tmp_path):
    """The operator judges the trial; the trade is in the stock. Keying the
    gate on the ticker alone would refuse a trade they had already licensed."""
    kit = _kit(tmp_path)
    ask_next(to_events([TRIAL]), **kit)
    handle_reply("yes 4", **_reply_kit(kit))

    assert kit["views"].for_event("BMRN", "NCT04265651", now=NOW) is not None
    assert kit["views"].for_symbol("BMRN", now=NOW) is not None


def test_an_unreadable_answer_is_not_a_view(tmp_path):
    """Confusion must never become consent."""
    kit = _kit(tmp_path)
    ask_next(to_events([TRIAL]), **kit)

    assert handle_reply("hmm maybe later", **_reply_kit(kit)) == "unparsed"
    assert kit["views"].for_symbol("BMRN", now=NOW) is None
    assert kit["state"].open_thread() is not None, "the question stays open"


def test_skip_records_a_view_that_does_not_license_a_trade(tmp_path):
    kit = _kit(tmp_path)
    ask_next(to_events([TRIAL]), **kit)
    handle_reply("skip", **_reply_kit(kit))

    view = kit["views"].for_symbol("BMRN", now=NOW)
    assert view is not None and not view.is_actionable


def test_a_follow_up_question_is_answered_and_keeps_the_thread_open(tmp_path):
    """The operator asking two questions before forming a view is the entire
    point of having them in the loop."""
    kit = _kit(tmp_path)
    ask_next(to_events([TRIAL]), **kit)
    kit["reasoner"].answer = "The phase 2 used the same endpoint."

    assert handle_reply("what was the phase 2 endpoint?",
                        **_reply_kit(kit)) == "question"
    assert "phase 2 used the same endpoint" in kit["telegram"].sent[-1]
    assert kit["state"].open_thread() is not None
    assert kit["views"].for_symbol("BMRN", now=NOW) is None


def test_a_message_with_no_open_question_records_nothing(tmp_path):
    kit = _kit(tmp_path)
    assert handle_reply("yes 5", **_reply_kit(kit)) == "ignored"
    assert kit["views"].for_symbol("BMRN", now=NOW) is None


def test_a_view_expires_rather_than_becoming_a_standing_licence(tmp_path):
    kit = _kit(tmp_path)
    ask_next(to_events([TRIAL]), **kit)
    handle_reply("yes 5", **_reply_kit(kit))

    later = NOW + dt.timedelta(days=200)
    assert kit["views"].for_symbol("BMRN", now=later) is None


def test_the_reasoner_the_dialogue_needs_is_the_one_production_builds():
    """research() and the follow-up path call reasoner.ask(). It did not
    exist: every brief failed silently and went out empty, and every follow-up
    would have died in the same place."""
    from trading_agent.reasoning import ReasoningClient

    assert hasattr(ReasoningClient, "ask")


def test_the_question_names_the_company_not_only_the_ticker():
    """"ABBV" is not a company to anyone reading this on a phone."""
    from trading_agent.consultation import build_question

    class U:
        def company_name(self, symbol):
            return "AbbVie"

    event = to_events([TRIAL], universe=U())[0]
    assert event.company == "AbbVie"
    assert "AbbVie (BMRN)" in build_question(event) or "AbbVie" in build_question(event)


def test_a_universe_that_cannot_name_the_company_still_produces_a_question():
    class U:
        def company_name(self, symbol):
            raise OSError("offline")

    event = to_events([TRIAL], universe=U())[0]
    assert event.company == "" and event.symbol == "BMRN"


# --- the operator's real two-trial reply, and changing an answer later ------

def test_the_real_two_trial_reply_records_the_open_one_and_answers_its_question(tmp_path):
    """Replays the shape of the message that recorded nothing: two prefixed
    answers, the second ending in "...?". BMRN stands in for the open trial."""
    kit = _kit(tmp_path)
    ask_next(to_events([TRIAL]), **kit)
    kit["reasoner"].answer = "The comparator is standard of care."

    msg = ("MYGN : no, 2, distrust changes in CT protocol\n"
           "BMRN : yes, 1, CT design is sound and inefficacious comparator...?")
    assert handle_reply(msg, **_reply_kit(kit)) == "view"

    view = kit["views"].for_symbol("BMRN", now=NOW)
    assert view.stance == "positive" and view.confidence == 1
    assert "inefficacious comparator" in view.note
    assert kit["views"].for_symbol("MYGN", now=NOW) is None

    sent = "\n".join(kit["telegram"].sent)
    assert "no question about MYGN" in sent
    assert "Recorded for BMRN" in sent
    assert "The comparator is standard of care." in sent  # the "?" got answered


def test_an_answer_can_be_changed_before_the_results(tmp_path):
    kit = _kit(tmp_path)
    ask_next(to_events([TRIAL]), **kit)
    handle_reply("yes 4 strong mechanism", **_reply_kit(kit))

    assert handle_reply("BMRN: no 2 the interim data worried me",
                        **_reply_kit(kit)) == "view"
    view = kit["views"].for_symbol("BMRN", now=NOW)
    assert view.stance == "negative" and view.confidence == 2
    assert "Updated for BMRN" in kit["telegram"].sent[-1]


def test_an_answer_cannot_change_once_the_result_is_known(tmp_path):
    """Otherwise the scoreboard measures hindsight."""
    kit = _kit(tmp_path)
    ask_next(to_events([TRIAL]), **kit)
    handle_reply("yes 4", **_reply_kit(kit))
    kit["views"].record_outcome("BMRN", "NCT04265651", "positive", NOW)

    assert handle_reply("BMRN: no 5", **_reply_kit(kit)) == "ignored"
    assert kit["views"].for_symbol("BMRN", now=NOW).stance == "positive"


def test_an_answer_with_nothing_waiting_explains_how_to_change_one(tmp_path):
    kit = _kit(tmp_path)
    assert handle_reply("yes 3", **_reply_kit(kit)) == "ignored"
    assert "start with the ticker" in kit["telegram"].sent[-1]


# --- watching the registry for changes to a trial already judged ------------

def _study(outcome="Overall survival", status="RECRUITING", enrollment=400,
           date="2026-10-01", phases=("PHASE3",)):
    return {"protocolSection": {
        "identificationModule": {"nctId": "NCT04265651", "briefTitle": "Phase 3"},
        "designModule": {"phases": list(phases),
                         "enrollmentInfo": {"count": enrollment}},
        "statusModule": {"overallStatus": status,
                         "primaryCompletionDateStruct": {"date": date}},
        "outcomesModule": {"primaryOutcomes": [{"measure": outcome}]},
    }}


def _watch_kit(tmp_path):
    from trading_agent.state import State
    from trading_agent.trial_watch import TrialWatcher

    state = State(tmp_path / "s.db")
    state.open_thread_for("NCT04265651", "BMRN", "Phase 3 VOXZOGO", NOW)
    state.close_thread()
    return {"watcher": TrialWatcher(tmp_path / "t.db"), "state": state,
            "telegram": Tg(), "audit": AuditLog(tmp_path / "a.log"), "now": NOW}


def test_the_first_look_at_a_trial_is_only_a_baseline(tmp_path):
    """There is nothing to compare against yet, and a message saying a trial
    changed the moment it is first seen would be false."""
    from trading_agent.dialogue import watch_registry

    kit = _watch_kit(tmp_path)
    assert watch_registry(fetch_study=lambda _n: _study(), **kit) == {}
    assert kit["telegram"].sent == []


def test_a_changed_endpoint_reopens_the_question(tmp_path):
    """What the trial measures is what the operator judged. Change it and the
    old answer is about a different trial."""
    from trading_agent.dialogue import watch_registry

    kit = _watch_kit(tmp_path)
    watch_registry(fetch_study=lambda _n: _study(), **kit)
    found = watch_registry(fetch_study=lambda _n: _study(outcome="Response rate"),
                           **kit)

    assert "NCT04265651" in found
    assert "BMRN" in kit["telegram"].sent[-1]
    assert "ask you about it again" in kit["telegram"].sent[-1]
    assert not kit["state"].was_asked("NCT04265651")


def test_a_trial_that_terminates_reopens_the_question(tmp_path):
    from trading_agent.dialogue import watch_registry

    kit = _watch_kit(tmp_path)
    watch_registry(fetch_study=lambda _n: _study(), **kit)
    watch_registry(fetch_study=lambda _n: _study(status="TERMINATED"), **kit)
    assert not kit["state"].was_asked("NCT04265651")


def test_a_smaller_or_later_trial_is_reported_without_re_asking(tmp_path):
    """Worth knowing, not worth re-asking unprompted: the operator can change
    their answer if it matters to them."""
    from trading_agent.dialogue import watch_registry

    kit = _watch_kit(tmp_path)
    watch_registry(fetch_study=lambda _n: _study(), **kit)
    watch_registry(fetch_study=lambda _n: _study(enrollment=250,
                                                 date="2027-03-01"), **kit)

    message = kit["telegram"].sent[-1]
    assert "enrollment" in message or "250" in message
    assert "Your answer stands" in message
    assert kit["state"].was_asked("NCT04265651")


def test_an_unchanged_trial_says_nothing(tmp_path):
    from trading_agent.dialogue import watch_registry

    kit = _watch_kit(tmp_path)
    watch_registry(fetch_study=lambda _n: _study(), **kit)
    assert watch_registry(fetch_study=lambda _n: _study(), **kit) == {}
    assert kit["telegram"].sent == []


def test_one_unreachable_trial_does_not_end_the_sweep(tmp_path):
    from trading_agent.dialogue import watch_registry

    kit = _watch_kit(tmp_path)

    def boom(_nct):
        raise OSError("registry down")

    assert watch_registry(fetch_study=boom, **kit) == {}
    assert any(e["event"] == "registry_check_failed" for e in kit["audit"].entries())
