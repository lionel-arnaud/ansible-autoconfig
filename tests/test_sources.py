"""The network boundary. Every test here uses a fake transport — these are the
shapes the agent expects back, and the ways each source is allowed to fail."""
from __future__ import annotations

import io
import json
import string
import zipfile

from trading_agent.config import Config
from trading_agent.sources import (alpaca_news_client, ctgov_client,
                                   etf_holdings_fetcher)


class Resp:
    def __init__(self, status=200, payload=None, text="", content=b""):
        self.status_code = status
        self._payload = payload
        self.text = text
        self.content = content

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def _get(resp):
    def get(url, params=None, headers=None, timeout=None):
        get.calls.append((url, params, headers))
        return resp
    get.calls = []
    return get


# --- ClinicalTrials.gov -----------------------------------------------------

def test_ctgov_returns_the_studies_list():
    get = _get(Resp(payload={"studies": [{"protocolSection": {}}]}))
    assert len(ctgov_client(get=get)("u", {"q": 1})) == 1


def test_ctgov_degrades_to_nothing_on_an_error_status():
    assert ctgov_client(get=_get(Resp(status=503)))("u", {}) == []


def test_ctgov_degrades_to_nothing_on_a_reshaped_payload():
    """Likelier than an outage and much easier to miss: the endpoint answers
    200 with a body that no longer holds a studies list."""
    assert ctgov_client(get=_get(Resp(payload={"data": []})))("u", {}) == []
    assert ctgov_client(get=_get(Resp(payload={"studies": "soon"})))("u", {}) == []


# --- Alpaca news ------------------------------------------------------------

NEWS = {"news": [{"headline": "Phase 3 hit", "symbols": ["MRNA", "BNTX"],
                  "created_at": "2026-09-11T12:00:00Z", "url": "http://x"}]}


def test_news_is_expanded_to_one_entry_per_symbol():
    get = _get(Resp(payload=NEWS))
    items = alpaca_news_client(Config.for_testing(), get=get)({"MRNA", "BNTX"}, 5)
    assert sorted(i["symbol"] for i in items) == ["BNTX", "MRNA"]
    assert items[0]["headline"] == "Phase 3 hit"


def test_news_sends_credentials_and_never_puts_them_in_the_url():
    get = _get(Resp(payload=NEWS))
    alpaca_news_client(Config.for_testing(), get=get)({"MRNA"}, 5)
    url, params, headers = get.calls[0]
    assert headers["APCA-API-KEY-ID"] == "test"
    assert "test" not in url and "test" not in json.dumps(params)


def test_news_asks_for_nothing_when_the_universe_is_empty():
    get = _get(Resp(payload=NEWS))
    assert alpaca_news_client(Config.for_testing(), get=get)([], 5) == []
    assert not get.calls, "an empty universe must not become an unfiltered query"


def test_news_limit_is_clamped_to_what_the_api_accepts():
    get = _get(Resp(payload=NEWS))
    alpaca_news_client(Config.for_testing(), get=get)({"MRNA"}, 5000)
    assert get.calls[0][1]["limit"] == 50


def test_news_covers_the_whole_universe_rather_than_the_first_page():
    """Truncating the symbol list would mean the agent never saw news about
    anything past the start of the alphabet."""
    get = _get(Resp(payload={"news": []}))
    universe = {f"S{i:03d}" for i in range(130)}
    alpaca_news_client(Config.for_testing(), get=get)(universe, 20)

    asked = set()
    for _url, params, _headers in get.calls:
        asked |= set(params["symbols"].split(","))
    assert asked == universe


def test_news_about_a_symbol_outside_the_universe_is_dropped():
    """Alpaca tags an article with every symbol it mentions. An article about
    MRNA that also names a symbol the agent may not trade must not introduce
    it as a catalyst."""
    get = _get(Resp(payload=NEWS))
    items = alpaca_news_client(Config.for_testing(), get=get)({"MRNA"}, 5)
    assert [i["symbol"] for i in items] == ["MRNA"]


