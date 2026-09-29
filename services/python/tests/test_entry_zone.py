# -*- coding: utf-8 -*-
"""Tests for the OB/FVG multi-timeframe entry engine (F2).

Pure-function coverage of ``trading.entry_zone``:
- bias from HTF EMA separation,
- OB/FVG band detection,
- plan building (direction + zone + SL just past the zone + RR take-profit),
- the width guard (reject absurdly wide stops),
- the watch-and-fire gate (wait outside the zone, fire inside it).
"""

from __future__ import annotations

from trading.entry_zone import (
    ZoneEntryGate,
    build_entry_plan,
    compute_bias,
    find_fair_value_gaps,
    find_order_blocks,
)


def _rising(n=80, start=100.0, step=0.5):
    return [start + i * step for i in range(n)]


def _falling(n=80, start=140.0, step=0.5):
    return [start - i * step for i in range(n)]


# ---------------------------------------------------------------------------
# compute_bias
# ---------------------------------------------------------------------------
def test_bias_bullish_on_rising_series():
    bias = compute_bias(_rising())
    assert bias["direction"] == "BULLISH"
    assert bias["strength"] > 0


def test_bias_bearish_on_falling_series():
    assert compute_bias(_falling())["direction"] == "BEARISH"


def test_bias_neutral_when_insufficient_bars():
    assert compute_bias([1.0, 2.0, 3.0])["direction"] == "NEUTRAL"


# ---------------------------------------------------------------------------
# zones
# ---------------------------------------------------------------------------
def test_find_fvg_detects_bullish_gap():
    # 3 candles where bar[2].low > bar[0].high → bullish FVG.
    highs = [10.0, 10.5, 12.0, 12.5]
    lows = [9.0, 9.5, 11.0, 11.5]
    fvgs = find_fair_value_gaps(highs, lows)
    assert any(f["type"] == "bullish" for f in fvgs)


def test_find_order_blocks_returns_bands():
    highs = [100 + i for i in range(25)]
    lows = [95 + i for i in range(25)]
    obs = find_order_blocks(highs, lows)
    assert {o["type"] for o in obs} == {"bullish", "bearish"}
    for o in obs:
        assert o["top"] > o["bottom"]


# ---------------------------------------------------------------------------
# build_entry_plan
# ---------------------------------------------------------------------------
def _zone_data():
    # bullish market: demand zone around 100-101, price ~100.5
    highs = [100.0 + i * 0.1 for i in range(20)]
    lows = [99.0 + i * 0.1 for i in range(20)]
    return highs, lows


def test_plan_bullish_uses_zone_and_rr():
    highs, lows = _zone_data()
    # price inside the bullish zone (near the swing low band)
    price = min(lows[-10:]) + 0.05
    plan = build_entry_plan(
        htf_closes=_rising(),
        zone_highs=highs,
        zone_lows=lows,
        trigger_price=price,
        atr=0.0,
        rr=2.0,
        require_inside_zone=False,
    )
    assert plan is not None
    assert plan.direction == "BUY"
    assert plan.stop_loss < plan.entry  # SL below entry for a BUY
    assert plan.take_profit > plan.entry
    # 2R take-profit.
    assert abs(plan.reward_distance - 2.0 * plan.risk_distance) < 1e-6


def test_plan_none_when_bias_neutral():
    highs, lows = _zone_data()
    plan = build_entry_plan(
        htf_closes=[1.0, 2.0, 3.0],  # insufficient → NEUTRAL
        zone_highs=highs,
        zone_lows=lows,
        trigger_price=100.5,
        require_inside_zone=False,
    )
    assert plan is None


def test_plan_rejects_absurdly_wide_stop():
    # Zone spans a huge range → risk >> max_risk_atr * atr → rejected.
    highs = [200.0, 200.0, 200.0]
    lows = [10.0, 10.0, 10.0]
    plan = build_entry_plan(
        htf_closes=_rising(),
        zone_highs=highs,
        zone_lows=lows,
        trigger_price=100.0,
        atr=0.5,  # tiny ATR vs a ~190-wide zone
        max_risk_atr=2.5,
        require_inside_zone=False,
    )
    assert plan is None


