"""The biotech universe — what the agent is allowed to trade at all."""
from __future__ import annotations

from trading_agent.universe import Universe


def test_seed_universe_is_usable_offline(tmp_path):
    """A cold start with no network must still produce a tradable universe.
    Trading should not stop because a CDN was slow."""
    u = Universe(cache_path=tmp_path / "u.json")
    assert len(u.symbols()) > 10
    assert u.is_biotech("MRNA")


def test_unknown_symbol_is_not_biotech(tmp_path):
    u = Universe(cache_path=tmp_path / "u.json")
    assert not u.is_biotech("AAPL")


def test_symbols_are_normalised(tmp_path):
    u = Universe(cache_path=tmp_path / "u.json")
    assert u.is_biotech("mrna") and u.is_biotech(" MRNA ")


def test_cache_survives_a_restart(tmp_path):
    path = tmp_path / "u.json"
    u = Universe(cache_path=path)
    u._write_cache({"ZZZZ"})
    assert Universe(cache_path=path).is_biotech("ZZZZ")


def test_stale_cache_is_used_rather_than_failing(tmp_path):
    """Explicitly not fatal: a refresh failure must degrade, not halt."""
    path = tmp_path / "u.json"
    u = Universe(cache_path=path)
    u._write_cache({"ZZZZ"})

    def boom(_):
        raise RuntimeError("network down")

    u2 = Universe(cache_path=path, fetcher=boom)
    result = u2.refresh()
    assert result["refreshed"] is False
    assert u2.is_biotech("ZZZZ"), "must fall back to the cached universe"


# --- sponsor names are looked up once and cached ----------------------------

def test_a_company_name_is_looked_up_once_and_kept(tmp_path):
    """Needed for every symbol on every registry sweep, and it changes at most
    once in a company's life."""
    calls = []

    def lookup(symbol):
        calls.append(symbol)
        return "BioMarin Pharmaceutical Inc"

    path = tmp_path / "u.json"
    u = Universe(path, name_lookup=lookup)
    assert u.company_name("BMRN") == "BioMarin Pharmaceutical Inc"
    assert u.company_name("bmrn") == "BioMarin Pharmaceutical Inc"
    assert calls == ["BMRN"]

    # And it survives a restart, so a redeploy does not re-query the lot.
    assert Universe(path, name_lookup=lookup).company_name("BMRN")
    assert calls == ["BMRN"]


def test_an_unknown_name_is_cached_too(tmp_path):
    """Otherwise a delisted ticker is looked up again on every sweep."""
    calls = []

    def lookup(symbol):
        calls.append(symbol)
        return ""

    u = Universe(tmp_path / "u.json", name_lookup=lookup)
    assert u.company_name("GONE") == ""
    assert u.company_name("GONE") == ""
    assert calls == ["GONE"]


def test_a_symbol_with_no_name_is_not_swept(tmp_path):
    """Better to skip a symbol than to search a trial registry for a ticker."""
    from trading_agent.catalysts import CatalystFeed

    class U:
        def symbols(self):
            return {"GONE"}

        def company_name(self, symbol):
            return ""

    def http(url, params):
        raise AssertionError("must not query without a sponsor name")

    assert CatalystFeed(U(), http=http, sleep=lambda _s: None).upcoming_trials() == []
