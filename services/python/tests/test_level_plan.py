# -*- coding: utf-8 -*-
"""Tests for the Entry/SL/TP1/TP2/TPmax level plan (signal-report ladder).

Covers ``trading.level_plan``: the project's ATR risk model
(SL = 1.5 x ATR, TP = 3.0 x ATR = 2R) turned into the reporting ladder
(TP1 = 1R, TP2 = 2R, TPmax = 3R), plus the helpers that read a live
snapshot and degrade honestly when evidence is missing.

No network and no MT5 are used.
"""

from __future__ import annotations

from trading.level_plan import (
    SL_ATR_MULT,
    TP1_R,
    TP2_R,
    TPMAX_R,
    build_level_plan,
    direction_from_text,
    extract_price_atr,
    indicative_levels,
)


# ---------------------------------------------------------------------------
# direction_from_text
# ---------------------------------------------------------------------------
def test_direction_from_text_maps_bullish_bearish() -> None:
    assert direction_from_text("overall BULLISH") == "BUY"
    assert direction_from_text("market_lead: BEARISH (conf=0.8)") == "SELL"


def test_direction_from_text_first_hint_wins_and_empty_degrades() -> None:
    assert direction_from_text("", "BULLISH") == "BUY"
    assert direction_from_text("NEUTRAL", "") == ""
    assert direction_from_text(None, 123) == ""


# ---------------------------------------------------------------------------
# build_level_plan — real order ladder
# ---------------------------------------------------------------------------
def test_build_level_plan_buy_ladder_uses_actual_stop() -> None:
    levels = build_level_plan("BUY", 2000.0, 1995.0, take_profit=2010.0, atr=4.0)
    assert levels is not None
    assert levels["direction"] == "BUY"
    assert levels["entry"] == 2000.0
    assert levels["sl"] == 1995.0  # exact stop given
    assert levels["tp1"] == 2005.0  # 1R = 5
    assert levels["tp2"] == 2010.0  # 2R
    assert levels["tpmax"] == 2015.0  # 3R
    assert levels["tp"] == 2010.0  # the proposal's own TP is kept
    assert levels["risk_distance"] == 5.0
    assert levels["rr"] == {"tp1": 1.0, "tp2": 2.0, "tpmax": 3.0}
    assert levels["source"] == "order"


def test_build_level_plan_sell_ladder_is_mirrored() -> None:
    levels = build_level_plan("SELL", 2000.0, 2005.0)
    assert levels is not None
    assert levels["sl"] == 2005.0
    assert levels["tp1"] == 1995.0
    assert levels["tp2"] == 1990.0
    assert levels["tpmax"] == 1985.0
    assert levels["source"] == "order"


def test_build_level_plan_degrades_without_direction_or_prices() -> None:
    assert build_level_plan("", 2000.0, 1995.0) is None
    assert build_level_plan("NEUTRAL", 2000.0, 1995.0) is None
    assert build_level_plan("BUY", 0.0, 1995.0) is None
    assert build_level_plan("BUY", 2000.0, 0.0) is None
    assert build_level_plan("BUY", 2000.0, 2000.0) is None  # zero risk
    assert build_level_plan("BUY", "x", "y") is None


def test_build_level_plan_accepts_string_numbers() -> None:
    levels = build_level_plan("buy", "100.5", "99.0")
    assert levels is not None
    assert levels["direction"] == "BUY"
    assert levels["risk_distance"] == 1.5


# ---------------------------------------------------------------------------
# indicative_levels — ATR model (no order yet)
# ---------------------------------------------------------------------------
def test_indicative_levels_follows_project_atr_model() -> None:
    # SL = 1.5 x ATR, TP2 = 3.0 x ATR => TP2 is the project's production TP.
    levels = indicative_levels("BUY", 2000.0, 2.0)
    assert levels is not None
    assert levels["sl"] == 2000.0 - SL_ATR_MULT * 2.0  # 1997.0
    assert levels["tp1"] == 2003.0  # 1R = 3.0
    assert levels["tp2"] == 2006.0  # 2R = 6.0
    assert levels["tpmax"] == 2009.0  # 3R = 9.0
    assert levels["atr"] == 2.0
    assert levels["source"] == "analysis"


def test_indicative_levels_sell_and_degradation() -> None:
    levels = indicative_levels("SELL", 2000.0, 2.0)
    assert levels is not None
    assert levels["sl"] == 2003.0
    assert levels["tp1"] == 1997.0
    assert indicative_levels("", 2000.0, 2.0) is None
    assert indicative_levels("BUY", 0.0, 2.0) is None
    assert indicative_levels("BUY", 2000.0, 0.0) is None


def test_ladder_reward_multiples_are_one_two_three_r() -> None:
    assert (TP1_R, TP2_R, TPMAX_R) == (1.0, 2.0, 3.0)


# ---------------------------------------------------------------------------
# extract_price_atr — snapshot shapes
# ---------------------------------------------------------------------------
def test_extract_price_atr_reads_feed_loop_snapshot() -> None:
    ctx = {
        "volatility": {"atr": 2.5, "price": 1998.75},
        "market_state": {"close": 1999.0, "atr": 2.4},
        "prices": [1990.0, 1995.0, 1998.75],
    }
    price, atr = extract_price_atr(ctx)
    assert price == 1999.0  # market_state.close (the live state) wins
    assert atr == 2.5  # volatility.atr wins

    # Without a market state, the volatility block still supplies both.
    assert extract_price_atr({"volatility": {"atr": 2.5, "price": 1998.75}}) == (1998.75, 2.5)


def test_extract_price_atr_fallbacks_and_missing_evidence() -> None:
    assert extract_price_atr({"price": 10.0, "atr": 1.0}) == (10.0, 1.0)
    assert extract_price_atr({"close": 11.0}) == (11.0, 0.0)
    assert extract_price_atr({"prices": [1.0, 2.0, 12.5]}) == (12.5, 0.0)
    assert extract_price_atr({"market_info": {"bid": 12.0, "ask": 12.2}}) == (12.2, 0.0)
    assert extract_price_atr({}) == (0.0, 0.0)
    assert extract_price_atr(None) == (0.0, 0.0)


def test_extract_price_atr_handles_market_state_object() -> None:
    class State:
        close = 3000.5
        atr = 7.5

    price, atr = extract_price_atr({"market_state": State()})
    assert price == 3000.5
    assert atr == 7.5
