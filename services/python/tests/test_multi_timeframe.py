# -*- coding: utf-8 -*-
"""Tests for multi-timeframe analysis (HTF bias + LTF entry filter)."""

from __future__ import annotations

from market.multi_timeframe import HTFBias, build_timeframe_prices, compute_htf_bias


def _uptrend(n=120, start=100.0, step=0.5):
    return [start + i * step for i in range(n)]


def _downtrend(n=120, start=200.0, step=0.5):
    return [start - i * step for i in range(n)]


def test_compute_htf_bias_bullish():
    bias = compute_htf_bias(_uptrend(), timeframe="H4", fast_period=20, slow_period=50)
    assert bias.direction == "BULLISH"
    assert bias.strength > 0.0
    assert bias.timeframe == "H4"


def test_compute_htf_bias_bearish():
    bias = compute_htf_bias(_downtrend(), timeframe="H4")
    assert bias.direction == "BEARISH"
    assert bias.strength > 0.0


def test_compute_htf_bias_insufficient_bars_is_neutral():
    bias = compute_htf_bias([100.0, 101.0, 102.0], timeframe="H4")
    assert bias.direction == "NEUTRAL"
    assert bias.strength == 0.0


def test_compute_htf_bias_flat_is_neutral():
    flat = [100.0] * 120
    bias = compute_htf_bias(flat)
    assert bias.direction == "NEUTRAL"


def test_htf_bias_to_dict():
    bias = HTFBias(timeframe="H4", direction="BULLISH", strength=0.42, reason="x")
    d = bias.to_dict()
    assert d == {"timeframe": "H4", "direction": "BULLISH", "strength": 0.42, "reason": "x"}


class _Bar:
    def __init__(self, close):
        self.close = close


class _FakeConnector:
    """Returns a per-timeframe series so we can control each TF's trend."""

    def __init__(self, series_by_tf):
        self.series_by_tf = series_by_tf
        self.calls = []

    def get_ohlc(self, symbol, timeframe, count):
        self.calls.append(timeframe)
        series = self.series_by_tf.get(timeframe)
        if series is None:
            raise RuntimeError("no data")
        return [_Bar(c) for c in series]


def test_build_timeframe_prices_attaches_all_and_htf_from_slowest():
    conn = _FakeConnector(
        {
            "M15": _uptrend(),
            "H1": _uptrend(),
            "H4": _downtrend(),  # slowest -> drives HTF bias
        }
    )
    result = build_timeframe_prices("XAUUSD", connector=conn, timeframes=("M15", "H1", "H4"))
    assert set(result["timeframe_prices"].keys()) == {"M15", "H1", "H4"}
    # HTF bias should come from H4 (the slowest timeframe) -> BEARISH.
    assert result["htf_bias"]["direction"] == "BEARISH"
    assert result["htf_bias"]["timeframe"] == "H4"


def test_build_timeframe_prices_skips_failed_tf_fail_safe():
    conn = _FakeConnector({"M15": _uptrend(), "H1": None, "H4": None})
    result = build_timeframe_prices("XAUUSD", connector=conn, timeframes=("M15", "H1", "H4"))
    assert set(result["timeframe_prices"].keys()) == {"M15"}
    # Only M15 available -> HTF bias computed from M15.
    assert result["htf_bias"]["timeframe"] == "M15"


def test_build_timeframe_prices_all_fail_returns_empty():
    conn = _FakeConnector({})
    result = build_timeframe_prices("XAUUSD", connector=conn)
    assert result["timeframe_prices"] == {}
    assert result["htf_bias"] is None


def test_build_timeframe_prices_no_connector():
    result = build_timeframe_prices("XAUUSD", connector=None)
    assert result == {"timeframe_prices": {}, "htf_bias": None}
