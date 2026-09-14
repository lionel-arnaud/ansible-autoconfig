"""The conversation with the operator.

Everything needed to turn a catalyst into a question, and an answer into a
recorded view, lives here. It is the piece that was missing: catalysts,
consultation, research and followup were each built and tested, and nothing
connected them, so the agent could find a readout and propose a trade but had
no way to ask the one person whose judgment the whole design depends on.

The rules it encodes, all of them the operator's:

- Only events worth their attention are asked about. An earnings call is
  recorded, never graded, and never becomes a question.
- A brief comes with the question, so answering needs no research on a phone.
- An unparseable answer is not a view. Confusion must never become consent.
- One open thread at a time: a reply is unambiguous about what it answers.
"""
from __future__ import annotations

import datetime as dt

from trading_agent.consultation import (build_question, is_answer, parse_reply,
                                        pending_questions, split_answers)
from trading_agent.events import Event, EventKind
from trading_agent.followup import Thread, build_followup_prompt, route
from trading_agent.research import research
from trading_agent.views import View

# How long a view on a readout stays good. A read is about that readout; left
# to stand indefinitely it becomes a licence to trade on a months-old opinion.
VIEW_TTL_DAYS = 90


def to_events(catalysts, *, universe=None) -> list[Event]:
    """Catalysts as the consultation layer understands them.

    The source decides the kind, because it decides what the item actually is:
    a registry entry for a late-phase trial is a readout the operator can call,
    and a news headline is not — it is context, and asking about every headline
    is how you train someone to stop reading the questions.
    """
    events: list[Event] = []
    for c in catalysts:
        if c.source == "clinicaltrials.gov":
            kind = EventKind.TRIAL_READOUT
            trial_id = c.url.rsplit("/", 1)[-1] if c.url else ""
        else:
            kind = EventKind.NEWS
            trial_id = ""
        company = ""
        if universe is not None:
            try:
                company = universe.company_name(c.symbol)
            except Exception:  # noqa: BLE001 — a missing name is cosmetic
                company = ""
        events.append(Event(symbol=c.symbol, kind=kind, title=c.title,
                            trial_id=trial_id, date=c.date, url=c.url,
                            company=company))
    return events


def ask_next(events, *, views, state, telegram, reasoner, audit, now,
             correlation_id: str = "") -> str:
    """Ask the operator about the most pressing unanswered event.

    One question at a time. The alternative is a phone full of questions whose
    answers cannot be told apart, and a reply that silently lands on the wrong
    trial is worse than a question never asked.
    """
    if state.open_thread() is not None:
        return ""

    candidates = pending_questions(events, views=views, now=now)
    if not candidates:
        return ""
    # Most material first, then soonest. The operator's attention is the
    # scarcest input in this system.
    event = sorted(candidates,
                   key=lambda e: (-int(e.materiality), e.date or "9999"))[0]
    if state.was_asked(event.view_key):
        return ""

    brief = research(event, reasoner=reasoner)
    audit.record("research", correlation_id, {
        "symbol": event.symbol, "event": event.view_key, "ok": brief.ok,
    })

    if not telegram.send(build_question(event, digest=brief.for_telegram())):
        # Unsent means unasked. Leaving no thread open means the next cycle
        # tries again rather than waiting forever for an answer to a question
        # that never arrived.
        audit.record("question_unsent", correlation_id,
                     {"symbol": event.symbol, "event": event.view_key})
        return ""

    state.open_thread_for(event.view_key, event.symbol, event.title, now)
    audit.record("question_sent", correlation_id, {
        "symbol": event.symbol, "event": event.view_key, "title": event.title,
    })
    return event.view_key


_STANCE_WORDS = {"positive": "yes, it will succeed",
                 "negative": "no, it will not",
                 "no_opinion": "skip, no view"}

_NO_OPEN_QUESTION = (
    "There is no question waiting right now. To change an earlier answer, "
    "start with the ticker, for example: IBRX: no 3 the new data changed my mind"
)


