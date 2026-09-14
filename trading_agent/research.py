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

_BRIEF_PROMPT = """You are briefing a colleague who will decide whether a
clinical trial is likely to succeed. They work in finance and have a real
interest in biotech, but they are not a clinician, and they read this on a
phone. Write plainly.

Writing rules:
- No unexplained jargon or acronyms. The first time a technical term is needed,
  spell it out and say what it means in a few words, for example "overall
  survival, meaning how long patients lived". Use the plain word when one exists.
- Say what numbers mean, not only what they are: "patients lived about five
  months longer on the drug (15 months against 10)", not "mOS 14.7 vs 9.6,
  HR 0.66".
- Short paragraphs. No tables.

Research this trial:

  Company: {company} ({symbol})
  Trial: {title}
  Registry ID: {trial_id}
  Results expected: {date}
{amendments}

Budget: at most six searches, then write.

If this trial has already published its main results, say so in the first line
and stop there: it is not a question anyone can still call.

Otherwise use these headings, in this order:

The company and the drug: what the company does, what the drug is and how it
is meant to work, in two or three sentences. Say whether this drug is one of
many for the company or its main hope.

What this trial tests: which patients, what the drug is compared against, what
counts as success, and whether that is a high or a low bar.

Why it could work: two or three concrete reasons, based on earlier results.

Why it could fail: two or three concrete reasons, such as a small or badly
designed trial, weak earlier results, or changes the company made to the trial
along the way. Registry changes late in a trial are among the most telling
signs available from outside.

Worth watching before the results: the two or three things that, if they happen
before the results come out, should make your colleague reconsider their
answer. Examples: the company changes the trial goals or delays it, a similar
drug reports results, or the company raises money on unusual terms. Say where
each would show up, such as the registry page, a press release or a filing.

Then three links your colleague can open and read. Prefer primary sources
(ClinicalTrials.gov, PubMed, FDA/EMA, SEC filings). Where secondary coverage
helps, prefer lemonde.fr and nytimes.com: they hold subscriptions to both, so
those are readable where other paywalls are not. Say in plain words what each
link is and why it is worth the click.

Be honest about what you could not find. An admitted gap is useful; a confident
guess is worse than silence, because it will be read as evidence.

Keep it under 350 words plus links."""


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
        company=getattr(event, "company", "") or event.symbol,
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
