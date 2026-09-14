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
    # Whether a number was actually given. A reply that also contains a
    # question mark only counts as an answer when it is this committed.
    explicit_confidence: bool = False


_STANCE_WORDS = _POSITIVE | _NEGATIVE | _SKIP
_MONTHS = ("January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December")


def _readable_date(raw: str) -> str:
    """2026-09-30 -> 30 September 2026. Anything else is returned untouched."""
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", (raw or "").strip())
    if not m:
        return raw
    year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if not 1 <= month <= 12:
        return raw
    return f"{day} {_MONTHS[month - 1]} {year}"


def build_question(event: Event, *, digest: str = "") -> str:
    """One message, everything needed to answer it, no follow-up required.

    Written for a phone and for someone who has not looked at the trial before:
    the operator said the first versions were cryptic, full of acronyms, and
    did not even name the company.
    """
    who = f"{event.company} ({event.symbol})" if event.company else event.symbol
    lines = [f"New question: {who}", f"Trial: {event.title}"]
    if event.date:
        lines.append(f"Results expected around {_readable_date(event.date)}")
    if event.trial_id:
        lines.append(f"Registry page: https://clinicaltrials.gov/study/{event.trial_id}")
    lines.append("")
    if digest:
        lines += [digest.strip(), ""]
    lines += [
        "Your call: will this trial succeed?",
        "Reply with yes, no or skip, then how sure you are from 1 (a hunch) to "
        "5 (very confident), then any reasoning you like. Dictate freely, it is "
        "all kept.",
        f"Example: {event.symbol}: yes 3 earlier results were solid but the trial is small",
        "",
        f"Starting with {event.symbol}: is optional, but it lets you answer "
        "several questions in one message, or change this answer later, until "
        "the results are out.",
        "Want to know more first? Ask anything, ending with a question mark.",
    ]
    return "\n".join(lines).strip()


def parse_reply(text: str) -> Reply | None:
    """Parse an operator reply. Returns None when it cannot be understood."""
    words = (text or "").strip().split()
    if not words:
        return None

    head = words[0].lower().strip(".,!?:;")
    if head in _POSITIVE:
        stance = "positive"
    elif head in _NEGATIVE:
        stance = "negative"
    elif head in _SKIP:
        return Reply("no_opinion", 0, _clean_note(words[1:]))
    else:
        # Deliberately not guessing. An unrecognised reply gets asked again
        # rather than being interpreted into a position.
        return None

    confidence = DEFAULT_CONFIDENCE
    explicit = False
    rest = words[1:]
    # Trailing punctuation stripped first. Dictated replies come out as
    # "yes, 1, the design is sound", and the "1," used to fail the match, fall
    # back to the default and bury the real number in the note.
    token = rest[0].rstrip(",;:.") if rest else ""
    m = re.fullmatch(r"([0-9]+(?:[.,][0-9]+)?)(?:/5)?", token)
    if m:
        # Decimals are accepted because people actually type them: the first
        # real reply to this system was "Yes 4.5 ...", which an integer-only
        # match silently dropped to the default and buried in the note.
        # Comma decimals too — the operator's locale is French.
        raw = float(m.group(1).replace(",", "."))
        # Round half UP rather than to even: 4.5 reads as "more than 4", and
        # banker's rounding would quietly record it as less.
        confidence = max(1, min(5, int(raw + 0.5)))
        explicit = True
        rest = rest[1:]

    return Reply(stance, confidence, _clean_note(rest), explicit)


def _clean_note(words) -> str:
    return " ".join(words).strip().lstrip(",;:-").strip()


def is_answer(text: str) -> bool:
    """Is this message a view, rather than a question?

    A reply starting with yes/no/skip is an answer, even when it contains a
    question mark: the operator's first two-trial reply ended its note with
    "...?" and the whole message was treated as a question, so neither view was
    recorded. But "no idea what the endpoint is?" also starts with "no", so a
    question mark requires a committed confidence number before a message
    counts. The costs are asymmetric: an answer misread as a question gets
    asked back, a question misread as an answer records a view never given.
    """
    reply = parse_reply(text)
    if reply is None:
        return False
    if "?" not in (text or ""):
        return True
    return reply.stance == "no_opinion" or reply.explicit_confidence


_PREFIX = re.compile(r"^\s*\$?([A-Za-z]{1,5})\s*[:\-–—]\s*(\S.*)$")


def _starts_with_stance(text: str) -> bool:
    words = (text or "").strip().split()
    return bool(words) and words[0].lower().strip(".,!?:;") in _STANCE_WORDS


def split_answers(text: str) -> list[tuple[str | None, str]]:
    """Split one message into per-trial answers.

    "MYGN: no 2 distrust the protocol change" on one line and "IBRX: yes 1 ..."
    on the next is how the operator actually replies when two questions are
    waiting. A line counts as a new answer only when it starts with a ticker
    and the rest starts with yes/no/skip; any other line continues the one
    before, so a long dictated note that wraps is kept whole.
    """
    items: list[list] = []
    for line in (text or "").splitlines():
        if not line.strip():
            continue
        m = _PREFIX.match(line)
        if (m and m.group(1).lower() not in _STANCE_WORDS
                and _starts_with_stance(m.group(2))):
            items.append([m.group(1).upper(), m.group(2).strip()])
        elif items:
            items[-1][1] = f"{items[-1][1]} {line.strip()}"
        else:
            items.append([None, line.strip()])
    return [(symbol, body) for symbol, body in items]


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
