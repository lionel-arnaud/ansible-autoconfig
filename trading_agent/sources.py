"""Real data sources.

Every collaborator the agent talks to over the network is constructed here and
nowhere else. The modules that use them — catalysts, universe — take them as
arguments and are tested with fakes, so this file is the only place a real URL
appears and the only place that needs re-checking when a provider changes.

Everything here is best-effort by contract: a source that is slow, broken or
reshaped returns nothing and the caller degrades. Trading on half a picture is
worse than trading on none.
"""
from __future__ import annotations

import csv
import io
import re
import xml.etree.ElementTree as ET
import zipfile

# Tickers only, the way an exchange writes them. Screens out the footnote rows
# and disclaimer text that ship inside these files.
_TICKER = re.compile(r"^[A-Z]{1,5}(?:\.[A-Z])?$")
# Ticker-shaped words that appear in holdings files without being holdings:
# column headers, the cash line, the currency, the settlement rows. They pass
# the shape test and would otherwise become symbols the agent tries to trade.
_NOT_A_HOLDING = {
    "SEDOL", "CUSIP", "ISIN", "USD", "EUR", "GBP", "CASH", "NAME", "TICKER",
    "SHARES", "PRICE", "VALUE", "WEIGHT", "SECTOR", "MARKET", "NL", "LLC",
    "INC", "LTD", "PLC", "CORP", "ETF", "FUND", "TOTAL", "OTHER", "N", "A",
}

# Published daily by the issuers. XBI is SPDR/State Street, IBB is iShares.
XBI_HOLDINGS = (
    "https://www.ssga.com/us/en/intermediary/etfs/library-content/"
    "products/fund-data/etfs/us/holdings-daily-us-en-xbi.xlsx"
)
IBB_HOLDINGS = (
    "https://www.ishares.com/us/products/239699/"
    "ishares-nasdaq-biotechnology-etf/1467271812596.ajax"
    "?fileType=csv&fileName=IBB_holdings&dataType=fund"
)
# Both issuers serve a bot-check page to an unfamiliar client.
_UA = "Mozilla/5.0 (compatible; ansible-autoconfig trading-agent)"

ALPACA_NEWS = "https://data.alpaca.markets/v1beta1/news"
# Suffixes the exchange listing carries and a trial registry never does.
_NAME_NOISE = re.compile(
    r"\s*(?:-\s*)?(?:common stock|ordinary shares?|class [a-c] .*|american "
    r"depositary shares?.*|ads.*|\(the\).*)$", re.I)
# Alpaca accepts a long symbols list; this keeps each URL and page sane.
_NEWS_CHUNK = 50
# Below this a "holdings file" is a parse that found headers, or an error page.
_MIN_HOLDINGS = 20
_XL = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def _get(url: str, *, params: dict | None = None, headers: dict | None = None,
         timeout: float = 30.0):
    import httpx

    return httpx.get(url, params=params, headers=headers, timeout=timeout,
                     follow_redirects=True)


class RateLimited(RuntimeError):
    """The source asked us to slow down. Distinct from a failure, because the
    right response is to wait rather than to shrug and carry on."""


def ctgov_client(*, get=_get):
    """ClinicalTrials.gov API v2. Returns the studies list, or [] on anything
    unexpected — including a reshaped payload, which is likelier than an
    outage and much easier to miss."""
    def fetch(url: str, params: dict) -> list[dict]:
        r = get(url, params=params)
        if r.status_code == 429:
            raise RateLimited(url)
        if r.status_code != 200:
            return []
        data = r.json()
        studies = data.get("studies") if isinstance(data, dict) else None
        return studies if isinstance(studies, list) else []

    return fetch


