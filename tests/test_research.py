"""Research briefs — what goes into the prompt, and what happens when it fails."""
from __future__ import annotations

from trading_agent.events import Event, EventKind
from trading_agent.research import PREFERRED_SOURCES, build_brief_prompt, research
from trading_agent.trial_watch import Amendment


def ev():
    return Event("MRNA", EventKind.TRIAL_READOUT, "Phase 3 adjuvant melanoma",
                 trial_id="NCT05933577", date="2026-10-15")


class Reasoner:
    def __init__(self, text=None, fail=False):
        self.text, self.fail, self.seen = text, fail, None

    def ask(self, prompt, **kwargs):
        if self.fail:
            raise OSError("opencode down")
        self.seen = prompt
        return self.text


def test_the_prompt_names_the_operators_readable_sources():
    """A paywalled link they cannot open looks like evidence and is not."""
    p = build_brief_prompt(ev())
    assert "lemonde.fr" in p and "nytimes.com" in p
    assert "subscriptions" in p


def test_primary_sources_outrank_journalism():
    # Normalised, because the prompt is hard-wrapped and the phrase straddles
    # a newline — asserting on the raw text tests the wrapping, not the meaning.
    p = " ".join(build_brief_prompt(ev()).split())
    assert "ClinicalTrials.gov" in p and "PubMed" in p
    assert p.index("primary sources") < p.index("lemonde.fr")


def test_the_prompt_asks_for_links_and_for_honest_gaps():
    p = build_brief_prompt(ev())
    assert "links" in p
    # A confident guess in a research brief is worse than silence — it gets
    # read as evidence.
    assert "could not find" in p or "admitted gap" in p


def test_detected_amendments_are_fed_into_the_brief():
    """The registry signal must reach the analyst, not just the log."""
    a = Amendment("NCT05933577", "primary_outcomes", ["OS"], ["PFS"], "high")
    p = build_brief_prompt(ev(), amendments=[a])
    assert "primary_outcomes" in p and "PFS" in p


def test_the_prompt_targets_an_expert_reader():
    assert "not for a retail investor" in build_brief_prompt(ev())


def test_research_failure_degrades_rather_than_raising():
    """A missing brief is survivable; a raised error would take down the whole
    consultation session and they would be asked about nothing."""
    b = research(ev(), reasoner=Reasoner(fail=True))
    assert b.ok is False and "unavailable" in b.for_telegram()


def test_an_empty_response_is_treated_as_no_brief():
    assert research(ev(), reasoner=Reasoner(text="   ")).ok is False


def test_a_good_brief_is_passed_through():
    b = research(ev(), reasoner=Reasoner(text="Single-asset oncology story."))
    assert b.ok and "Single-asset" in b.for_telegram()
