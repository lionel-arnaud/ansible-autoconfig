"""Classifying events: what deserves research, and what deserves a score.

Two separate judgments, deliberately not conflated:

  * **Materiality** decides whether an event is worth spending tokens
    researching. Deep research per catalyst costs real money, so most things
    must not qualify.
  * **Scoreability** decides whether the operator's call on it belongs in the
    scoreboard. Their edge is biotech judgment, so a purely financial event is
    worth reading and not worth grading — scoring it would dilute the one
    number that is supposed to measure domain skill.

An earnings beat is a good example of something that can be material enough to
mention and still be wrong to score.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class Materiality(IntEnum):
    LOW = 1       # mention if asked, never research
    MEDIUM = 2    # research only when no view exists yet
    HIGH = 3      # always worth researching


class EventKind:
    TRIAL_READOUT = "trial_readout"
    TRIAL_AMENDMENT = "trial_amendment"
    INTERIM_ANALYSIS = "interim_analysis"
    REGULATORY = "regulatory"       # PDUFA dates, approvals, CRLs
    EARNINGS = "earnings"
    NEWS = "news"


# The operator's edge is judging science, not quarterly numbers. Financial
# events still get surfaced — they move prices — but a call on one says nothing
# about biotech skill, so it stays out of the score.
_SCOREABLE = {
    EventKind.TRIAL_READOUT,
    EventKind.TRIAL_AMENDMENT,
    EventKind.INTERIM_ANALYSIS,
    EventKind.REGULATORY,
}

# Which events carry NEW information capable of invalidating a view already
# held. This is a different axis from materiality, and conflating them was a
# bug: a scheduled readout is important, but it is precisely what the existing
# view was formed about, so re-asking is noise. An amendment or a regulatory
# action is genuinely new, so it is worth a second look.
_INVALIDATES_PRIOR_VIEW = {
    EventKind.TRIAL_AMENDMENT,
    EventKind.REGULATORY,
}

_MATERIALITY = {
    EventKind.TRIAL_READOUT: Materiality.HIGH,
    EventKind.REGULATORY: Materiality.HIGH,
    EventKind.TRIAL_AMENDMENT: Materiality.HIGH,
    EventKind.INTERIM_ANALYSIS: Materiality.MEDIUM,
    EventKind.EARNINGS: Materiality.LOW,
    EventKind.NEWS: Materiality.LOW,
}


@dataclass(frozen=True)
class Event:
    symbol: str
    kind: str
    title: str
    # The trial this belongs to, where there is one. Views are keyed on this
    # rather than on the individual item, so a read on a trial carries across
    # its interim analysis, its amendments and its final readout — which is
    # both cheaper and closer to how the judgment actually works.
    trial_id: str = ""
    date: str = ""
    url: str = ""

    @property
    def materiality(self) -> Materiality:
        return _MATERIALITY.get(self.kind, Materiality.LOW)

    @property
    def invalidates_prior_view(self) -> bool:
        """Does this carry information that could change an existing view?"""
        return self.kind in _INVALIDATES_PRIOR_VIEW

    @property
    def is_scoreable(self) -> bool:
        return self.kind in _SCOREABLE

    @property
    def view_key(self) -> str:
        """What a view on this event is filed under. Falls back to the symbol
        when there is no trial, so company-level calls still have a home."""
        return self.trial_id or self.symbol


def worth_researching(event: Event, *, has_view: bool,
                      threshold: Materiality = Materiality.MEDIUM) -> bool:
    """Should tokens be spent researching this?

    The cheapest saving available is not re-researching something already
    judged: a held view is the answer research was trying to produce. Only a
    HIGH event overrides that, because an amendment or a termination can
    genuinely invalidate an earlier read.
    """
    if event.materiality < threshold:
        return False
    if has_view and not event.invalidates_prior_view:
        # Already judged, and nothing new has happened. Re-researching would
        # spend tokens to re-derive an answer already on file, and re-asking
        # would spend the operator's patience, which is the scarcer resource.
        return False
    return True
