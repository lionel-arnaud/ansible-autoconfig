"""Follow-up questions.

The operator asked how hard this would be. It is not hard, because the pieces
already exist: Telegram polling reads their messages, opencode holds a session,
and the event under discussion is already in the state store. This routes one
to the other and keeps the thread.

The design rule that makes it safe: a follow-up conversation can NEVER place a
trade. It answers questions. Positions change only through a recorded view and
the guardrail, exactly as before — so the chattiest possible conversation still
cannot move money.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

# A reply that is asking rather than answering. Crude on purpose — the cost of
# guessing wrong is small in this direction: an answer misread as a question
# gets asked back, whereas a question misread as an answer would record a view
# the operator never gave.
_QUESTION_HINTS = ("?", "what ", "why ", "how ", "who ", "when ", "which ",
                   "tell me", "explain", "more detail", "more info", "elaborate",
                   "can you", "could you", "any thoughts", "what about")


@dataclass(frozen=True)
class Thread:
    """An open conversation about one event."""
    event_key: str
    symbol: str
    session_id: str = ""
    opened_at: dt.datetime | None = None


def looks_like_a_question(text: str) -> bool:
    low = (text or "").strip().lower()
    if not low:
        return False
    if low.endswith("?") or "?" in low:
        return True
    return any(h in low for h in _QUESTION_HINTS)


FOLLOWUP_PROMPT = """The colleague you briefed has a follow-up about {symbol}
({event}). Answer it directly.

Their question:
{question}

Rules:
- Answer what was asked. Do not re-brief them on things they did not ask about.
- They know the field; skip the primer.
- If you do not know, say so. A confident guess here becomes an input to a real
  trading decision, which is the one place bluffing actually costs money.
- Cite a link where a claim is checkable, preferring primary sources, then
  lemonde.fr and nytimes.com which they can open.
- Under 250 words unless they asked for depth."""


def build_followup_prompt(thread: Thread, question: str, event_title: str = "") -> str:
    return FOLLOWUP_PROMPT.format(
        symbol=thread.symbol,
        event=event_title or thread.event_key,
        question=question.strip(),
    )


def route(text: str, *, thread: Thread | None):
    """Decide what an incoming message is.

    Returns one of: ("question", text) | ("answer", text) | ("ignore", "")
    A message arriving with no open thread is not a follow-up; it is either a
    command (handled before this) or conversation with nobody listening.
    """
    if not (text or "").strip():
        return ("ignore", "")
    if thread is None:
        return ("ignore", "")
    if looks_like_a_question(text):
        return ("question", text.strip())
    return ("answer", text.strip())
