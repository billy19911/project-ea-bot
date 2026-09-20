# -*- coding: utf-8 -*-
"""Tests for market data health endpoint (Phase 32)."""

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
