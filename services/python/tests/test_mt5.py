# -*- coding: utf-8 -*-
"""Tests for MT5 data models and retrieval functions."""

from datetime import datetime, timezone

import pytest

from src.mt5.models import OHLC, SymbolInfo, Tick, Timeframe
from src.mt5.retrieval import _TIMEFRAME_MAP, get_ohlc, get_symbol_info, get_tick

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


def test_symbol_info_creation():
    s = SymbolInfo(
        symbol="BTCUSD",
        digits=2,
        point=0.01,
        bid=108500.0,
        ask=108500.5,
        spread=5,
        contract_size=1.0,
        volume_min=0.01,
        volume_max=100.0,
        tick_value=1.0,
        tick_size=0.01,
    )
    assert s.symbol == "BTCUSD"
    assert s.bid < s.ask
    assert s.spread == 5


def test_tick_creation():
    now = datetime.now(timezone.utc)
    t = Tick(symbol="EURUSD", bid=1.0850, ask=1.0852, last=1.0851, volume=1.5, time=now)
    assert t.symbol == "EURUSD"
    assert t.bid < t.ask


def test_ohlc_creation():
    now = datetime.now(timezone.utc)
    c = OHLC(
        symbol="BTCUSD",
        timeframe=Timeframe.M1,
        open=108000.0,
        high=108500.0,
        low=107800.0,
        close=108300.0,
        tick_volume=100.0,
        spread=5,
        real_volume=5000.0,
        time=now,
    )
    assert c.high >= c.low
    assert c.timeframe == Timeframe.M1


# ---------------------------------------------------------------------------
# Retrieval — graceful degradation when MT5 absent
# ---------------------------------------------------------------------------


def test_timeframe_map_populated():
    assert len(_TIMEFRAME_MAP) == 7
    assert all(v != 0 for v in _TIMEFRAME_MAP.values())


def test_get_symbol_info_raises_without_mt5(monkeypatch):
    import src.mt5.retrieval as mod

    monkeypatch.setattr(mod, "mt5", None)
    with pytest.raises(RuntimeError, match="MetaTrader5"):
        get_symbol_info("BTCUSD")


def test_get_tick_raises_without_mt5(monkeypatch):
    import src.mt5.retrieval as mod

    monkeypatch.setattr(mod, "mt5", None)
    with pytest.raises(RuntimeError, match="MetaTrader5"):
        get_tick("BTCUSD")


def test_get_ohlc_raises_without_mt5(monkeypatch):
    import src.mt5.retrieval as mod

    monkeypatch.setattr(mod, "mt5", None)
    with pytest.raises(RuntimeError, match="MetaTrader5"):
        get_ohlc("BTCUSD")
