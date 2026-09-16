# -*- coding: utf-8 -*-
"""Tests for MT5 live read-only data mode (Run 23).

Covers:
- use_live_data_mode() safety when MetaTrader5 is not importable (CI/Linux).
- execute_order() refusal while in live read-only mode.
- /mt5/mode endpoint reporting.
- get_ohlc() timeframe mapping (M5/H4/fallback).
- get_positions() live path with realistic fake TradePosition objects
  (no `margin`, no `entry` — the real MT5 object has neither).

All tests run without the MetaTrader5 package installed.
"""

from __future__ import annotations

import importlib
import sys
import types
from types import SimpleNamespace

import pytest

connector = importlib.import_module("mt5.connector")


@pytest.fixture(autouse=True)
def _reset_mode():
    """Ensure each test starts and ends with a clean connector state."""
    connector._live_mode = False
    connector._mt5_available = False
    yield
    connector._live_mode = False
    connector._mt5_available = False


# ---------------------------------------------------------------------------
# F1 — use_live_data_mode()
# ---------------------------------------------------------------------------


class TestUseLiveDataMode:
    def test_returns_false_when_package_missing(self, monkeypatch):
        """ImportError must be swallowed and return False (no raise)."""
        real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __import__

        def fake_import(name, *args, **kwargs):
            if name == "MetaTrader5":
                raise ImportError("simulated missing MetaTrader5")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", fake_import)
        monkeypatch.delitem(sys.modules, "MetaTrader5", raising=False)

        assert connector.use_live_data_mode() is False
        assert connector.is_live_mode() is False

    def test_sets_live_mode_when_initialize_succeeds(self, monkeypatch):
        fake_mt5 = types.ModuleType("MetaTrader5")
        fake_mt5.initialize = lambda *a, **k: True
        monkeypatch.setitem(sys.modules, "MetaTrader5", fake_mt5)

        assert connector.use_live_data_mode() is True
        assert connector.is_live_mode() is True

    def test_initialize_exception_never_breaks_startup(self, monkeypatch):
        """A dead terminal raising inside initialize() must return False, not raise."""
        fake_mt5 = types.ModuleType("MetaTrader5")

        def exploding_initialize(*a, **k):
            raise OSError("terminal not found")

        fake_mt5.initialize = exploding_initialize
        monkeypatch.setitem(sys.modules, "MetaTrader5", fake_mt5)

        assert connector.use_live_data_mode() is False
        assert connector.is_live_mode() is False


# ---------------------------------------------------------------------------
# F2 — execute_order() refusal in live read-only mode
# ---------------------------------------------------------------------------


class TestExecuteOrderGuard:
    def test_live_mode_refuses_and_never_calls_order_send(self, monkeypatch):
        """In live mode execute_order must refuse without touching mt5.order_send."""
        calls = []

        def exploding_order_send(*args, **kwargs):
            calls.append(args)
            raise AssertionError("order_send must NOT be called in read-only mode")

        fake_mt5 = types.ModuleType("MetaTrader5")
        fake_mt5.order_send = exploding_order_send
        monkeypatch.setitem(sys.modules, "MetaTrader5", fake_mt5)

        connector._live_mode = True
        result = connector.execute_order(
            {"symbol": "EURUSDc", "side": "BUY", "quantity": 0.01, "order_type": "MARKET"}
        )

        assert result["success"] is False
        assert result["order_id"] is None
        assert "read-only" in result["message"].lower()
        assert calls == []

    def test_paper_mode_still_simulates(self):
        """Default (paper) mode keeps the simulated success path."""
        connector._live_mode = False
        result = connector.execute_order(
            {"symbol": "EURUSD", "side": "BUY", "quantity": 0.1, "order_type": "MARKET"}
        )
        assert result["success"] is True
        assert result["order_id"] is not None


# ---------------------------------------------------------------------------
# F4 — /mt5/mode endpoint
# ---------------------------------------------------------------------------


class TestModeEndpoint:
    def test_paper_mode_report(self):
        from mt5.endpoints import get_mode

        result = _run(get_mode())
        assert result == {"live_data": False, "execution": "paper"}

    def test_live_mode_report(self):
        from mt5.endpoints import get_mode

        connector._live_mode = True
        result = _run(get_mode())
        assert result == {"live_data": True, "execution": "disabled (read-only)"}


