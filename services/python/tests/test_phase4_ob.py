# -*- coding: utf-8 -*-
"""Phase 4 — OB detection tests (§6–§8, §42 TEST 5/14)."""

from __future__ import annotations

import pytest

from src.trading.entry_config import ZoneConfig
from src.trading.entry_detectors import detect_order_blocks
from src.trading.entry_zones import evaluate_invalidation, zone_identity


def _bullish_ob_series():
    """Origin bearish candle at index 3, strong bullish displacement at 4."""
    opens = [10.0, 10.2, 10.5, 10.4, 10.4, 10.9]
    highs = [10.1, 10.3, 10.6, 10.5, 11.2, 11.4]
    lows = [9.9, 10.0, 10.3, 10.2, 10.3, 10.8]
    closes = [10.05, 10.15, 10.4, 10.3, 11.0, 11.3]
    return opens, highs, lows, closes


def test_detects_bullish_order_block_with_displacement():
    o, h, lo, c = _bullish_ob_series()
    zones = detect_order_blocks(
        symbol="XAUUSD", timeframe="M15", opens=o, highs=h, lows=lo, closes=c, atr=0.3
    )
    bullish = [z for z in zones if z.direction == "LONG"]
    assert bullish, "expected a bullish OB"
    z = bullish[0]
    assert z.zone_type == "ORDER_BLOCK"
    assert z.bottom < z.top
    assert z.displacement_atr >= 0.5


def test_no_ob_without_displacement():
    """Every opposite candle is NOT an OB — need displacement (§6)."""
    o = [10.0, 10.1, 10.0, 10.1, 10.05]
    h = [10.1, 10.2, 10.1, 10.2, 10.15]
    lo = [9.9, 10.0, 9.9, 10.0, 9.95]
    c = [10.05, 10.0, 10.05, 10.05, 10.1]  # tiny bodies, no displacement
    zones = detect_order_blocks(
        symbol="XAUUSD", timeframe="M15", opens=o, highs=h, lows=lo, closes=c, atr=1.0
    )
    assert zones == []


def test_zone_identity_is_stable():
    """Same structure ⇒ same zone_id (no new id per tick) (§5)."""
    a = zone_identity(
        symbol="XAUUSD",
        timeframe="M15",
        direction="LONG",
        zone_type="ORDER_BLOCK",
        anchor_price=10.5,
        anchor_index=3,
    )
    b = zone_identity(
        symbol="XAUUSD",
        timeframe="M15",
        direction="LONG",
        zone_type="ORDER_BLOCK",
        anchor_price=10.5,
        anchor_index=3,
    )
    c = zone_identity(
        symbol="XAUUSD",
        timeframe="M15",
        direction="LONG",
        zone_type="ORDER_BLOCK",
        anchor_price=10.6,
        anchor_index=3,  # different anchor
    )
    assert a == b
    assert a != c


def test_ob_invalidation_on_decisive_close():
    o, h, lo, c = _bullish_ob_series()
    z = detect_order_blocks(
        symbol="XAUUSD", timeframe="M15", opens=o, highs=h, lows=lo, closes=c, atr=0.3
    )[0]
    # Wick below is NOT invalidation.
    inv, _ = evaluate_invalidation(z, close_price=z.bottom + 0.001)
    assert inv is False
    # Decisive close below the invalidation boundary → INVALID.
    inv2, reason = evaluate_invalidation(z, close_price=z.invalidation_price - 0.5)
    assert inv2 is True
    assert "invalidated" in reason.lower()


def test_zone_retest_cap():
    o, h, lo, c = _bullish_ob_series()
    z = detect_order_blocks(
        symbol="XAUUSD", timeframe="M15", opens=o, highs=h, lows=lo, closes=c, atr=0.3
    )[0]
    cfg = ZoneConfig(max_retests=1)
    z.record_touch()
    assert z.retests_exceeded(cfg.max_retests) is False
    z.record_touch()
    assert z.retests_exceeded(cfg.max_retests) is True


def test_bearish_ob_mirror():
    # bullish origin candle at idx 3 (10.3→10.5), strong bearish displacement idx 4.
    o = [10.0, 10.2, 10.1, 10.3, 10.5]
    h = [10.1, 10.3, 10.2, 10.6, 10.55]
    lo = [9.9, 10.1, 10.0, 10.25, 10.0]
    c = [10.05, 10.15, 10.05, 10.5, 10.1]  # idx3 green, idx4 close 10.1 (huge red)
    zones = detect_order_blocks(
        symbol="XAUUSD", timeframe="M15", opens=o, highs=h, lows=lo, closes=c, atr=0.2
    )
    short = [z for z in zones if z.direction == "SHORT"]
    assert short
    assert short[0].invalidation_price == short[0].top


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
