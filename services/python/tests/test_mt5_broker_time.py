# -*- coding: utf-8 -*-
"""Broker-time conversion (WIB-vs-UTC bug) — regression tests.

Root cause recap: MT5 reports epoch seconds in *server wall-clock* space.
A live probe of the attached terminals measured the offset as exactly +3 h
(raw tick/bar/deal epoch minus true UTC epoch = 10800 s), and the same epoch
space is used for inputs (``copy_rates_from`` / ``copy_rates_range`` /
``history_deals_get``). The connector used to render raw epochs with
``datetime.fromtimestamp()`` (naive LOCAL) while the freshness gate treats
naive datetimes as UTC — on a UTC+7 host every bar looked ~10 h in the
future and the committee rejected all data with
``clock_anomaly_received_before_bar``.

The fix (``mt5.broker_time``): one fixed-offset conversion —
out ``raw - 3 h`` -> aware UTC; in ``true UTC + 3 h`` -> raw epoch.

These tests pin the conversion at the helper level and at every
connector/retrieval site (tick, OHLC, history window, range, data-info,
positions, orders) using fake MT5 modules — no terminal required.
"""

from __future__ import annotations

import importlib
import sys
import types
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

broker_time = importlib.import_module("mt5.broker_time")
connector = importlib.import_module("mt5.connector")
retrieval = importlib.import_module("mt5.retrieval")
models = importlib.import_module("mt5.models")

BROKER_OFFSET = timedelta(hours=3)
RAW = 1789588924  # a fixed epoch; the exact value is irrelevant


def _from_broker(raw: float) -> datetime:
    """Expected aware-UTC value for a raw MT5 epoch (independent of the helper)."""
    return datetime.fromtimestamp(raw, tz=timezone.utc) - BROKER_OFFSET


def _fake_mt5(**attrs) -> types.ModuleType:
    mod = types.ModuleType("MetaTrader5")
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
        setattr(mod, name, name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    return mod


@pytest.fixture(autouse=True)
def _reset_connector_mode():
    connector._live_mode = False
    yield
    connector._live_mode = False


# ---------------------------------------------------------------------------
# 1. Helper — mt5.broker_time
# ---------------------------------------------------------------------------


class TestBrokerTimeHelper:
    def test_offset_constant_is_three_hours(self):
        assert broker_time.BROKER_UTC_OFFSET == BROKER_OFFSET

    def test_from_broker_epoch_is_aware_utc_minus_offset(self):
        got = broker_time.from_broker_epoch(RAW)
        assert got == _from_broker(RAW)
        assert got.tzinfo is not None
        assert got.utcoffset() == timedelta(0)

    def test_from_broker_epoch_accepts_float(self):
        assert broker_time.from_broker_epoch(float(RAW)) == _from_broker(RAW)

    def test_to_broker_epoch_aware_utc(self):
        dt = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
        assert broker_time.to_broker_epoch(dt) == int(dt.timestamp()) + 10800

    def test_to_broker_epoch_naive_is_utc(self):
        naive = datetime(2026, 9, 1, 12, 0, 0)
        expected = int(naive.replace(tzinfo=timezone.utc).timestamp()) + 10800
        assert broker_time.to_broker_epoch(naive) == expected

    def test_to_broker_epoch_aware_non_utc(self):
        wib = timezone(timedelta(hours=7))
        dt = datetime(2026, 9, 1, 19, 0, 0, tzinfo=wib)  # == 12:00 UTC
        noon_utc = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
        assert broker_time.to_broker_epoch(dt) == int(noon_utc.timestamp()) + 10800

    def test_roundtrip(self):
        dt = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
        assert broker_time.from_broker_epoch(broker_time.to_broker_epoch(dt)) == dt


# ---------------------------------------------------------------------------
# 2. Connector — live paths must emit aware-UTC times
# ---------------------------------------------------------------------------


class TestConnectorGetTick:
    def test_tick_time_aware_utc(self, monkeypatch):
        fake = _fake_mt5(
            symbol_info_tick=lambda symbol: SimpleNamespace(
                bid=1.1, ask=1.2, last=0.0, volume=0, time=RAW
            )
        )
        monkeypatch.setitem(sys.modules, "MetaTrader5", fake)

        connector._live_mode = True
        tick = connector.get_tick("EURUSDc")

        assert tick is not None
        assert tick.time == _from_broker(RAW)
        assert tick.time.tzinfo is not None


class TestConnectorGetOhlc:
    @staticmethod
    def _rates(*times):
        return [
            {
                "open": 1.0,
                "high": 2.0,
                "low": 0.5,
                "close": 1.5,
                "tick_volume": 10,
                "time": t,
            }
            for t in times
        ]

    def test_bar_time_aware_utc(self, monkeypatch):
        fake = _fake_mt5(copy_rates_from_pos=lambda s, tf, start, count: self._rates(RAW))
        monkeypatch.setitem(sys.modules, "MetaTrader5", fake)

        connector._live_mode = True
        bars = connector.get_ohlc("EURUSDc", "M5", 1)

        assert len(bars) == 1
        assert bars[0].time == _from_broker(RAW)

    def test_before_window_inputs_converted_to_broker_epoch(self, monkeypatch):
        before = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
        captured = {}

        def fake_copy(cand, tf, start, count):
            captured["start"] = start
            return []

        fake = _fake_mt5(copy_rates_from=fake_copy)
        monkeypatch.setitem(sys.modules, "MetaTrader5", fake)

        connector._live_mode = True
        connector.get_ohlc("EURUSDc", "H1", 10, before=before)

        expected = broker_time.to_broker_epoch(before) - (10 + 8) * 3600
        assert captured["start"] == expected

    def test_before_filter_compares_in_broker_space(self, monkeypatch):
        before = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
        broker_ts = broker_time.to_broker_epoch(before)
        fake = _fake_mt5(
            copy_rates_from=lambda cand, tf, start, count: self._rates(broker_ts - 3600)
        )
        monkeypatch.setitem(sys.modules, "MetaTrader5", fake)

        connector._live_mode = True
        bars = connector.get_ohlc("EURUSDc", "H1", 1, before=before)

        assert len(bars) == 1
        assert bars[0].time == before - timedelta(hours=1)


class TestConnectorGetOhlcRange:
    def test_range_input_and_output_in_broker_space(self, monkeypatch):
        start = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 9, 1, 6, 0, 0, tzinfo=timezone.utc)
        captured = {}

        def fake_range(cand, tf, s, e):
            captured["start"] = s
            captured["end"] = e
            return [
                {
                    "open": 1.0,
                    "high": 2.0,
                    "low": 0.5,
                    "close": 1.5,
                    "tick_volume": 10,
                    "time": broker_time.to_broker_epoch(start),
                }
            ]

        fake = _fake_mt5(copy_rates_range=fake_range)
        monkeypatch.setitem(sys.modules, "MetaTrader5", fake)

        connector._live_mode = True
        bars = connector.get_ohlc_range("EURUSDc", "H1", start, end)

        assert captured["start"] == broker_time.to_broker_epoch(start)
        assert captured["end"] == broker_time.to_broker_epoch(end)
        assert len(bars) == 1
        assert bars[0].time == start


