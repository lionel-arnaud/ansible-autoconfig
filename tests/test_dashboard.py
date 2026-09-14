"""The operator's daily page: what it shows, and what it must never do."""
from __future__ import annotations

import datetime as dt
import sqlite3

import pytest

from trading_agent import dashboard
from trading_agent.audit import AuditLog
from trading_agent.state import State
from trading_agent.views import View, ViewStore

NOW = dt.datetime.now(dt.timezone.utc)
SUMMARY = {
    "available": True, "paper": True, "equity": 1012.5, "cash": 900.0,
    "buying_power": 1800.0,
    "positions": [{"symbol": "IBRX", "qty": 10.0, "market_value": 112.5,
                   "cost_basis": 100.0, "unrealized_pl": 12.5,
                   "unrealized_plpc": 0.125}],
}
LIMITS = {"live": False, "max_position_usd": 150.0, "max_deployed_usd": 750.0,
          "max_trades_per_day": 5, "daily_loss_limit_usd": 50.0}


def _staging(tmp_path):
    root = tmp_path / "staging"
    (root / "logs").mkdir(parents=True)
    state = State(root / "state.db")
    state.open_thread_for("NCT02138734", "IBRX", "BCG with ALT-803 in bladder cancer",
                          NOW - dt.timedelta(days=1))
    state.close_thread()
    state.open_thread_for("NCT00000001", "RGNX", "RGX-314 gene therapy", NOW)
    views = ViewStore(root / "views.db")
    views.record(View("IBRX", "NCT02138734", "positive", 1,
                      "design is sound <script>alert(1)</script>",
                      NOW - dt.timedelta(hours=16), NOW + dt.timedelta(days=90)))
    audit = AuditLog(root / "logs" / "audit.log")
    audit.record("view_recorded", "c1", {"symbol": "IBRX", "event": "NCT02138734",
                                         "stance": "positive", "confidence": 1})
    audit.record("catalysts", "c2", {"count": 7})
    (root / "universe.json").write_text(
        '{"symbols": ["IBRX", "RGNX"], '
        '"names": {"IBRX": "ImmunityBio", "RGNX": "REGENXBIO"}}')
    # As the push script leaves them: self-contained files, no writers open.
    for store in (state, views):
        store._db.close()
    for name in ("state.db", "views.db"):
        c = sqlite3.connect(root / name)
        c.execute("PRAGMA journal_mode=DELETE")
        c.close()
    return root


def _page(root, summary=SUMMARY, limits=LIMITS):
    return dashboard.render(dashboard.collect(root, broker_summary=summary,
                                              limits=limits, now=NOW))


def test_the_page_says_it_is_a_daily_snapshot(tmp_path):
    """The operator accepted a day-old page on one condition: that it says so."""
    page = _page(_staging(tmp_path))
    assert "Daily snapshot, not live." in page
    assert "may be up to a day old" in page
    assert 'data-generated="' in page
    assert "older than expected" in page  # the stale warning is wired


def test_calls_are_shown_in_plain_words(tmp_path):
    page = _page(_staging(tmp_path))
    assert "ImmunityBio (IBRX)" in page
    assert "Yes, it will succeed" in page and "confidence 1/5" in page
    assert "https://clinicaltrials.gov/study/NCT02138734" in page
    assert "awaiting results" in page


def test_dictated_notes_are_escaped(tmp_path):
    page = _page(_staging(tmp_path))
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page


def test_the_waiting_question_is_shown(tmp_path):
    page = _page(_staging(tmp_path))
    assert "REGENXBIO (RGNX)" in page and "RGX-314 gene therapy" in page


def test_positions_limits_and_mode_are_shown(tmp_path):
    page = _page(_staging(tmp_path))
    assert "$12.50 (+12.5%)" in page
    assert "PAPER" in page
    assert "$150.00 per position" in page


def test_a_broker_outage_costs_only_the_portfolio_section(tmp_path):
    page = _page(_staging(tmp_path),
                 summary={"available": False, "error": "sentinel-broker-error"})
    assert "Portfolio unavailable" in page
    assert "sentinel-broker-error" not in page  # error text is never published
    assert "ImmunityBio (IBRX)" in page


def test_rendering_never_writes_to_the_snapshots(tmp_path):
    root = _staging(tmp_path)
    before = {p.name: p.read_bytes() for p in root.glob("*.db")}
    _page(root)
    assert {p.name: p.read_bytes() for p in root.glob("*.db")} == before
    assert not list(root.glob("*-wal")) and not list(root.glob("*-shm"))

    store = ViewStore.read_only(root / "views.db")
    with pytest.raises(sqlite3.OperationalError):
        store._db.execute("DELETE FROM views")
    store.close()


def test_an_empty_staging_directory_still_renders(tmp_path):
    (tmp_path / "empty").mkdir()
    page = _page(tmp_path / "empty", summary={"available": False}, limits={})
    assert "No calls recorded yet." in page and "No question waiting." in page


def test_the_rendered_file_never_contains_a_credential(tmp_path, monkeypatch):
    from trading_agent.broker import Broker

    root = _staging(tmp_path)
    secrets = {"ALPACA_API_KEY_ID": "sentinel-key-value-not-real",
               "ALPACA_API_SECRET_KEY": "sentinel-secret-value-not-real",
               "TELEGRAM_BOT_TOKEN": "sentinel-token-value-not-real",
               "OPENCODE_PASSWORD": "sentinel-password-value-not-real"}
    for key, value in secrets.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(Broker, "from_config",
                        classmethod(lambda cls, cfg: Broker.for_testing()))

    out = tmp_path / "site" / "index.html"
    assert dashboard.main(["--root", str(root), "--out", str(out)]) == 0
    page = out.read_text()
    assert "PAPER" in page and "$1,000.00" in page
    for value in secrets.values():
        assert value not in page


def test_the_env_file_is_read_literally_not_by_a_shell(tmp_path, monkeypatch):
    """Passwords contain shell punctuation. Sourcing the file with a shell
    would act on it."""
    env = tmp_path / "env"
    env.write_text("# comment\nOPENCODE_PASSWORD=pa$$w;rd&(x)`id`\nQUOTED=\"a b\"\n")
    monkeypatch.delenv("OPENCODE_PASSWORD", raising=False)
    monkeypatch.delenv("QUOTED", raising=False)
    dashboard._load_env_file(str(env))
    import os
    assert os.environ["OPENCODE_PASSWORD"] == "pa$$w;rd&(x)`id`"
    assert os.environ["QUOTED"] == "a b"
