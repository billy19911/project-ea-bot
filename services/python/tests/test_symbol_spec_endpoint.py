# -*- coding: utf-8 -*-
"""Tests for SymbolSpec endpoint (Phase 33)."""

from fastapi.testclient import TestClient

from src.main import app

client = TestClient(app)

REQUIRED_KEYS = {
    "symbol",
    "digits",
    "point",
    "tick_size",
    "tick_value",
    "contract_size",
    "volume_min",
    "volume_max",
    "volume_step",
    "stops_level",
    "freeze_level",
    "filling_mode",
    "margin_mode",
    "spread",
}


def test_symbol_spec_default() -> None:
    res = client.get("/market/symbol-spec")
    assert res.status_code == 200
    spec = res.json()
    assert REQUIRED_KEYS <= set(spec)
    assert spec["symbol"] == "XAUUSD"


def test_symbol_spec_custom_symbol() -> None:
    res = client.get("/market/symbol-spec?symbol=EURUSD")
    assert res.status_code == 200
    spec = res.json()
    assert spec["symbol"] == "EURUSD"
    assert REQUIRED_KEYS <= set(spec)
