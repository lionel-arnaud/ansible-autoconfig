"""Detecting amendments to clinical trials.

Sponsors amend registrations, and what they amend is informative. A changed
primary endpoint late in a pivotal trial, a quietly shrinking enrolment, a
completion date that keeps slipping — these are among the few genuinely
asymmetric signals available to an outside observer, because the sponsor knows
something and the registry is where it surfaces first.

ClinicalTrials.gov v2 has no history endpoint (probed: /studies/{id}/history is
404). So history is something we build: snapshot the material fields on each
poll, diff against the previous snapshot, and surface what moved. Slightly more
work, and better in one respect — we decide what counts as material, and we are
told when it changes rather than having to go looking.
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    nct_id TEXT PRIMARY KEY,
    fields TEXT NOT NULL,
    seen_at TEXT NOT NULL
);
"""

# Ordered by how much a change to each tends to mean. An endpoint change in a
# pivotal trial is the loudest signal on this list; a status flip to terminated
# is the bluntest.
MATERIAL_FIELDS = (
    "primary_outcomes",
    "overall_status",
    "enrollment",
    "primary_completion_date",
    "phases",
)

_SEVERITY = {
    "primary_outcomes": "high",
    "overall_status": "high",
    "enrollment": "medium",
    "primary_completion_date": "medium",
    "phases": "medium",
}


@dataclass(frozen=True)
class Amendment:
    nct_id: str
    field: str
    before: object
    after: object
    severity: str

    def describe(self) -> str:
        return (f"{self.nct_id}: {self.field} changed "
                f"[{self.severity}] {self.before!r} -> {self.after!r}")


def extract_fields(study: dict) -> dict:
    """Pull the material fields out of a CTGov v2 study record."""
    proto = study.get("protocolSection", {})
    status = proto.get("statusModule", {})
    design = proto.get("designModule", {})
    outcomes = proto.get("outcomesModule", {})
    return {
        "primary_outcomes": [
            o.get("measure", "") for o in outcomes.get("primaryOutcomes", []) or []
        ],
        "overall_status": status.get("overallStatus", ""),
        "enrollment": (design.get("enrollmentInfo", {}) or {}).get("count"),
        "primary_completion_date": (
            status.get("primaryCompletionDateStruct", {}) or {}
        ).get("date", ""),
        "phases": design.get("phases", []) or [],
    }


class TrialWatcher:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(_SCHEMA)

    def observe(self, nct_id: str, study: dict, *,
                now: dt.datetime) -> list[Amendment]:
        """Record what a trial looks like now, and report what moved.

        The first sighting reports nothing: with no prior snapshot every field
        would look like a change, which would be noise rather than signal.
        """
        current = extract_fields(study)
        row = self._db.execute(
            "SELECT fields FROM snapshots WHERE nct_id=?", (nct_id,)
        ).fetchone()
        self._db.execute(
            "INSERT INTO snapshots(nct_id,fields,seen_at) VALUES(?,?,?) "
            "ON CONFLICT(nct_id) DO UPDATE SET fields=excluded.fields, "
            "seen_at=excluded.seen_at",
            (nct_id, json.dumps(current, sort_keys=True), now.isoformat()),
        )
        if row is None:
            return []

        previous = json.loads(row[0])
        return [
            Amendment(nct_id, f, previous.get(f), current.get(f), _SEVERITY[f])
            for f in MATERIAL_FIELDS
            if previous.get(f) != current.get(f)
        ]
