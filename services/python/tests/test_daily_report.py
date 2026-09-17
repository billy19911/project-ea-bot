# -*- coding: utf-8 -*-
"""Tests for the daily report aggregator (UI/UX ide #9).

The aggregator is a pure function over normalized deals, so it is tested
without MT5. The honesty rules pinned here:

- only closed deals (entry 1/3) count towards wins/losses;
- net includes commission and swap of every deal in the period;
- empty input produces an honest empty report (no invented numbers);
- win_rate is None when nothing was decided — never a fake 0%.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.reports.daily import aggregate_deals, normalize_deal  # noqa: E402


def _deal(ts, entry, profit, symbol="XAUUSD", commission=0.0, swap=0.0, volume=0.01):
    return {
        "ts": ts,
        "ticket": ts,
        "symbol": symbol,
        "entry": entry,
        "volume": volume,
        "price": 1.0,
        "profit": profit,
        "commission": commission,
        "swap": swap,
    }


def _now_ts(minutes_ago=0):
    import time

    return int(time.time()) - minutes_ago * 60


def test_normalize_deal_handles_object_attributes():
    class D:
        time = 1234567890
        ticket = 42
        symbol = "EURUSD"
        entry = 1
        volume = 0.5
        price = 1.2345
        profit = 10.5
        commission = -0.25
        swap = 0.0

    out = normalize_deal(D())
    assert out["symbol"] == "EURUSD"
    assert out["entry"] == 1
    assert out["profit"] == 10.5
    assert out["commission"] == -0.25


def test_normalize_deal_missing_fields_are_zero_not_fabricated():
    out = normalize_deal(object())
    assert out["ts"] == 0
    assert out["symbol"] == ""
    assert out["profit"] == 0.0
    assert out["volume"] == 0.0


def test_empty_input_gives_honest_empty_report():
    r = aggregate_deals([], days=7)
    assert r["totals"]["deals"] == 0
    assert r["totals"]["closed"] == 0
    assert r["totals"]["net"] == 0.0
    assert r["totals"]["win_rate"] is None  # tidak ada yang diputuskan
    assert r["daily"] == []
    assert r["symbols"] == []


def test_only_closed_deals_count_as_win_loss():
    # entry=0 (IN) tidak dihitung menang/kalah meski profit field terisi
    deals = [
        _deal(_now_ts(10), 0, 999.0),  # open — must NOT count as win
        _deal(_now_ts(9), 1, 50.0),  # close win
        _deal(_now_ts(8), 3, -20.0),  # close by — loss
    ]
    r = aggregate_deals(deals, days=7)
    t = r["totals"]
    assert t["deals"] == 3
    assert t["closed"] == 2
    assert t["wins"] == 1
    assert t["losses"] == 1
    assert t["win_rate"] == 0.5
    assert t["net"] == 999.0 + 50.0 - 20.0


def test_net_includes_commission_and_swap():
    deals = [_deal(_now_ts(5), 1, 100.0, commission=-1.5, swap=-0.5)]
    r = aggregate_deals(deals, days=7)
    assert r["totals"]["net"] == 98.0


def test_breakeven_is_neither_win_nor_loss():
    deals = [_deal(_now_ts(5), 1, 0.0)]
    r = aggregate_deals(deals, days=7)
    day = r["daily"][0]
    assert day["breakeven"] == 1
    assert day["wins"] == 0
    assert day["losses"] == 0
    assert day["win_rate"] is None


def test_deals_older_than_window_are_excluded():
    old = _deal(_now_ts(60 * 24 * 10), 1, 500.0)  # 10 days ago
    recent = _deal(_now_ts(5), 1, 10.0)
    r = aggregate_deals([old, recent], days=7)
    assert r["totals"]["deals"] == 1
    assert r["totals"]["net"] == 10.0


def test_best_and_worst_day_tracked():
    import time

    now = int(time.time())
    yesterday = now - 24 * 3600
    deals = [
        _deal(now - 60, 1, 30.0),  # hari ini
        _deal(yesterday, 1, -10.0),  # kemarin
    ]
    r = aggregate_deals(deals, days=7)
    assert r["totals"]["best_day"]["net"] == 30.0
    assert r["totals"]["worst_day"]["net"] == -10.0


def test_symbols_sorted_by_absolute_net():
    deals = [
        _deal(_now_ts(5), 1, 10.0, symbol="EURUSD"),
        _deal(_now_ts(6), 1, -100.0, symbol="XAUUSD"),
    ]
    r = aggregate_deals(deals, days=7)
    assert r["symbols"][0]["symbol"] == "XAUUSD"  # |−100| > 10
    assert r["symbols"][0]["win_rate"] == 0.0
    assert r["symbols"][1]["win_rate"] == 1.0


def test_build_daily_report_reports_unavailable_without_live_mode():
    from src.reports.daily import build_daily_report

    # In the test environment MT5 live mode is off → honest failure, no zeros.
    out = build_daily_report(days=7)
    assert out["ok"] is False
    assert isinstance(out["reason"], str) and out["reason"]
    assert "totals" not in out


def test_days_are_clamped():
    from src.reports.daily import build_daily_report

    out = build_daily_report(days=9999)
    assert out["days"] <= 90