def test_plan_requires_inside_zone_when_requested():
    highs, lows = _zone_data()
    # price FAR above the zone → not inside → None (watch-and-fire waits).
    plan = build_entry_plan(
        htf_closes=_rising(),
        zone_highs=highs,
        zone_lows=lows,
        trigger_price=500.0,
        atr=1.0,
        require_inside_zone=True,
    )
    assert plan is None


# ---------------------------------------------------------------------------
# ZoneEntryGate (watch-and-fire)
# ---------------------------------------------------------------------------
def test_plan_fires_when_price_near_zone_within_trigger_window():
    """Relaxed firing: price within entry_trigger_atr of the zone fires an entry
    (market entry at current price; SL anchored below the demand zone)."""
    highs = [2000.0 + i * 0.3 for i in range(60)]
    lows = [1995.0 + i * 0.3 for i in range(60)]
    opens = [h - 0.1 for h in highs]
    price = highs[-1]  # ~2017.7, well above the demand band
    plan = build_entry_plan(
        htf_closes=_rising(120),
        zone_highs=highs,
        zone_lows=lows,
        zone_opens=opens,
        trigger_price=price,
        atr=5.0,
        require_inside_zone=True,
    )
    assert plan is not None
    assert plan.direction == "BUY"
    # Market entry == current price (not the far zone edge).
    assert abs(plan.entry - price) < 1e-6
    # SL anchored at/below the zone bottom.
    assert plan.stop_loss <= plan.zone_bottom + 1e-6
    assert plan.take_profit > plan.entry


def test_plan_waits_when_price_too_far_from_zone():
    """Beyond entry_trigger_atr the plan stays None (watch-and-fire waits)."""
    highs = [2000.0 + i * 0.3 for i in range(60)]
    lows = [1995.0 + i * 0.3 for i in range(60)]
    opens = [h - 0.1 for h in highs]
    price = highs[-1] + 100.0  # very far above the demand zone
    plan = build_entry_plan(
        htf_closes=_rising(120),
        zone_highs=highs,
        zone_lows=lows,
        zone_opens=opens,
        trigger_price=price,
        atr=5.0,
        require_inside_zone=True,
    )
    assert plan is None

    gate = ZoneEntryGate()
    highs = [100.0 + i * 0.1 for i in range(20)]
    lows = [99.0 + i * 0.1 for i in range(20)]

    # Discover the actual zone the engine will pick (don't assume the band).
    ref = build_entry_plan(
        htf_closes=_rising(),
        zone_highs=highs,
        zone_lows=lows,
        trigger_price=min(lows[-5:]),  # a bit above the demand band bottom
        atr=0.0,
        require_inside_zone=False,
    )
    assert ref is not None and ref.direction == "BUY"
    inside_price = (ref.zone_top + ref.zone_bottom) / 2.0

    # 1) Price far above the zone → parked as pending, no plan.
    plan = gate.evaluate(
        symbol="XAUUSD",
        htf_closes=_rising(),
        zone_highs=highs,
        zone_lows=lows,
        trigger_price=ref.zone_top + 50.0,
        atr=0.0,
    )
    assert plan is None
    assert gate.pending_count() == 1

    # 2) Price now inside the zone → fires and clears pending.
    plan = gate.evaluate(
        symbol="XAUUSD",
        htf_closes=_rising(),
        zone_highs=highs,
        zone_lows=lows,
        trigger_price=inside_price,
        atr=0.0,
    )
    assert plan is not None
    assert plan.direction == "BUY"
    assert gate.pending_count() == 0


def test_gate_clears_pending_when_setup_disappears():
    gate = ZoneEntryGate()
    highs = [100.0 + i * 0.1 for i in range(20)]
    lows = [99.0 + i * 0.1 for i in range(20)]
    gate.evaluate(
        symbol="EURUSD",
        htf_closes=_rising(),
        zone_highs=highs,
        zone_lows=lows,
        trigger_price=min(lows) + 50.0,
        atr=0.0,
    )
    assert gate.pending_count() == 1
    # Neutral bias → no valid setup at all → pending dropped.
    gate.evaluate(
        symbol="EURUSD",
        htf_closes=[1.0, 2.0],
        zone_highs=highs,
        zone_lows=lows,
        trigger_price=100.0,
        atr=0.0,
    )
    assert gate.pending_count() == 0
