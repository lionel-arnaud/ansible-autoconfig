"""Research briefs — the junior-analyst half.

The operator judges the science; this gathers what is needed to judge it. It
runs through opencode, which has its own tools, so the model can go and read
rather than only summarise a news feed.

Rationed deliberately: this is the expensive part of the system, so only HIGH
materiality events, and never something already judged unless genuinely new
information has appeared. See events.worth_researching().
"""
from __future__ import annotations

from dataclasses import dataclass

# Sources the operator can actually open. A paywalled link they cannot read is
# worse than no link — it looks like evidence and is not. They hold Le Monde
# and NYT subscriptions, so those are preferred over equivalent coverage
# elsewhere; primary sources outrank all of it.
PREFERRED_SOURCES = (
    "clinicaltrials.gov",
    "pubmed.ncbi.nlm.nih.gov",
    "fda.gov",
    "ema.europa.eu",
    "sec.gov",
    "lemonde.fr",
    "nytimes.com",
)

_BRIEF_PROMPT = """You are a biotech analyst briefing a colleague who will make
the call. They are a CFO with deep biotech domain knowledge — write for someone
who understands clinical development, not for a retail investor.

Research this event and produce a brief:

  Company: {symbol}
  Event: {title}
  Trial: {trial_id}
  Expected: {date}
{amendments}

Budget: at most six searches, then write. This runs on a schedule against a
whole watchlist, so a good brief now beats an exhaustive one later.

Cover, briefly and only where you find real information:

1. **The asset and its trial** — mechanism, what is novel, how derisked by
   earlier phases, and the design: endpoints, powering, comparator. Flag
   anything unusual, such as a soft primary endpoint or a comparator chosen
   to flatter. Name the phase 2 numbers if they exist.
2. **Registry history** — endpoint or enrolment changes, timeline slippage.
   Amendments late in a pivotal trial are the single most informative signal
   available from outside.
3. **What would change your mind** — the two or three things that would most
   move the probability either way.

Then: **three links** the colleague can open and read. Prefer primary sources
(ClinicalTrials.gov, PubMed, FDA/EMA, SEC filings). Where secondary coverage
helps, prefer lemonde.fr and nytimes.com — they hold subscriptions to both, so
those are readable where other paywalls are not. Label each link with what it
is and why it is worth the click.

Be honest about what you could not find. An admitted gap is useful; a confident
guess is worse than silence, because it will be read as evidence.

Keep it under 300 words plus links. It is read on a phone."""


@dataclass(frozen=True)
class Brief:
    symbol: str
    text: str
    ok: bool = True

    def for_telegram(self) -> str:
        return self.text if self.ok else f"(research unavailable for {self.symbol})"


def build_brief_prompt(event, amendments=()) -> str:
    amend_text = ""
    if amendments:
        amend_text = ("\nRegistry amendments already detected:\n"
                      + "\n".join(f"  - {a.describe()}" for a in amendments))
    return _BRIEF_PROMPT.format(
        symbol=event.symbol,
        title=event.title,
        trial_id=event.trial_id or "(none)",
        date=event.date or "(unknown)",
        amendments=amend_text,
    )


# The backend is agentic and its latency has no upper bound worth trusting:
# measured against the real one, this prompt has run past ten minutes. The
# brief now runs on its own thread where a stall costs nothing, so the timeout
# is generous rather than tight — but it exists, because a request that never
# returns would leave the question unasked forever.
BRIEF_TIMEOUT_SECONDS = 600.0


def research(event, *, reasoner, amendments=()) -> Brief:
    """Produce a brief. Failure degrades to no brief, never to a raised error.

    A missing brief means the operator is asked without one, which is worse but
    survivable. A raised error would take down the consultation session and
    they would be asked about nothing at all.
    """
    try:
        text = reasoner.ask(build_brief_prompt(event, amendments),
                            timeout=BRIEF_TIMEOUT_SECONDS)
    except Exception:  # noqa: BLE001
        return Brief(event.symbol, "", ok=False)
    return Brief(event.symbol, (text or "").strip(), ok=bool(text and text.strip()))
