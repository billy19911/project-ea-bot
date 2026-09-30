# -*- coding: utf-8 -*-
"""Phase 4 — trigger engine tests (§14–§22, §42 TEST 2–4/12/13/44)."""

from __future__ import annotations

import pytest

from src.trading.trigger_engine import (
    TRIGGER_CANDLE_CLOSE,
    TRIGGER_DISPLACEMENT,
    TRIGGER_MICRO_BOS,
    TRIGGER_MOMENTUM_SHIFT,
    TRIGGER_REJECTION,
    TRIGGER_ZONE_TOUCH,
    evaluate_triggers,
)


def _trend_up(n: int = 20, start: float = 100.0):
    o = [start + i * 0.5 for i in range(n)]
    h = [x + 0.6 for x in o]
    lo = [x - 0.6 for x in o]
    c = [x + 0.3 for x in o]
    return o, h, lo, c


def test_zone_touch_does_not_enter():
    """Touch without confirmation → no ENTRY trigger types fire."""
    # Flat candle sitting inside the zone, no rejection/displacement/BOS.
    r = evaluate_triggers(
        direction="LONG",
        zone_top=200.0,
        zone_bottom=199.0,
        opens=[200.4, 200.4, 200.4],
        highs=[200.5, 200.5, 200.5],
        lows=[199.5, 199.5, 199.5],
        closes=[200.0, 200.0, 200.0],
        atr=1.0,
        is_closed=True,
    )
    assert r.conditions_met[TRIGGER_ZONE_TOUCH] is True
    assert r.conditions_met[TRIGGER_REJECTION] is False
    assert r.conditions_met[TRIGGER_DISPLACEMENT] is False
    assert r.conditions_met[TRIGGER_MICRO_BOS] is False


def test_bullish_rejection_confirmed():
    """Wick into zone + bullish body + close → rejection (§15 TEST 2)."""
    r = evaluate_triggers(
        direction="LONG",
        zone_top=10.3,
        zone_bottom=10.2,
        opens=[10.4, 10.45, 10.5],
        highs=[10.5, 10.55, 10.7],
        lows=[10.3, 10.35, 10.15],
        closes=[10.42, 10.5, 10.6],
        atr=0.2,
        is_closed=True,
    )
    assert r.conditions_met[TRIGGER_REJECTION] is True
    assert any(e.type == TRIGGER_REJECTION for e in r.evidence)


def test_random_wick_is_not_rejection():
    """Bearish body with a down wick is NOT a LONG rejection."""
    r = evaluate_triggers(
        direction="LONG",
        zone_top=10.3,
        zone_bottom=10.2,
        opens=[10.6, 10.62, 10.65],
        highs=[10.7, 10.7, 10.68],
        lows=[10.3, 10.32, 10.1],
        closes=[10.5, 10.52, 10.4],
        atr=0.2,
        is_closed=True,
    )
    assert r.conditions_met[TRIGGER_REJECTION] is False


def test_forming_candle_never_confirms():
    """is_closed=False → candle_close False, detectors skip last bar (TEST 3)."""
    o, h, lo, c = _trend_up()
    r = evaluate_triggers(
        direction="LONG",
        zone_top=c[-1] + 5,
        zone_bottom=c[-1] + 4,
        opens=o,
        highs=h,
        lows=lo,
        closes=c,
        atr=0.5,
        is_closed=False,
    )
    assert r.conditions_met[TRIGGER_CANDLE_CLOSE] is False


def test_micro_bos_breaks_local_swing():
    """Last-bar high breaks the prior lookback swing high (TEST 4)."""
    o = [10 + i * 0.1 for i in range(12)]
    c = [10 + i * 0.1 + 0.05 for i in range(12)]
    h = [x + 0.2 for x in c]
    lo = [x - 0.2 for x in c]
    h[-1] = max(h[:-1]) + 0.5  # decisive break
    c[-1] = h[-1] - 0.05
    o[-1] = c[-1] - 0.3
    r = evaluate_triggers(
        direction="LONG",
        zone_top=h[-1] + 1,
        zone_bottom=h[-1] - 1,
        opens=o,
        highs=h,
        lows=lo,
        closes=c,
        atr=0.3,
        is_closed=True,
    )
    assert r.conditions_met[TRIGGER_MICRO_BOS] is True


def test_momentum_shift_supports_not_triggers():
    o, h, lo, c = _trend_up(40)
    r = evaluate_triggers(
        direction="LONG",
        zone_top=0,
        zone_bottom=-100,
        opens=o,
        highs=h,
        lows=lo,
        closes=c,
        atr=0.5,
        is_closed=True,
    )
    assert r.conditions_met[TRIGGER_MOMENTUM_SHIFT] is True


def test_no_future_leakage():
    """A break bar AFTER the evaluated prefix must not leak into the result."""
    # Flat, non-trending series (no local high break within the prefix).
    o = [10.0] * 12
    c = [10.0] * 12
    h = [10.2] * 12
    lo = [9.8] * 12
    # Full series WITH a future break appended at the end.
    h_full = h + [10.2 + 2.0]
    lo_full = lo + [9.8]
    o_full = o + [10.0]
    c_full = c + [12.1]
    trunc = evaluate_triggers(
        direction="LONG",
        zone_top=999,
        zone_bottom=998,
        opens=o,
        highs=h,
        lows=lo,
        closes=c,
        atr=0.5,
        is_closed=True,
    )
    # Prefix without the future break must NOT show micro BOS.
    assert trunc.conditions_met[TRIGGER_MICRO_BOS] is False
    # The full series DOES see the break only because it is its own last bar.
    full = evaluate_triggers(
        direction="LONG",
        zone_top=999,
        zone_bottom=998,
        opens=o_full,
        highs=h_full,
        lows=lo_full,
        closes=c_full,
        atr=0.5,
        is_closed=True,
    )
    assert full.conditions_met[TRIGGER_MICRO_BOS] is True


def test_trigger_freshness_window():
    r = evaluate_triggers(
        direction="LONG",
        zone_top=10.3,
        zone_bottom=10.2,
        opens=[10.4, 10.45, 10.5],
        highs=[10.5, 10.55, 10.7],
        lows=[10.3, 10.35, 10.15],
        closes=[10.42, 10.5, 10.6],
        atr=0.2,
        is_closed=True,
        now_ts=1000.0,
        candle_ts=1000.0,
    )
    assert r.is_fresh(900.0, now_ts=1000.0) is True
    assert r.is_fresh(900.0, now_ts=1000.0 + 901.0) is False


def test_blocking_conditions_recorded():
    o, h, lo, c = _trend_up()
    r = evaluate_triggers(
        direction="LONG",
        zone_top=c[-1] - 1,
        zone_bottom=c[-1] - 2,
        opens=o,
        highs=h,
        lows=lo,
        closes=c,
        atr=0.5,
        is_closed=True,
        spread_atr=1.0,
        news_blocked=True,
        structure_invalidated=True,
    )
    assert "spread_too_wide" in r.blocking
    assert "news_high_impact" in r.blocking
    assert "structure_invalidated" in r.blocking


def test_insufficient_data_is_unknown_not_ready():
    r = evaluate_triggers(
        direction="LONG",
        zone_top=1,
        zone_bottom=0,
        opens=[1.0],
        highs=[1.1],
        lows=[0.9],
        closes=[1.05],
        atr=0.1,
        is_closed=True,
    )
    assert "insufficient_data" in r.blocking
    assert not any(r.conditions_met.values())


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
