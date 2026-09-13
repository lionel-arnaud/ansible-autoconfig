"""What the agent may trade.

Derived from biotech ETF holdings (XBI, IBB) rather than a hand-kept list: the
operator was clear that a manual list is too large and too time-dependent to
maintain, and an ETF's published holdings are already curated, auditable and
self-updating.

A seed list ships in-tree so a cold start works with no network. Refreshing is
explicit and never fatal — a slow CDN must not stop trading.
"""
from __future__ import annotations

import json
from pathlib import Path

# Seed only. Large, liquid biotech names so a cold start is tradable before the
# first successful refresh; the real universe comes from the ETF holdings.
_SEED = {
    "MRNA", "BNTX", "REGN", "VRTX", "GILD", "AMGN", "BIIB", "ILMN", "INCY",
    "ALNY", "BMRN", "NBIX", "SRPT", "IONS", "EXAS", "TECH", "RARE", "FOLD",
    "ARWR", "BEAM", "NTLA", "CRSP", "EDIT", "VCYT", "HALO", "UTHR", "JAZZ",
    "XBI", "IBB",
}


class Universe:
    def __init__(self, cache_path: Path | str, fetcher=None,
                 name_lookup=None) -> None:
        self.cache_path = Path(cache_path)
        self._fetcher = fetcher
        self._name_lookup = name_lookup
        cached = self._read_cache()
        self._symbols = (cached or {}).get("symbols") or set(_SEED)
        self._names: dict[str, str] = (cached or {}).get("names") or {}

    def symbols(self) -> set[str]:
        return set(self._symbols)

    def is_biotech(self, symbol: str) -> bool:
        return (symbol or "").strip().upper() in self._symbols

    def refresh(self) -> dict:
        """Pull fresh holdings. Failure degrades to the cache, never raises."""
        if self._fetcher is None:
            return {"refreshed": False, "reason": "no fetcher configured",
                    "count": len(self._symbols)}
        try:
            fetched = {s.strip().upper() for s in self._fetcher(None) if s.strip()}
        except Exception as exc:  # noqa: BLE001 — degrade, do not halt
            return {"refreshed": False, "reason": str(exc),
                    "count": len(self._symbols)}
        if not fetched:
            # An empty result is far more likely to be a broken parse than a
            # genuinely empty ETF, and adopting it would silently forbid
            # everything.
            return {"refreshed": False, "reason": "empty result ignored",
                    "count": len(self._symbols)}
        self._write_cache(fetched)
        return {"refreshed": True, "count": len(fetched)}

    def company_name(self, symbol: str) -> str:
        """The sponsor name a trial registry would use, or "" if unknown.

        Looked up once per symbol and cached on disk: it is the kind of fact
        that changes at most once in a company's life, and the registry sweep
        needs it for every symbol on every sweep.
        """
        symbol = (symbol or "").strip().upper()
        if symbol in self._names:
            return self._names[symbol]
        if self._name_lookup is None:
            return ""
        try:
            name = self._name_lookup(symbol) or ""
        except Exception:  # noqa: BLE001 — an unknown name is not an error
            name = ""
        # Cached even when empty, so a delisted or unrecognised ticker is not
        # looked up again on every sweep.
        self._names[symbol] = name
        self._write_cache(self._symbols)
        return name

    def _read_cache(self) -> dict | None:
        try:
            data = json.loads(self.cache_path.read_text())
        except Exception:  # noqa: BLE001 — a missing or corrupt cache is normal
            return None
        symbols = {s.upper() for s in data.get("symbols", [])}
        names = {k.upper(): v for k, v in (data.get("names") or {}).items()}
        return {"symbols": symbols or None, "names": names}

    def _write_cache(self, symbols: set[str]) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(
            {"symbols": sorted(symbols), "names": self._names}))
        self._symbols = set(symbols)
