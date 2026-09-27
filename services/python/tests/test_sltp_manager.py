# -*- coding: utf-8 -*-
"""Tests for dynamic SL management: BEP, progressive TP1 lock, trailing."""

from __future__ import annotations

from execution.sltp_manager import SLTPConfig, decide_stop_loss


def test_disabled_returns_none():
    cfg = SLTPConfig(enabled=False)
    assert (
        decide_stop_loss(
            direction="buy",
            entry_price=2000.0,
            current_sl=1990.0,
            current_price=2020.0,
            atr=10.0,
            initial_risk=10.0,
            config=cfg,
        )
        is None
    )


def test_breakeven_moves_sl_to_entry_at_1r():
    cfg = SLTPConfig(breakeven_enabled=True, progressive_enabled=False, trailing_enabled=False)
    # BUY: entry 2000, risk 10 -> 1R at 2010. Price 2012.
    decision = decide_stop_loss(
        direction="buy",
        entry_price=2000.0,
        current_sl=1990.0,
        current_price=2012.0,
        atr=10.0,
        initial_risk=10.0,
        config=cfg,
    )
    assert decision is not None
    assert decision.reason == "breakeven"
    assert decision.new_sl == 2000.0


def test_breakeven_not_triggered_below_1r():
    cfg = SLTPConfig(breakeven_enabled=True, progressive_enabled=False, trailing_enabled=False)
    decision = decide_stop_loss(
        direction="buy",
        entry_price=2000.0,
        current_sl=1990.0,
        current_price=2005.0,  # only 0.5R
        atr=10.0,
        initial_risk=10.0,
        config=cfg,
    )
    assert decision is None


def test_breakeven_with_lock_r():
    cfg = SLTPConfig(
        breakeven_enabled=True,
        bep_lock_r=0.5,
        progressive_enabled=False,
        trailing_enabled=False,
    )
    decision = decide_stop_loss(
        direction="buy",
        entry_price=2000.0,
        current_sl=1990.0,
        current_price=2012.0,
        atr=10.0,
        initial_risk=10.0,
        config=cfg,
    )
    assert decision is not None
    # entry + 0.5R = 2005
    assert decision.new_sl == 2005.0


def test_progressive_tp1_lock():
    cfg = SLTPConfig(
        breakeven_enabled=False, progressive_enabled=True, tp1_lock_r=0.5, trailing_enabled=False
    )
    # Reaching 1R (2010) locks 0.5R -> SL 2005
    decision = decide_stop_loss(
        direction="buy",
        entry_price=2000.0,
        current_sl=1990.0,
        current_price=2011.0,
        atr=10.0,
        initial_risk=10.0,
        config=cfg,
    )
    assert decision is not None
    assert decision.reason in ("tp1_lock", "breakeven")
    assert decision.new_sl == 2005.0


def test_trailing_buy_uses_atr():
    cfg = SLTPConfig(
        breakeven_enabled=False,
        progressive_enabled=False,
        trailing_enabled=True,
        trail_atr_factor=1.5,
    )
    decision = decide_stop_loss(
        direction="buy",
        entry_price=2000.0,
        current_sl=1990.0,
        current_price=2030.0,
        atr=10.0,
        initial_risk=10.0,
        config=cfg,
    )
    assert decision is not None
    assert decision.reason == "trailing"
    # 2030 - 1.5*10 = 2015
    assert decision.new_sl == 2015.0


def test_trailing_sell_uses_atr():
    cfg = SLTPConfig(
        breakeven_enabled=False,
        progressive_enabled=False,
        trailing_enabled=True,
        trail_atr_factor=1.5,
    )
    decision = decide_stop_loss(
        direction="sell",
        entry_price=2000.0,
        current_sl=2010.0,
        current_price=1970.0,
        atr=10.0,
        initial_risk=10.0,
        config=cfg,
    )
    assert decision is not None
    assert decision.reason == "trailing"
    # 1970 + 1.5*10 = 1985
    assert decision.new_sl == 1985.0


def test_never_widens_risk_buy():
    # SL already at 2015 (very tight); trailing wants 2015 -> no worse change.
    cfg = SLTPConfig(breakeven_enabled=False, progressive_enabled=False, trailing_enabled=True)
    decision = decide_stop_loss(
        direction="buy",
        entry_price=2000.0,
        current_sl=2018.0,  # already better than trail candidate
        current_price=2025.0,
        atr=10.0,
        initial_risk=10.0,
        config=cfg,
    )
    assert decision is None


def test_min_move_r_prevents_churn():
    cfg = SLTPConfig(
        breakeven_enabled=True,
        progressive_enabled=False,
        trailing_enabled=False,
        min_move_r=0.5,
    )
    # current SL 1999.9 (0.01R from entry 2000) -> move to 2000 is < 0.5R -> skip
    decision = decide_stop_loss(
        direction="buy",
        entry_price=2000.0,
        current_sl=1999.9,
        current_price=2012.0,
        atr=10.0,
        initial_risk=10.0,
        config=cfg,
    )
    assert decision is None


def test_invalid_direction_returns_none():
    assert (
        decide_stop_loss(
            direction="flat",
            entry_price=2000.0,
            current_sl=1990.0,
            current_price=2020.0,
            atr=10.0,
        )
        is None
    )


def test_picks_most_favourable_among_rules():
    # All rules enabled: trailing at 2030 with 1.5 ATR = 2015 (1.5R), which beats
    # breakeven (2000). So trailing should win.
    cfg = SLTPConfig(
        breakeven_enabled=True,
        progressive_enabled=True,
        tp1_lock_r=0.5,
        trailing_enabled=True,
        trail_atr_factor=1.5,
    )
    decision = decide_stop_loss(
        direction="buy",
        entry_price=2000.0,
        current_sl=1990.0,
        current_price=2030.0,
        atr=10.0,
        initial_risk=10.0,
        config=cfg,
    )
    assert decision is not None
    assert decision.reason == "trailing"
    assert decision.new_sl == 2015.0