def alpaca_news_client(config, *, get=_get):
    """Alpaca's news feed for the universe. The same credentials as trading,
    on the data host rather than the broker host."""
    def fetch(symbols, limit: int = 20) -> list[dict]:
        if not symbols:
            return []
        names = sorted(symbols)
        out: list[dict] = []
        # Chunked, not truncated. The universe is two ETFs' holdings, well over
        # one request's worth of symbols, and taking the first fifty would mean
        # the agent never saw news about anything after the letter C.
        for i in range(0, len(names), _NEWS_CHUNK):
            chunk = names[i:i + _NEWS_CHUNK]
            try:
                r = get(
                    ALPACA_NEWS,
                    params={"symbols": ",".join(chunk),
                            "limit": max(1, min(int(limit), 50))},
                    headers={"APCA-API-KEY-ID": config.alpaca_key_id,
                             "APCA-API-SECRET-KEY": config.alpaca_secret_key},
                )
            except Exception:  # noqa: BLE001 — one chunk must not lose the rest
                continue
            if r.status_code != 200:
                continue
            items = r.json().get("news", [])
            for item in items if isinstance(items, list) else []:
                for symbol in item.get("symbols", []) or []:
                    # Alpaca tags an article with every symbol it mentions,
                    # including ones outside the universe.
                    if symbol not in symbols:
                        continue
                    out.append({
                        "symbol": symbol,
                        "headline": item.get("headline", ""),
                        "created_at": item.get("created_at", ""),
                        "url": item.get("url", ""),
                    })
        return out

    return fetch


def _tickers_from_csv(text: str) -> set[str]:
    out: set[str] = set()
    for row in csv.reader(io.StringIO(text)):
        for cell in row:
            cell = cell.strip().strip('"')
            if _TICKER.match(cell) and cell not in _NOT_A_HOLDING:
                out.add(cell)
                break  # the ticker is the first ticker-shaped cell in a row
    return out


def _tickers_from_xlsx(blob: bytes) -> set[str]:
    """Read the shared-string table directly rather than adding a spreadsheet
    dependency. An xlsx is a zip of XML, the holdings are strings, and one
    library fewer on a host that places orders is worth forty lines."""
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        if "xl/sharedStrings.xml" not in z.namelist():
            return set()
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
    strings = ["".join(t.text or "" for t in si.iter(_XL + "t")) for si in root]
    return {s.strip() for s in strings
            if _TICKER.match(s.strip()) and s.strip() not in _NOT_A_HOLDING}


def etf_holdings_fetcher(*, get=_get):
    """Union of the XBI and IBB holdings.

    A union, not an intersection: the operator wants the investable biotech
    universe, and a name held by either fund qualifies. If one issuer fails the
    other still yields a usable list; if both fail the caller keeps its cache.
    """
    def fetch(_unused=None) -> set[str]:
        found: set[str] = set()
        for url, parse in ((IBB_HOLDINGS, "csv"), (XBI_HOLDINGS, "xlsx")):
            try:
                r = get(url, headers={"User-Agent": _UA})
                if r.status_code != 200:
                    continue
                names = (_tickers_from_csv(r.text) if parse == "csv"
                         else _tickers_from_xlsx(r.content))
            except Exception:  # noqa: BLE001 — one issuer must not sink the other
                continue
            # Checked per issuer, before the union. iShares intermittently
            # answers a CSV request with its bot-check page, and a handful of
            # ticker-shaped words scraped out of HTML ("LLC", "NL") would
            # otherwise enter the tradable universe on the back of the other
            # issuer's good data.
            if len(names) >= _MIN_HOLDINGS:
                found |= names
        return found

    return fetch


def _company_name(raw: str) -> str:
    """The name a trial registry would file a sponsor under.

    "ACADIA Pharmaceuticals Inc. Common Stock" is how an exchange lists a
    security; ClinicalTrials.gov knows it as "ACADIA Pharmaceuticals Inc.".
    """
    return _NAME_NOISE.sub("", (raw or "").strip()).strip(" .,")


def alpaca_assets_client(config, *, get=_get):
    """Ticker to company name.

    Needed because a trial registry does not know tickers. Searching it for
    "ACAD" matched trials containing "Academy" and "Acute" — the agent asked
    the operator to judge an obesity study run by a company it cannot trade.
    """
    def fetch(symbol: str) -> str:
        try:
            r = get(
                f"{config.endpoint}/v2/assets/{symbol}",
                headers={"APCA-API-KEY-ID": config.alpaca_key_id,
                         "APCA-API-SECRET-KEY": config.alpaca_secret_key},
            )
        except Exception:  # noqa: BLE001
            return ""
        if r.status_code != 200:
            return ""
        try:
            return _company_name(r.json().get("name", ""))
        except Exception:  # noqa: BLE001
            return ""

    return fetch