class TestConnectorGetDataInfo:
    def test_times_aware_utc_and_probe_converted(self, monkeypatch):
        newest_raw = RAW
        oldest_raw = RAW - 3600 * 24 * 365
        captured = {}

        def fake_from(cand, tf, start, count):
            captured["start"] = start
            return [{"time": oldest_raw}]

        fake = _fake_mt5(
            copy_rates_from=fake_from,
            copy_rates_from_pos=lambda s, tf, start, count: [{"time": newest_raw}],
        )
        monkeypatch.setitem(sys.modules, "MetaTrader5", fake)

        connector._live_mode = True
        info = connector.get_data_info("EURUSDc", "H1")

        assert info["newest_bar"] == _from_broker(newest_raw)
        assert info["oldest_bar"] == _from_broker(oldest_raw)
        # The 5-year depth probe must be sent in broker epoch space too.
        probe_now = broker_time.to_broker_epoch(
            datetime.now(timezone.utc) - timedelta(days=5 * 365)
        )
        assert abs(captured["start"] - probe_now) < 30


class TestConnectorGetPositions:
    def test_position_times_aware_utc(self, monkeypatch):
        raw = SimpleNamespace(
            ticket=1,
            symbol="XAUUSDc",
            type=0,
            volume=0.1,
            price_open=1.0,
            price_current=1.1,
            swap=0.0,
            profit=1.0,
            magic=0,
            sl=0.0,
            tp=0.0,
            reason=1,
            time=RAW,
            time_update=RAW + 60,
        )
        fake = _fake_mt5(positions_get=lambda: [raw], POSITION_REASON_CLIENT=0)
        monkeypatch.setitem(sys.modules, "MetaTrader5", fake)

        connector._live_mode = True
        positions = connector.get_positions()

        assert len(positions) == 1
        assert positions[0].time == _from_broker(RAW)
        assert positions[0].time_update == _from_broker(RAW + 60)


