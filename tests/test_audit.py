"""ACCEPTANCE F1-F3 — reconstructing why a trade happened."""
from __future__ import annotations

import datetime as dt
import json

from trading_agent.audit import AuditLog, new_correlation_id


def test_f1_events_carry_timestamp_and_correlation_id(tmp_path):
    log = AuditLog(tmp_path / "audit.log")
    cid = new_correlation_id()
    log.record("decision", cid, {"symbol": "MRNA", "rationale": "phase 3 readout"})
    entry = json.loads((tmp_path / "audit.log").read_text().strip())
    assert entry["correlation_id"] == cid
    assert entry["event"] == "decision"
    assert entry["ts"].endswith("+00:00"), "timestamps must be unambiguous UTC"


def test_f2_a_chain_is_reconstructable_from_an_order_id(tmp_path):
    """The question that matters at 3am: why did this order happen?"""
    log = AuditLog(tmp_path / "audit.log")
    cid = new_correlation_id()
    log.record("catalyst", cid, {"symbol": "MRNA", "trial": "NCT123"})
    log.record("reasoning", cid, {"conclusion": "buy"})
    log.record("guardrail", cid, {"allowed": True})
    log.record("order", cid, {"broker_order_id": "abc-123"})
    log.record("noise", new_correlation_id(), {"unrelated": True})

    chain = log.chain_for_order("abc-123")
    assert [e["event"] for e in chain] == ["catalyst", "reasoning", "guardrail", "order"]


def test_f3_log_rotates_under_a_size_cap(tmp_path):
    """The Pi has a finite SD card and this runs continuously."""
    path = tmp_path / "audit.log"
    log = AuditLog(path, max_bytes=2048, backup_count=2)
    for i in range(500):
        log.record("spam", new_correlation_id(), {"i": i, "pad": "x" * 100})
    produced = sorted(p.name for p in tmp_path.iterdir())
    assert len(produced) <= 3, f"rotation cap exceeded: {produced}"
    assert path.stat().st_size <= 8192


def test_secrets_are_not_written_to_the_log(tmp_path):
    """An audit log is read by humans and copied into tickets."""
    log = AuditLog(tmp_path / "audit.log")
    log.record("config", new_correlation_id(), {
        "alpaca_secret_key": "SHOULD-NOT-APPEAR",
        "telegram_bot_token": "ALSO-NOT",
        "symbol": "MRNA",
    })
    text = (tmp_path / "audit.log").read_text()
    assert "SHOULD-NOT-APPEAR" not in text
    assert "ALSO-NOT" not in text
    assert "MRNA" in text


# --- ACCEPTANCE H3: "what did you do today, and why" ------------------------

def test_the_day_report_answers_what_and_why(tmp_path):
    log = AuditLog(tmp_path / "a.log")
    cid = "c1"
    log.record("catalysts", cid, {"count": 77})
    log.record("question_sent", cid, {"symbol": "BMRN",
                                      "title": "Phase 3 VOXZOGO"})
    log.record("view_recorded", cid, {"symbol": "BMRN", "stance": "positive",
                                      "confidence": 4})
    log.record("proposal", cid, {"symbol": "BMRN", "side": "buy",
                                 "notional": 100.0,
                                 "rationale": "sNDA submitted after a clean readout"})
    log.record("guardrail", cid, {"symbol": "BMRN", "allowed": True,
                                  "reason": "approved"})
    log.record("order", cid, {"symbol": "BMRN", "broker_order_id": "o1"})

    day = dt.datetime.now(dt.timezone.utc).date().isoformat()
    report = log.day_report(day)

    assert "BMRN" in report
    assert "sNDA submitted" in report, "the why, not just the what"
    assert "asked you" in report and "positive" in report


def test_the_day_report_says_why_it_did_nothing(tmp_path):
    """A day with no trades is the normal day for this agent, and a report
    that just says nothing happened teaches the operator nothing."""
    log = AuditLog(tmp_path / "a.log")
    log.record("catalysts", "c1", {"count": 50})
    log.record("view_gate", "c1", {"symbol": "MRNA", "reason": "no view recorded"})
    log.record("guardrail", "c2", {"symbol": "VRTX", "allowed": False,
                                   "reason": "max_position: 900 exceeds 150"})

    report = log.day_report(dt.datetime.now(dt.timezone.utc).date().isoformat())
    assert "declined" in report
    assert "max_position" in report and "no view recorded" in report
    assert "No trades" in report


def test_a_day_with_nothing_recorded_says_so(tmp_path):
    assert "nothing recorded" in AuditLog(tmp_path / "a.log").day_report("2020-01-01")