def handle_reply(text, *, views, state, telegram, reasoner, audit, now,
                 correlation_id: str = "") -> str:
    """Route one operator message that was not a command.

    Returns what it was treated as, for the caller to log: "question",
    "view", "unparsed" or "ignored".

    Answers are recognised before questions. The other way round, a view whose
    note ended in "...?" was treated as a question and never recorded.
    """
    if not (text or "").strip():
        return "ignored"

    answers = [(symbol, body) for symbol, body in split_answers(text)
               if is_answer(body)]
    if answers:
        outcomes = [
            _record_answer(symbol, body, views=views, state=state,
                           telegram=telegram, reasoner=reasoner, audit=audit,
                           now=now, correlation_id=correlation_id)
            for symbol, body in answers
        ]
        return "view" if "view" in outcomes else outcomes[0]

    open_thread = state.open_thread()
    if open_thread is None:
        telegram.send(_NO_OPEN_QUESTION)
        return "ignored"

    thread = Thread(event_key=open_thread["event_key"], symbol=open_thread["symbol"])
    kind, payload = route(text, thread=thread)
    if kind == "question":
        # Follow-ups do not close the thread: the operator is allowed to ask
        # several before forming a view, which is the entire point of having
        # them in the loop.
        _answer_followup(thread, payload, open_thread["title"],
                         telegram=telegram, reasoner=reasoner, audit=audit,
                         correlation_id=correlation_id)
        return "question"

    telegram.send(
        "I could not read that as an answer. Start with yes, no or skip, then "
        "a confidence from 1 to 5, then anything you like."
    )
    audit.record("reply_unparsed", correlation_id,
                 {"symbol": thread.symbol, "text": payload[:200]})
    return "unparsed"


def _record_answer(symbol, body, *, views, state, telegram, reasoner, audit,
                   now, correlation_id) -> str:
    reply = parse_reply(body)
    thread = state.thread_for_symbol(symbol) if symbol else state.open_thread()
    if thread is None:
        telegram.send(f"There is no question about {symbol} to answer."
                      if symbol else _NO_OPEN_QUESTION)
        audit.record("reply_unmatched", correlation_id,
                     {"symbol": symbol, "text": body[:200]})
        return "ignored"

    if views.has_outcome(thread["symbol"], thread["event_key"]):
        telegram.send(f"The results for {thread['symbol']} are already known, "
                      "so that answer can no longer change.")
        return "ignored"

    updating = not thread["open"]
    views.record(View(
        symbol=thread["symbol"],
        event_id=thread["event_key"],
        stance=reply.stance,
        confidence=reply.confidence,
        note=reply.note,
        recorded_at=now,
        expires_at=now + dt.timedelta(days=VIEW_TTL_DAYS),
    ))
    if not updating:
        state.close_thread()
    audit.record("view_updated" if updating else "view_recorded", correlation_id, {
        "symbol": thread["symbol"], "event": thread["event_key"],
        "stance": reply.stance, "confidence": reply.confidence,
    })

    verb = "Updated" if updating else "Recorded"
    ack = [f"{verb} for {thread['symbol']}: {_STANCE_WORDS[reply.stance]}"
           + (f", confidence {reply.confidence}/5." if reply.stance != "no_opinion"
              else ".")]
    if reply.note:
        ack.append(f"Your note: {reply.note}")
    ack.append(f"To change it before the results, reply starting with "
               f"{thread['symbol']}:")
    telegram.send("\n".join(ack))

    # A question inside the note is still a question. It gets answered, after
    # the view is safely on file.
    if "?" in reply.note:
        _answer_followup(Thread(event_key=thread["event_key"], symbol=thread["symbol"]),
                         reply.note, thread["title"], telegram=telegram,
                         reasoner=reasoner, audit=audit,
                         correlation_id=correlation_id)
    return "view"


def _answer_followup(thread, question, title, *, telegram, reasoner, audit,
                     correlation_id) -> None:
    answer = reasoner.ask(build_followup_prompt(thread, question, title))
    telegram.send(answer or "(no answer available right now)")
    audit.record("followup", correlation_id,
                 {"symbol": thread.symbol, "question": question[:200]})
