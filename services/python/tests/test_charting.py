# -*- coding: utf-8 -*-
"""Tests for the charting layer (Fase 1 "Pasar").

Locks in the honesty rules of the chart payload:

* candles come 1:1 from the provided bars (oldest → newest),
* indicator warm-up positions are ``None`` — never a fabricated 0.0,
* the overlay EMA values equal the engine's own EMA implementation,
* the endpoint refuses invalid input and says ``ok: false`` (with a reason)
  instead of drawing fabricated data when MT5 is not live.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src.charting.series import build_chart_payload, ema_chart_series
from src.main import app
from src.trading.indicators import ema_series


def _bars(n: int = 120) -> list[SimpleNamespace]:
    """Deterministic OHLC bars (oldest → newest)."""
    out = []
    price = 2000.0
    start = datetime(2026, 9, 1, 0, 0, 0)
    for i in range(n):
        price += ((i % 5) - 2) * 1.5 + 0.4
        o = price - 0.8
        c = price
        h = max(o, c) + 0.6
        low = min(o, c) - 0.6
        out.append(
            SimpleNamespace(
                time=start + timedelta(hours=i),
                open=round(o, 2),
                high=round(h, 2),
                low=round(low, 2),
                close=round(c, 2),
                volume=100.0 + i,
            )
        )
    return out


class TestEmaChartSeries:
    def test_warmup_is_none_not_zero(self) -> None:
        prices = [100.0 + i for i in range(30)]
        series = ema_chart_series(prices, 10)
        assert all(v is None for v in series[:9])
        assert series[9] is not None

    def test_matches_engine_ema_from_seed_index(self) -> None:
        prices = [100.0 + (i % 3) for i in range(40)]
        ours = ema_chart_series(prices, 10)
        ref = ema_series(prices, 10)
        for i in range(9, len(prices)):
            assert ours[i] == pytest.approx(ref[i])

    def test_insufficient_data_all_none(self) -> None:
        assert ema_chart_series([1.0, 2.0], 10) == [None, None]


class TestBuildChartPayload:
    def test_candles_mirror_bars(self) -> None:
        bars = _bars(50)
        payload = build_chart_payload(bars, ema_fast=5, ema_slow=20)
        assert len(payload["bars"]) == 50
        first = payload["bars"][0]
        assert first["open"] == bars[0].open
        assert first["close"] == bars[0].close
        assert first["time"] == bars[0].time.isoformat()

    def test_series_aligned_with_bars(self) -> None:
        bars = _bars(80)
        payload = build_chart_payload(bars, ema_fast=5, ema_slow=20)
        n = len(bars)
        assert len(payload["overlays"]["ema_fast"]["values"]) == n
        assert len(payload["overlays"]["ema_slow"]["values"]) == n
        assert len(payload["overlays"]["bollinger"]["upper"]) == n
        assert len(payload["panels"]["rsi"]["values"]) == n
        assert len(payload["panels"]["macd"]["line"]) == n

    def test_ema_values_real_not_zero_filled(self) -> None:
        bars = _bars(60)
        payload = build_chart_payload(bars, ema_fast=10, ema_slow=30)
        fast = payload["overlays"]["ema_fast"]["values"]
        # Warm-up = None (not 0.0); after warm-up real values near price range.
        assert all(v is None for v in fast[:9])
        assert all(v is not None and v > 100 for v in fast[9:])

    def test_invalid_periods_rejected(self) -> None:
        bars = _bars(40)
        with pytest.raises(ValueError):
            build_chart_payload(bars, ema_fast=0, ema_slow=20)
        with pytest.raises(ValueError):
            build_chart_payload(bars, ema_fast=20, ema_slow=20)

    def test_optional_panels_can_be_skipped(self) -> None:
        bars = _bars(60)
        payload = build_chart_payload(
            bars,
            ema_fast=5,
            ema_slow=20,
            include_bollinger=False,
            include_rsi=False,
            include_macd=False,
        )
        assert payload["overlays"]["bollinger"] is None
        assert payload["panels"]["rsi"] is None
        assert payload["panels"]["macd"] is None


class TestChartEndpoint:
    def setup_method(self) -> None:
        self.client = TestClient(app)

    def test_rejects_invalid_symbol(self) -> None:
        r = self.client.get("/chart/candles", params={"symbol": "not a symbol!"})
        assert r.status_code == 400

    def test_rejects_unknown_timeframe(self) -> None:
        r = self.client.get("/chart/candles", params={"symbol": "XAUUSD", "timeframe": "H7"})
        assert r.status_code == 400

    def test_rejects_ema_slow_not_above_fast(self) -> None:
        r = self.client.get(
            "/chart/candles",
            params={"symbol": "XAUUSD", "ema_fast": 50, "ema_slow": 20},
        )
        assert r.status_code == 400

    def test_rejects_out_of_range_bars(self) -> None:
        r = self.client.get("/chart/candles", params={"symbol": "XAUUSD", "bars": 5})
        assert r.status_code == 422

    def test_not_live_returns_ok_false_with_reason(self, monkeypatch) -> None:
        from src.mt5 import connector

        monkeypatch.setattr(connector, "is_live_mode", lambda: False)
        r = self.client.get("/chart/candles", params={"symbol": "XAUUSD"})
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is False
        assert "reason" in body and body["reason"]

    def test_live_mode_returns_real_series(self, monkeypatch) -> None:
        from src.mt5 import connector

        bars = _bars(100)
        monkeypatch.setattr(connector, "is_live_mode", lambda: True)
        monkeypatch.setattr(
            connector, "get_ohlc", lambda symbol, tf, count, before=None: bars[:count]
        )
        r = self.client.get(
            "/chart/candles",
            params={"symbol": "XAUUSD", "timeframe": "H1", "bars": 60},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["symbol"] == "XAUUSD"
        assert body["timeframe"] == "H1"
        assert len(body["bars"]) == 60
        assert body["provenance"]["mode"] == "live-read-only"
        assert body["provenance"]["bar_count"] == 60
        # Series aligned; warm-up None not 0.0.
        fast = body["overlays"]["ema_fast"]["values"]
        assert len(fast) == 60
        assert all(v is None for v in fast[:19])
        assert fast[19] is not None

    def test_live_mode_empty_bars_ok_false(self, monkeypatch) -> None:
        from src.mt5 import connector

        monkeypatch.setattr(connector, "is_live_mode", lambda: True)
        monkeypatch.setattr(connector, "get_ohlc", lambda symbol, tf, count, before=None: [])
        r = self.client.get("/chart/candles", params={"symbol": "NOSUCHSYM"})
        assert r.status_code == 200
        assert r.json()["ok"] is False


class TestChartAnalysisEndpoint:
    """Fase 2 — real engine analysis (entry/SL/TP) + open position levels."""

    def setup_method(self) -> None:
        self.client = TestClient(app)

    def _position(self, ticket=1, symbol="XAUUSD", sl=None, tp=None):
        return SimpleNamespace(
            ticket=ticket,
            symbol=symbol,
            side="BUY",
            quantity=0.1,
            price_open=2000.0,
            price_current=2005.0,
            sl=sl,
            tp=tp,
            profit=5.0,
        )

    def test_rejects_invalid_symbol(self) -> None:
        r = self.client.get("/chart/analysis", params={"symbol": "not a symbol!"})
        assert r.status_code == 400

    def test_rejects_unknown_timeframe(self) -> None:
        r = self.client.get("/chart/analysis", params={"symbol": "XAUUSD", "timeframe": "H7"})
        assert r.status_code == 400

    def test_not_live_returns_ok_false_with_reason(self, monkeypatch) -> None:
        from src.mt5 import connector

        monkeypatch.setattr(connector, "is_live_mode", lambda: False)
        r = self.client.get("/chart/analysis", params={"symbol": "XAUUSD"})
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is False
        assert "reason" in body and body["reason"]

    def test_live_analysis_uses_real_engine_levels(self, monkeypatch) -> None:
        from src.mt5 import connector

        bars = _bars(120)
        monkeypatch.setattr(connector, "is_live_mode", lambda: True)
        monkeypatch.setattr(
            connector, "get_ohlc", lambda symbol, tf, count, before=None: bars[:count]
        )
        monkeypatch.setattr(connector, "get_account_info", lambda: SimpleNamespace(equity=10000.0))
        monkeypatch.setattr(connector, "get_positions", lambda: [])

        r = self.client.get(
            "/chart/analysis", params={"symbol": "XAUUSD", "timeframe": "H1", "bars": 120}
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["provenance"]["engine"] == "trading.TradingEngine"
        assert body["provenance"]["stop_multiplier"] == 2.0
        assert body["provenance"]["reward_risk_ratio"] == 2.0
        assert body["provenance"]["risk_percent"] == 2.0

        analysis = body["analysis"]
        assert analysis["signal"] in {"BUY", "SELL", "HOLD"}
        assert analysis["entry"] is not None
        if analysis["signal"] != "HOLD":
            assert analysis["stop_loss"] is not None
            assert analysis["take_profit"] is not None
        assert isinstance(analysis["reason"], str) and analysis["reason"]

    def test_open_position_levels_passed_through(self, monkeypatch) -> None:
        from src.mt5 import connector

        bars = _bars(120)
        monkeypatch.setattr(connector, "is_live_mode", lambda: True)
        monkeypatch.setattr(
            connector, "get_ohlc", lambda symbol, tf, count, before=None: bars[:count]
        )
        monkeypatch.setattr(connector, "get_account_info", lambda: SimpleNamespace(equity=10000.0))
        monkeypatch.setattr(
            connector,
            "get_positions",
            lambda: [
                self._position(1, "XAUUSD", sl=1950.0, tp=2100.0),
                self._position(2, "EURUSD", sl=None, tp=None),
            ],
        )

        r = self.client.get("/chart/analysis", params={"symbol": "XAUUSD"})
        body = r.json()
        assert body["ok"] is True
        assert len(body["positions"]) == 1  # EURUSD filtered out
        pos = body["positions"][0]
        assert pos["ticket"] == 1
        assert pos["sl"] == 1950.0
        assert pos["tp"] == 2100.0

    def test_broker_suffix_symbol_matches(self, monkeypatch) -> None:
        from src.mt5 import connector

        bars = _bars(120)
        monkeypatch.setattr(connector, "is_live_mode", lambda: True)
        monkeypatch.setattr(
            connector, "get_ohlc", lambda symbol, tf, count, before=None: bars[:count]
        )
        monkeypatch.setattr(connector, "get_account_info", lambda: SimpleNamespace(equity=10000.0))
        monkeypatch.setattr(
            connector,
            "get_positions",
            lambda: [self._position(7, "XAUUSDc", sl=None, tp=None)],
        )

        r = self.client.get("/chart/analysis", params={"symbol": "XAUUSD"})
        body = r.json()
        assert len(body["positions"]) == 1
        # No fabricated level: nothing placed stays null.
        assert body["positions"][0]["sl"] is None
        assert body["positions"][0]["tp"] is None

    def test_too_few_bars_ok_false(self, monkeypatch) -> None:
        from src.mt5 import connector

        monkeypatch.setattr(connector, "is_live_mode", lambda: True)
        monkeypatch.setattr(connector, "get_ohlc", lambda symbol, tf, count, before=None: _bars(10))
        r = self.client.get("/chart/analysis", params={"symbol": "XAUUSD", "bars": 50})
        assert r.status_code == 200
        assert r.json()["ok"] is False


class TestChartHistoryPaging:
    """Lazy-load of older history via the `before` parameter."""

    def setup_method(self) -> None:
        self.client = TestClient(app)

    def _bars_ending(self, end_iso: str, count: int):
        base_end = datetime.fromisoformat(end_iso)
        out = []
        for i in range(count):
            t = base_end - timedelta(hours=count - 1 - i)
            out.append(
                SimpleNamespace(
                    time=t,
                    open=1.0 + i * 0.001,
                    high=1.0 + i * 0.001 + 0.0005,
                    low=1.0 + i * 0.001 - 0.0005,
                    close=1.0 + i * 0.001,
                    volume=1000.0,
                )
            )
        return out

    def test_before_returns_older_window_and_has_more(self, monkeypatch) -> None:
        from src.mt5 import connector

        monkeypatch.setattr(connector, "is_live_mode", lambda: True)
        calls = []

        def fake_get_ohlc(symbol, tf, count, before=None):
            calls.append(before)
            if before is None:
                return self._bars_ending("2026-01-10T00:00:00", count)
            # One older page exists, then nothing before that.
            if before > datetime(2026, 1, 1, 0, 0, 0):
                return self._bars_ending(before.isoformat(), count)
            return []

        monkeypatch.setattr(connector, "get_ohlc", fake_get_ohlc)

        r = self.client.get(
            "/chart/candles",
            params={
                "symbol": "XAUUSD",
                "timeframe": "H1",
                "bars": 50,
                "before": "2026-01-05T00:00:00",
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["before"] == "2026-01-05T00:00:00"
        # First call must be the requested window (the later probe passes an
        # older timestamp).
        assert calls[0] == datetime(2026, 1, 5, 0, 0, 0)
        # The fake still has bars older than the returned window, so more
        # history exists → has_more is True.
        assert body["has_more"] is True

    def test_before_invalid_iso_400(self, monkeypatch) -> None:
        from src.mt5 import connector

        monkeypatch.setattr(connector, "is_live_mode", lambda: True)
        r = self.client.get(
            "/chart/candles",
            params={"symbol": "XAUUSD", "bars": 50, "before": "not-a-date"},
        )
        assert r.status_code == 400

    def test_has_more_false_when_no_older_bars(self, monkeypatch) -> None:
        """When the older-history probe returns nothing, has_more is False."""
        from src.mt5 import connector

        monkeypatch.setattr(connector, "is_live_mode", lambda: True)

        def fake_get_ohlc(symbol, tf, count, before=None):
            # The paged window returns a full page; the probe (count == 1)
            # returns empty → no more history.
            if count == 1:
                return []
            return self._bars_ending("2026-01-05T00:00:00", count)

        monkeypatch.setattr(connector, "get_ohlc", fake_get_ohlc)
        r = self.client.get(
            "/chart/candles",
            params={"symbol": "XAUUSD", "bars": 50, "before": "2026-01-05T00:00:00"},
        )
        assert r.status_code == 200
        assert r.json()["has_more"] is False

    def test_history_page_allows_fewer_than_min_bars(self, monkeypatch) -> None:
        """A final history page may legitimately return < _MIN_BARS bars."""
        from src.mt5 import connector

        monkeypatch.setattr(connector, "is_live_mode", lambda: True)
        monkeypatch.setattr(
            connector,
            "get_ohlc",
            lambda symbol, tf, count, before=None: _bars(5) if before else _bars(60),
        )
        r = self.client.get(
            "/chart/candles",
            params={"symbol": "XAUUSD", "bars": 50, "before": "2020-01-01T00:00:00"},
        )
        assert r.status_code == 200
        assert r.json()["ok"] is True