def _run(coro):
    """Run a coroutine without requiring pytest-asyncio."""
    import asyncio

    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# BUG 3 — get_ohlc() timeframe mapping
# ---------------------------------------------------------------------------


class TestOhlcTimeframeMapping:
    @pytest.mark.parametrize(
        "tf_name,expected_attr",
        [
            ("M5", "TIMEFRAME_M5"),
            ("m15", "TIMEFRAME_M15"),
            ("H4", "TIMEFRAME_H4"),
            ("D1", "TIMEFRAME_D1"),
        ],
    )
    def test_timeframe_passed_to_mt5(self, monkeypatch, tf_name, expected_attr):
        captured = {}

        def fake_copy(symbol, timeframe, start, count):
            captured["symbol"] = symbol
            captured["timeframe"] = timeframe
            return None  # no rates needed — we only check the tf argument

        fake_mt5 = types.ModuleType("MetaTrader5")
        fake_mt5.copy_rates_from_pos = fake_copy
        # Distinct sentinel values per timeframe constant
        for name in (
            "TIMEFRAME_M1",
            "TIMEFRAME_M5",
            "TIMEFRAME_M15",
            "TIMEFRAME_M30",
            "TIMEFRAME_H1",
            "TIMEFRAME_H4",
            "TIMEFRAME_D1",
            "TIMEFRAME_W1",
            "TIMEFRAME_MN1",
        ):
            setattr(fake_mt5, name, name)
        monkeypatch.setitem(sys.modules, "MetaTrader5", fake_mt5)

        connector._live_mode = True
        connector.get_ohlc("EURUSDc", tf_name, 5)

        assert captured["timeframe"] == expected_attr
        assert captured["symbol"] == "EURUSDc"

    def test_unknown_timeframe_falls_back_to_h1(self, monkeypatch):
        captured = {}

        def fake_copy(symbol, timeframe, start, count):
            captured["timeframe"] = timeframe
            return None

        fake_mt5 = types.ModuleType("MetaTrader5")
        fake_mt5.copy_rates_from_pos = fake_copy
        fake_mt5.TIMEFRAME_H1 = "H1_SENTINEL"
        for name in (
            "TIMEFRAME_M1",
            "TIMEFRAME_M5",
            "TIMEFRAME_M15",
            "TIMEFRAME_M30",
            "TIMEFRAME_H4",
            "TIMEFRAME_D1",
            "TIMEFRAME_W1",
            "TIMEFRAME_MN1",
        ):
            setattr(fake_mt5, name, name)
        monkeypatch.setitem(sys.modules, "MetaTrader5", fake_mt5)

        connector._live_mode = True
        connector.get_ohlc("EURUSDc", "NOT_A_TF", 5)

        assert captured["timeframe"] == "H1_SENTINEL"


# ---------------------------------------------------------------------------
# BUG 4 — get_positions() live path with realistic TradePosition fakes
# ---------------------------------------------------------------------------


def _fake_position(ticket: int = 1, reason: int = 0):
    """Build a SimpleNamespace mirroring the REAL MT5 TradePosition fields.

    The real object has no ``margin`` and no ``entry`` attributes.
    """
    return SimpleNamespace(
        ticket=ticket,
        symbol="XAUUSDc",
        type=0,
        volume=0.01,
        price_open=4347.5,
        price_current=4346.1,
        swap=0.0,
        profit=-15.77,
        reason=reason,
        time=1789588924,
        time_update=1789589000,
    )


class TestLivePositions:
    def test_positions_parsed_without_margin_or_entry(self, monkeypatch):
        fake_mt5 = types.ModuleType("MetaTrader5")
        fake_mt5.positions_get = lambda *a, **k: (
            _fake_position(101),
            _fake_position(102, reason=3),
        )
        fake_mt5.POSITION_REASON_CLIENT = 0
        monkeypatch.setitem(sys.modules, "MetaTrader5", fake_mt5)

        connector._live_mode = True
        positions = connector.get_positions()

        assert len(positions) == 2
        first = positions[0]
        assert first.ticket == 101
        assert first.symbol == "XAUUSDc"
        assert first.side == "BUY"
        assert first.margin == 0.0
        assert first.entry == "POSITION_ENTRY_IN"
        assert positions[1].entry == "POSITION_ENTRY_OUT"

    def test_positions_none_returns_empty(self, monkeypatch):
        fake_mt5 = types.ModuleType("MetaTrader5")
        fake_mt5.positions_get = lambda *a, **k: None
        fake_mt5.POSITION_REASON_CLIENT = 0
        monkeypatch.setitem(sys.modules, "MetaTrader5", fake_mt5)

        connector._live_mode = True
        assert connector.get_positions() == []