class TestConnectorGetOrders:
    def test_order_times_aware_utc(self, monkeypatch):
        raw = SimpleNamespace(
            ticket=1,
            symbol="XAUUSDc",
            type=0,
            price_open=1.0,
            price_stoplimit=0.0,
            volume_initial=0.1,
            volume_current=0.1,
            state=1,
            time_setup=RAW,
            time_expiration=RAW + 3600,
        )
        fake = _fake_mt5(orders_get=lambda: [raw])
        monkeypatch.setitem(sys.modules, "MetaTrader5", fake)

        connector._live_mode = True
        orders = connector.get_orders()

        assert len(orders) == 1
        assert orders[0].time_setup == _from_broker(RAW)
        assert orders[0].time_expiration == _from_broker(RAW + 3600)

    def test_zero_expiration_stays_none(self, monkeypatch):
        raw = SimpleNamespace(
            ticket=1,
            symbol="XAUUSDc",
            type=0,
            price_open=1.0,
            price_stoplimit=0.0,
            volume_initial=0.1,
            volume_current=0.1,
            state=1,
            time_setup=RAW,
            time_expiration=0,
        )
        fake = _fake_mt5(orders_get=lambda: [raw])
        monkeypatch.setitem(sys.modules, "MetaTrader5", fake)

        connector._live_mode = True
        orders = connector.get_orders()

        assert orders[0].time_expiration is None


# ---------------------------------------------------------------------------
# 3. Retrieval — live paths must emit aware-UTC times
# ---------------------------------------------------------------------------


class TestRetrieval:
    def test_tick_time_aware_utc(self, monkeypatch):
        fake = types.ModuleType("MetaTrader5")
        fake.symbol_info_tick = lambda symbol: SimpleNamespace(
            bid=1.0, ask=1.1, last=0.0, volume=0, time=RAW, flags=0
        )
        monkeypatch.setattr(retrieval, "mt5", fake)

        tick = retrieval.get_tick("EURUSDc")

        assert tick is not None
        assert tick.time == _from_broker(RAW)

    def test_ohlc_time_aware_utc(self, monkeypatch):
        fake = types.ModuleType("MetaTrader5")
        fake.copy_rates_from_pos = lambda s, tf, start, count: [
            {
                "open": 1.0,
                "high": 2.0,
                "low": 0.5,
                "close": 1.5,
                "tick_volume": 10.0,
                "spread": 2,
                "real_volume": 0.0,
                "time": RAW,
            }
        ]
        monkeypatch.setattr(retrieval, "mt5", fake)

        bars = retrieval.get_ohlc("EURUSDc", models.Timeframe.M1, 1)

        assert len(bars) == 1
        assert bars[0].time == _from_broker(RAW)

    def test_since_converted_to_broker_epoch(self, monkeypatch):
        since = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
        captured = {}

        def fake_copy(symbol, tf, timestamp, count):
            captured["timestamp"] = timestamp
            return []

        fake = types.ModuleType("MetaTrader5")
        fake.copy_rates_from = fake_copy
        monkeypatch.setattr(retrieval, "mt5", fake)

        retrieval.get_ohlc("EURUSDc", models.Timeframe.M1, 1, since=since)

        assert captured["timestamp"] == broker_time.to_broker_epoch(since)


# ---------------------------------------------------------------------------
# 4. Market health — ages computed in aware-UTC space
# ---------------------------------------------------------------------------


class _Tick:
    def __init__(self, t: datetime, bid: float = 1.0, ask: float = 1.1) -> None:
        self.time = t
        self.bid = bid
        self.ask = ask


class _Bar:
    def __init__(self, t: datetime) -> None:
        self.time = t


class TestMarketHealthAwareUtc:
    def test_last_successful_update_is_aware_utc(self, monkeypatch):
        health = importlib.import_module("src.market.health")
        now = datetime.now(timezone.utc)
        monkeypatch.setattr(health, "get_tick", lambda s: _Tick(now))
        monkeypatch.setattr(health, "get_ohlc", lambda s: [_Bar(now)])

        res = health.compute_market_data_health("XAUUSD")

        assert res["feed_connected"] is True
        assert res["status"] == "HEALTHY"
        assert res["last_successful_update"].endswith("+00:00")

    def test_aware_utc_ages_are_computed_correctly(self, monkeypatch):
        health = importlib.import_module("src.market.health")
        now = datetime.now(timezone.utc)
        monkeypatch.setattr(health, "get_tick", lambda s: _Tick(now))
        monkeypatch.setattr(health, "get_ohlc", lambda s: [_Bar(now)])

        res = health.compute_market_data_health("XAUUSD")

        assert 0 <= res["tick_age_ms"] < 1500
        assert 0 <= res["bar_age_ms"] < 1500

    def test_naive_local_times_still_work(self, monkeypatch):
        """Legacy stubs that build naive local datetimes keep working."""
        health = importlib.import_module("src.market.health")
        now_local = datetime.now()  # naive local wall time
        monkeypatch.setattr(health, "get_tick", lambda s: _Tick(now_local))
        monkeypatch.setattr(health, "get_ohlc", lambda s: [_Bar(now_local - timedelta(minutes=10))])

        res = health.compute_market_data_health("XAUUSD")

        assert res["feed_connected"] is True
        assert res["status"] == "STALE"  # 10-minute-old bar
