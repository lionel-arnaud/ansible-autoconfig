"""Configuration, and the gate that keeps real money out of reach.

The live endpoint is deliberately hard to reach: it needs TWO independent
environment variables, because a single one can be set by a typo, a stale
shell, or a unit file copied from somewhere else. Two cannot be set by accident.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass

PAPER_ENDPOINT = "https://paper-api.alpaca.markets"
LIVE_ENDPOINT = "https://api.alpaca.markets"


class ConfigError(RuntimeError):
    """Raised at startup for a configuration that must not be allowed to run."""


@dataclass(frozen=True)
class Config:
    endpoint: str
    alpaca_key_id: str
    alpaca_secret_key: str
    # Risk limits. Deterministic, enforced in guardrails.py, never delegated to
    # the model. Defaults match the operator's confirmed $1000 account.
    max_position_usd: float = 150.0
    max_deployed_usd: float = 750.0
    max_trades_per_day: int = 5
    daily_loss_limit_usd: float = 50.0
    account_equity_usd: float = 1000.0
    # Below this, the agent acts without asking. Set to 0.0 to be asked about
    # everything. The operator disabled mandatory approval, so this defaults to
    # "never ask" — but the path stays wired, so re-enabling is config, not a
    # rewrite.
    approval_threshold_usd: float = float("inf")
    # How long a request waits before it is denied. Never auto-approved.
    approval_ttl_seconds: float = 3600.0
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    opencode_url: str = ""
    opencode_user: str = "lion"
    opencode_password: str = ""

    @property
    def is_live(self) -> bool:
        return self.endpoint == LIVE_ENDPOINT

    @classmethod
    def from_env(cls, *, _require_secrets: bool = True) -> "Config":
        mode = os.environ.get("TRADING_MODE", "paper").strip().lower()
        confirmed = os.environ.get("LIVE_CONFIRMED", "").strip().lower()

        # Both, or neither. Never one.
        live = mode == "live" and confirmed == "yes"
        endpoint = LIVE_ENDPOINT if live else PAPER_ENDPOINT

        key = os.environ.get("ALPACA_API_KEY_ID", "")
        secret = os.environ.get("ALPACA_API_SECRET_KEY", "")
        if _require_secrets and not (key and secret):
            raise ConfigError(
                "ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY must be set; "
                "they are rendered into /etc/trading-agent/env from the vault."
            )

        return cls(
            endpoint=endpoint,
            alpaca_key_id=key,
            alpaca_secret_key=secret,
            max_position_usd=_num("MAX_POSITION_USD", 150.0),
            max_deployed_usd=_num("MAX_DEPLOYED_USD", 750.0),
            max_trades_per_day=int(_num("MAX_TRADES_PER_DAY", 5)),
            daily_loss_limit_usd=_num("DAILY_LOSS_LIMIT_USD", 50.0),
            account_equity_usd=_num("ACCOUNT_EQUITY_USD", 1000.0),
            approval_threshold_usd=_num("APPROVAL_THRESHOLD_USD", float("inf")),
            approval_ttl_seconds=_num("APPROVAL_TTL_SECONDS", 3600.0),
            telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
            telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID", ""),
            opencode_url=os.environ.get("OPENCODE_URL", ""),
            opencode_user=os.environ.get("OPENCODE_USER", "lion"),
            opencode_password=os.environ.get("OPENCODE_PASSWORD", ""),
        )

    @classmethod
    def for_testing(cls, **overrides) -> "Config":
        base = dict(
            endpoint=PAPER_ENDPOINT,
            alpaca_key_id="test",
            alpaca_secret_key="test",
        )
        base.update(overrides)
        return cls(**base)


def _num(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        # Fail closed: an unparseable limit must stop startup, not silently
        # fall back to a default the operator did not choose.
        raise ConfigError(f"{name}={raw!r} is not a number") from exc
    # NaN parses happily and then compares false against every bound, so a
    # limit set to NaN would disable that limit instead of tightening it.
    if math.isnan(value):
        raise ConfigError(f"{name}={raw!r} is not a usable limit")
    return value