# --- ETF holdings -----------------------------------------------------------

def _xlsx(strings):
    buf = io.BytesIO()
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    body = "".join(f"<si><t>{s}</t></si>" for s in strings)
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/sharedStrings.xml", f'<sst xmlns="{ns}">{body}</sst>')
    return buf.getvalue()


# Letters only: that is what a ticker looks like, and it is what screens the
# prose out of these files.
_A = string.ascii_uppercase
CSV_NAMES = [f"C{a}{b}" for a in _A[:6] for b in _A[:5]]
XLSX_NAMES = [f"X{a}{b}" for a in _A[:6] for b in _A[:5]]
REAL_CSV = "\n".join(["Ticker,Name"] + [f"{s},Co" for s in CSV_NAMES])
REAL_XLSX = _xlsx(XLSX_NAMES + ["Fund Name:"])


def test_holdings_are_the_union_of_both_issuers():
    def get(url, params=None, headers=None, timeout=None):
        return (Resp(text=REAL_CSV) if "ishares" in url
                else Resp(content=REAL_XLSX))
    symbols = etf_holdings_fetcher(get=get)()
    assert "CAA" in symbols and "XAA" in symbols
    assert len(symbols) == 60


def test_one_issuer_failing_still_yields_the_other():
    def get(url, params=None, headers=None, timeout=None):
        return Resp(status=500) if "ishares" in url else Resp(content=REAL_XLSX)
    assert len(etf_holdings_fetcher(get=get)()) == 30


def test_a_bot_check_page_is_rejected_before_it_joins_the_union():
    """iShares intermittently answers a CSV request with HTML. Scraping it
    yields a few ticker-shaped words — LLC, NL — which must never reach the
    tradable universe on the back of the other issuer's good data."""
    html = "<html><body>Access to this page has been denied. NL LLC</body></html>"

    def get(url, params=None, headers=None, timeout=None):
        return Resp(text=html) if "ishares" in url else Resp(content=REAL_XLSX)
    symbols = etf_holdings_fetcher(get=get)()
    assert "LLC" not in symbols and "NL" not in symbols
    assert len(symbols) == 30


def test_both_issuers_failing_returns_nothing_so_the_cache_survives():
    def get(url, params=None, headers=None, timeout=None):
        raise OSError("dns")
    assert etf_holdings_fetcher(get=get)() == set()


def test_file_artifacts_are_not_mistaken_for_holdings():
    """The live XBI file put SEDOL and USD into the tradable universe: a column
    header and the currency, both ticker-shaped."""
    csv_text = "\n".join(["Ticker,Name,Currency,SEDOL"]
                         + [f"{s},Co,USD,BXXXXX" for s in CSV_NAMES])

    def get(url, params=None, headers=None, timeout=None):
        return Resp(text=csv_text) if "ishares" in url else Resp(status=500)

    symbols = etf_holdings_fetcher(get=get)()
    assert "SEDOL" not in symbols and "USD" not in symbols
    assert symbols == set(CSV_NAMES)


# --- ticker to sponsor name -------------------------------------------------

def test_an_exchange_listing_becomes_a_sponsor_name():
    """A trial registry files ACADIA as "ACADIA Pharmaceuticals Inc.", not as
    an exchange lists it."""
    from trading_agent.sources import _company_name

    assert _company_name("ACADIA Pharmaceuticals Inc. Common Stock") == \
        "ACADIA Pharmaceuticals Inc"
    assert _company_name("Legend Biotech Corporation American Depositary "
                         "Shares") == "Legend Biotech Corporation"


def test_an_unknown_ticker_yields_no_name_rather_than_a_guess():
    from trading_agent.sources import alpaca_assets_client

    fetch = alpaca_assets_client(Config.for_testing(), get=_get(Resp(status=404)))
    assert fetch("NOPE") == ""
