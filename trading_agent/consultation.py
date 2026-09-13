"""Asking the operator for a view, and understanding the answer.

This is what Telegram is here for. The whole thing has to survive being
answered one-handed on a phone between other tasks, so the format is
deliberately crude: yes / no / skip, an optional 1-5 confidence, and any
remaining words kept as a note.

The one rule that matters: an answer that cannot be understood is not a view.
Confusion must never become consent.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

from trading_agent.events import Event, Materiality, worth_researching

_POSITIVE = {"yes", "y", "positive", "pos", "success", "succeed", "hit", "good"}
_NEGATIVE = {"no", "n", "negative", "neg", "fail", "miss", "bad"}
_SKIP = {"skip", "pass", "dunno", "idk", "unsure", "no_opinion", "noview"}

DEFAULT_CONFIDENCE = 3  # an unstated confidence is not certainty


@dataclass(frozen=True)
class Reply:
    stance: str
    confidence: int
    note: str


def build_question(event: Event, *, digest: str = "") -> str:
    """One message, everything needed to answer it, no follow-up required."""
    lines = [
        f"**{event.symbol}** — {event.title}",
        f"trial: {event.trial_id}" if event.trial_id else "",
        f"expected: {event.date}" if event.date else "",
        "",
    ]
    if digest:
        lines += [digest.strip(), ""]
    lines += [
        "Will this read out positively?",
        "Start with *yes*, *no* or *skip*, then a 1-5 confidence, then say "
        "whatever you like — dictate as long an answer as you want, it is all "
        "kept with the view.",
        "e.g. `yes 4.5 mechanism is derisked by the phase 2 and Merck sharing "
        "the risk matters here`",
    ]
    return "\n".join(line for line in lines if line != "" or True).strip()


def parse_reply(text: str) -> Reply | None:
    """Parse an operator reply. Returns None when it cannot be understood."""
    words = (text or "").strip().split()
    if not words:
        return None

    head = words[0].lower().strip(".,!?")
    if head in _POSITIVE:
        stance = "positive"
    elif head in _NEGATIVE:
        stance = "negative"
    elif head in _SKIP:
        return Reply("no_opinion", 0, " ".join(words[1:]))
    else:
        # Deliberately not guessing. An unrecognised reply gets asked again
        # rather than being interpreted into a position.
        return None

    confidence = DEFAULT_CONFIDENCE
    rest = words[1:]
    if rest and re.fullmatch(r"[0-9]+(?:[.,][0-9]+)?", rest[0]):
        # Decimals are accepted because people actually type them: the first
        # real reply to this system was "Yes 4.5 ...", which an integer-only
        # match silently dropped to the default and buried in the note.
        # Comma decimals too — the operator's locale is French.
        raw = float(rest[0].replace(",", "."))
        # Round half UP rather than to even: 4.5 reads as "more than 4", and
        # banker's rounding would quietly record it as less.
        confidence = max(1, min(5, int(raw + 0.5)))
        rest = rest[1:]

    return Reply(stance, confidence, " ".join(rest))


def pending_questions(events, *, views, now: dt.datetime,
                      threshold: Materiality = Materiality.MEDIUM) -> list[Event]:
    """Which events are worth the operator's attention right now.

    Two filters: skip what is not their edge to judge, and skip what they have
    already judged. A HIGH event still gets asked despite an existing view,
    because an amendment can invalidate an earlier read.
    """
    out: list[Event] = []
    for event in events:
        if not event.is_scoreable:
            continue
        has_view = views.for_event(event.symbol, event.view_key, now=now) is not None
        if worth_researching(event, has_view=has_view, threshold=threshold):
            out.append(event)
    return out