# ---------------------------------------------------------------------------
# BUG 1/2 — get_tick() and get_symbol_info() live parsing
# ---------------------------------------------------------------------------


class TestLiveTickAndSymbol:
    def test_tick_built_from_symbol_info_tick(self, monkeypatch):
        fake_mt5 = types.ModuleType("MetaTrader5")
        # The REAL Tick object has NO `symbol` attribute.
        fake_mt5.symbol_info_tick = lambda symbol: SimpleNamespace(
            bid=1.15327,
            ask=1.15344,
            last=0.0,
            volume=0,
            time=1789588924,
        )
        monkeypatch.setitem(sys.modules, "MetaTrader5", fake_mt5)

        connector._live_mode = True
        tick = connector.get_tick("EURUSDc")

        assert tick is not None
        assert tick.symbol == "EURUSDc"
        assert tick.bid == 1.15327
        assert tick.ask == 1.15344

    def test_tick_none_returns_none(self, monkeypatch):
        fake_mt5 = types.ModuleType("MetaTrader5")
        fake_mt5.symbol_info_tick = lambda symbol: None
        monkeypatch.setitem(sys.modules, "MetaTrader5", fake_mt5)

        connector._live_mode = True
        assert connector.get_tick("EURUSDc") is None

    def test_symbol_info_accepts_tuple(self, monkeypatch):
        fake_mt5 = types.ModuleType("MetaTrader5")
        fake_symbol = SimpleNamespace(
            name="EURUSDc",
            bid=1.15328,
            ask=1.15344,
            spread=16,
            digits=5,
            trade_contract_size=100000.0,
            point=0.00001,
            trade_mode=4,
            currency_profit="USD",
            currency_margin="USD",
        )
        # REAL symbols_get() returns a TUPLE, not a list.
        fake_mt5.symbols_get = lambda symbol=None: (fake_symbol,)
        monkeypatch.setitem(sys.modules, "MetaTrader5", fake_mt5)

        connector._live_mode = True
        info = connector.get_symbol_info("EURUSDc")

        assert info is not None
        assert info.symbol == "EURUSDc"
        assert info.spread == 16

    def test_symbol_info_none_returns_none(self, monkeypatch):
        fake_mt5 = types.ModuleType("MetaTrader5")
        fake_mt5.symbols_get = lambda symbol=None: None
        monkeypatch.setitem(sys.modules, "MetaTrader5", fake_mt5)

        connector._live_mode = True
        assert connector.get_symbol_info("EURUSDc") is None


# ---------------------------------------------------------------------------
# Execution engine — native order_send guard (defense in depth)
# ---------------------------------------------------------------------------


class TestEngineNativeGuard:
    def test_engine_blocks_native_send_in_live_mode(self, monkeypatch):
        """ExecutionEngine._send_to_mt5 must refuse while live-data mode is on."""
        from execution.engine import ExecutionEngine, OrderRequest

        def exploding_order_send(*args, **kwargs):
            raise AssertionError("mt5.order_send must NOT be called in read-only mode")

        fake_mt5 = types.ModuleType("MetaTrader5")
        fake_mt5.order_send = exploding_order_send
        fake_mt5.TRADE_ACTION_DEAL = 1
        fake_mt5.ORDER_TYPE_BUY = 0
        fake_mt5.ORDER_TYPE_SELL = 1
        fake_mt5.ORDER_TIME_GTC = 0
        monkeypatch.setitem(sys.modules, "MetaTrader5", fake_mt5)

        connector._live_mode = True
        engine = ExecutionEngine(mt5_connector=None)
        request = OrderRequest(symbol="EURUSDc", order_type="BUY", volume=0.01)
        result = engine._send_to_mt5(request)

        assert result["success"] is False
        assert "read-only" in result["message"].lower()
