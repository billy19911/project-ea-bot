# -*- coding: utf-8 -*-
"""Tests for the per-cycle TradeManager (BEP / progressive / trailing wiring)."""

from __future__ import annotations

from execution.sltp_manager import SLTPConfig
from monitoring.trade_manager import TradeManager


class _Tick:
    def __init__(self, bid, ask):
        self.bid = bid
        self.ask = ask


def _manager(positions, ticks, atr=10.0, applied=None, config=None):
    calls = applied if applied is not None else []

    def apply(ticket, symbol, sl, tp):
        calls.append({"ticket": ticket, "symbol": symbol, "sl": sl, "tp": tp})
        return {"success": True, "error_code": 0, "message": "ok"}

    return (
        TradeManager(
            config=config
            or SLTPConfig(
                breakeven_enabled=True,
                progressive_enabled=True,
                trailing_enabled=True,
            ),
            position_reader=lambda: positions,
            tick_reader=lambda sym: ticks.get(sym),
            atr_reader=lambda sym: atr,
            apply_sltp=apply,
        ),
        calls,
    )


def test_manage_applies_breakeven_on_profit():
    positions = [
        {
            "ticket": 111,
            "symbol": "XAUUSD",
            "side": "buy",
            "volume": 0.1,
            "entry_price": 2000.0,
            "sl": 1990.0,
            "tp": 2030.0,
        }
    ]
    ticks = {"XAUUSD": _Tick(bid=2012.0, ask=2012.2)}
    mgr, calls = _manager(positions, ticks)

    applied = mgr.manage()

    assert len(applied) == 1
    assert applied[0]["ticket"] == 111
    assert applied[0]["reason"] in ("breakeven", "tp1_lock", "trailing")
    assert applied[0]["sent"] is True
    assert len(calls) == 1
    assert calls[0]["ticket"] == 111
    # Never widens risk: new SL must be above the old 1990.
    assert calls[0]["sl"] > 1990.0


def test_manage_no_change_when_not_in_profit():
    positions = [
        {
            "ticket": 222,
            "symbol": "XAUUSD",
            "side": "buy",
            "entry_price": 2000.0,
            "sl": 1990.0,
            "tp": 2030.0,
        }
    ]
    ticks = {"XAUUSD": _Tick(bid=1995.0, ask=1995.2)}  # below entry
    mgr, calls = _manager(positions, ticks)

    applied = mgr.manage()

    assert applied == []
    assert calls == []
    assert mgr.snapshot()["counts"]["skipped"] >= 1


def test_manage_handles_multiple_positions_independently():
    positions = [
        {
            "ticket": 1,
            "symbol": "XAUUSD",
            "side": "buy",
            "entry_price": 2000.0,
            "sl": 1990.0,
            "tp": 0.0,
        },
        {
            "ticket": 2,
            "symbol": "BTCUSD",
            "side": "sell",
            "entry_price": 60000.0,
            "sl": 61000.0,
            "tp": 0.0,
        },
    ]
    ticks = {
        "XAUUSD": _Tick(bid=2020.0, ask=2020.2),
        "BTCUSD": _Tick(bid=58000.0, ask=58005.0),
    }
    # Realistic per-symbol ATR: XAU ~10, BTC ~1000.
    atr_by_symbol = {"XAUUSD": 10.0, "BTCUSD": 1000.0}
    calls = []

    def apply(ticket, symbol, sl, tp):
        calls.append({"ticket": ticket, "symbol": symbol, "sl": sl, "tp": tp})
        return {"success": True, "error_code": 0, "message": "ok"}

    mgr = TradeManager(
        config=SLTPConfig(
            breakeven_enabled=True,
            progressive_enabled=True,
            trailing_enabled=True,
        ),
        position_reader=lambda: positions,
        tick_reader=lambda sym: ticks.get(sym),
        atr_reader=lambda sym: atr_by_symbol.get(sym, 0.0),
        apply_sltp=apply,
    )

    applied = mgr.manage()

    assert len(applied) == 2
    tickets = {a["ticket"] for a in applied}
    assert tickets == {1, 2}
    # Both tighten risk.
    by_ticket = {c["ticket"]: c for c in calls}
    assert by_ticket[1]["sl"] > 1990.0
    assert by_ticket[2]["sl"] < 61000.0


def test_manage_is_fail_safe_when_send_fails():
    positions = [
        {
            "ticket": 333,
            "symbol": "XAUUSD",
            "side": "buy",
            "entry_price": 2000.0,
            "sl": 1990.0,
        }
    ]
    ticks = {"XAUUSD": _Tick(bid=2020.0, ask=2020.2)}

    def failing_apply(ticket, symbol, sl, tp):
        return {"success": False, "error_code": 403, "message": "not armed"}

    mgr = TradeManager(
        config=SLTPConfig(),
        position_reader=lambda: positions,
        tick_reader=lambda s: ticks.get(s),
        atr_reader=lambda s: 10.0,
        apply_sltp=failing_apply,
    )

    applied = mgr.manage()

    assert len(applied) == 1
    assert applied[0]["sent"] is False
    assert applied[0]["error_code"] == 403
    assert mgr.snapshot()["counts"]["errors"] >= 1


def test_manage_survives_position_read_error():
    def boom():
        raise RuntimeError("broker down")

    mgr = TradeManager(position_reader=boom)
    applied = mgr.manage()
    assert applied == []
    assert mgr.snapshot()["counts"]["errors"] >= 1


def test_snapshot_shape():
    mgr, _ = _manager([], {})
    snap = mgr.snapshot()
    assert set(snap.keys()) == {"enabled", "counts", "recent"}
    assert "evaluated" in snap["counts"]
