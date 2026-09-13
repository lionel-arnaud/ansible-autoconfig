"""ACCEPTANCE E1-E3 — live trading must be unreachable by accident."""
from __future__ import annotations

import pathlib

import pytest

from trading_agent.config import Config

PAPER = "https://paper-api.alpaca.markets"
LIVE = "https://api.alpaca.markets"


def test_e1_default_endpoint_is_paper(monkeypatch):
    monkeypatch.delenv("TRADING_MODE", raising=False)
    monkeypatch.delenv("LIVE_CONFIRMED", raising=False)
    assert PAPER in Config.from_env(_require_secrets=False).endpoint


def test_e2_mode_alone_does_not_reach_live(monkeypatch):
    """One variable must not be enough. A typo, a stale shell, a copied unit
    file — any single mistake would otherwise put real money on the line."""
    monkeypatch.setenv("TRADING_MODE", "live")
    monkeypatch.delenv("LIVE_CONFIRMED", raising=False)
    assert PAPER in Config.from_env(_require_secrets=False).endpoint


def test_e2_confirmation_alone_does_not_reach_live(monkeypatch):
    monkeypatch.delenv("TRADING_MODE", raising=False)
    monkeypatch.setenv("LIVE_CONFIRMED", "yes")
    assert PAPER in Config.from_env(_require_secrets=False).endpoint


def test_e2_live_requires_both_signals(monkeypatch):
    monkeypatch.setenv("TRADING_MODE", "live")
    monkeypatch.setenv("LIVE_CONFIRMED", "yes")
    assert LIVE in Config.from_env(_require_secrets=False).endpoint


def test_e3_live_url_is_not_hardcoded_outside_config():
    """Only config.py may name the live endpoint. Anywhere else is a path that
    could bypass the two-signal gate."""
    root = pathlib.Path(__file__).resolve().parent.parent / "trading_agent"
    offenders = [
        p.name
        for p in root.rglob("*.py")
        if p.name != "config.py" and "api.alpaca.markets" in p.read_text()
    ]
    assert not offenders, f"live endpoint referenced outside config.py: {offenders}"
