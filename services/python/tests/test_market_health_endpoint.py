# -*- coding: utf-8 -*-
"""Tests for market data health endpoint (Phase 32)."""

import datetime

from fastapi.testclient import TestClient

from src.main import app

client = TestClient(app)


def test_market_health_default() -> None:
    res = client.get("/market/health")
    assert res.status_code == 200
    data = res.json()
    assert data["symbol"] == "XAUUSD"
    assert isinstance(data["tick_age_ms"], int)
    assert isinstance(data["status"], str)
    assert data["feed_connected"] in (True, False)


def test_market_health_custom_symbol() -> None:
    res = client.get("/market/health?symbol=EURUSD")
    assert res.status_code == 200
    assert res.json()["symbol"] == "EURUSD"


# ---------------------------------------------------------------------------
# Regression: get_ohlc returns a LIST of bars, and connector times are naive
# LOCAL datetimes. The old health.py treated the list as a single OHLC object
# and compared against a UTC now — so every symbol reported DISCONNECTED.
# ---------------------------------------------------------------------------


class _Tick:
    def __init__(self, t: float, bid: float, ask: float) -> None:
        self.time = t
        self.bid = bid
        self.ask = ask


class _Bar:
    def __init__(self, t: float) -> None:
        self.time = t


def test_health_connected_with_list_ohlc(monkeypatch) -> None:
    """A list of bars + fresh local timestamps must report CONNECTED/HEALTHY."""
    import src.market.health as health

    now = datetime.datetime.now()
    monkeypatch.setattr(health, "get_tick", lambda s: _Tick(now, 4165.0, 4165.3))
    monkeypatch.setattr(
        health,
        "get_ohlc",
        lambda s: [_Bar(now - datetime.timedelta(hours=1)), _Bar(now)],
    )

    result = health.compute_market_data_health("XAUUSD")
    assert result["feed_connected"] is True
    assert result["status"] == "HEALTHY"
    assert result["tick_age_ms"] == 0
    assert result["bar_age_ms"] == 0
    assert result["last_successful_update"]  # non-empty ISO timestamp


def test_health_stale_when_bar_old(monkeypatch) -> None:
    """An old last bar → STALE (still connected), not DISCONNECTED."""
    import src.market.health as health

    now = datetime.datetime.now()
    monkeypatch.setattr(health, "get_tick", lambda s: _Tick(now, 4165.0, 4165.3))
    monkeypatch.setattr(
        health,
        "get_ohlc",
        lambda s: [_Bar(now - datetime.timedelta(minutes=10))],
    )

    result = health.compute_market_data_health("XAUUSD")
    assert result["feed_connected"] is True
    assert result["status"] == "STALE"


def test_health_disconnected_when_missing(monkeypatch) -> None:
    """No tick/bar → honest DISCONNECTED."""
    import src.market.health as health

    monkeypatch.setattr(health, "get_tick", lambda s: None)
    monkeypatch.setattr(health, "get_ohlc", lambda s: [])

    result = health.compute_market_data_health("XAUUSD")
    assert result["feed_connected"] is False
    assert result["status"] == "DISCONNECTED"


def test_health_negative_age_is_clamped(monkeypatch) -> None:
    """Future-dated data (clock skew) clamps age to 0, never negative."""
    import src.market.health as health

    now = datetime.datetime.now()
    future = now + datetime.timedelta(hours=2)
    monkeypatch.setattr(health, "get_tick", lambda s: _Tick(future, 4165.0, 4165.3))
    monkeypatch.setattr(health, "get_ohlc", lambda s: [_Bar(future)])

    result = health.compute_market_data_health("XAUUSD")
    assert result["tick_age_ms"] >= 0
    assert result["bar_age_ms"] >= 0
