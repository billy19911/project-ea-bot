# -*- coding: utf-8 -*-
"""Phase 4 — FVG detection tests (§9–§11, §42 TEST 10/11)."""

from __future__ import annotations

import pytest

from src.trading.entry_config import ZoneConfig
from src.trading.entry_detectors import detect_fvgs


def test_detects_bullish_fvg_from_ohlc():
    """3-candle imbalance: highs[i-1] < lows[i+1] (§9)."""
    highs = [10.0, 10.5, 11.0, 12.0]
    lows = [9.8, 10.0, 10.6, 11.2]
    # i=2: highs[1]=10.5 < lows[3]=11.2 → bullish gap (10.5, 11.2).
    zones = detect_fvgs(symbol="XAUUSD", timeframe="M15", highs=highs, lows=lows, atr=0.2)
    assert zones
    bull = [z for z in zones if z.direction == "LONG"]
    assert bull
    assert bull[-1].bottom == pytest.approx(10.5)
    assert bull[-1].top == pytest.approx(11.2)


def test_detects_bearish_fvg_from_ohlc():
    highs = [12.0, 11.5, 11.0, 10.0]
    lows = [11.5, 11.0, 10.5, 9.8]
    # i=2: lows[1]=11.0 > highs[3]=10.0 → bearish gap (10.0, 11.0).
    zones = detect_fvgs(symbol="XAUUSD", timeframe="M15", highs=highs, lows=lows, atr=0.2)
    bear = [z for z in zones if z.direction == "SHORT"]
    assert bear
    assert bear[-1].bottom == pytest.approx(10.0)
    assert bear[-1].top == pytest.approx(11.0)


def test_tiny_gap_rejected_as_noise():
    """Gap smaller than fvg_min_gap_atr is NOT a setup (§10)."""
    highs = [10.0, 10.01, 10.02, 10.05]
    lows = [9.9, 9.95, 10.0, 10.02]
    # gap = 10.02-10.01 = 0.01, atr=1.0 → 0.01 ATR < 0.1 minimum.
    zones = detect_fvgs(symbol="XAUUSD", timeframe="M15", highs=highs, lows=lows, atr=1.0)
    assert zones == []


def test_gap_quality_is_atr_normalized():
    highs = [10.0, 10.5, 11.0, 12.0]
    lows = [9.8, 10.0, 10.6, 11.2]
    zones = detect_fvgs(symbol="XAUUSD", timeframe="M15", highs=highs, lows=lows, atr=0.2)
    z = zones[-1]
    # gap 0.7 / atr 0.2 = 3.5 ATR.
    assert z.gap_atr == pytest.approx(3.5)


def test_fvg_count_configurable_via_lookback():
    highs = [10.0, 10.5, 11.0, 12.0, 12.5, 10.0, 10.5, 11.0, 12.0]
    lows = [9.8, 10.0, 10.6, 11.2, 11.5, 9.8, 10.0, 10.6, 11.2]
    narrow = detect_fvgs(
        symbol="X",
        timeframe="M15",
        highs=highs,
        lows=lows,
        atr=0.2,
        config=ZoneConfig(fvg_lookback=3),
    )
    wide = detect_fvgs(
        symbol="X",
        timeframe="M15",
        highs=highs,
        lows=lows,
        atr=0.2,
        config=ZoneConfig(fvg_lookback=15),
    )
    assert len(narrow) <= len(wide)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
