# -*- coding: utf-8 -*-
"""Tests for the level-based SL ladder (TP1 → BEP+buffer, TP2 → TP1, trail).

R = initial risk = |entry - initial SL|. Ladder (BUY, entry 2000, R=10):
  TP1 = 2010 (1R),  TP2 = 2020 (2R),  TPmax = 2030 (3R).
"""

from __future__ import annotations

from execution.sltp_manager import SLTPConfig, decide_stop_loss


def _decide(price, sl=1990.0, direction="buy", cfg=None, atr=10.0):
    return decide_stop_loss(
        direction=direction,
        entry_price=2000.0,
        current_sl=sl,
        current_price=price,
        atr=atr,
        initial_risk=10.0,
        config=cfg or SLTPConfig(),
    )


def test_disabled_returns_none():
    cfg = SLTPConfig(enabled=False)
    assert _decide(2020.0, cfg=cfg) is None


def test_no_move_before_tp1():
    """Below TP1 (1R) the stop must NOT move — this was the old bug."""
    # Price 0.5R (2005) and 0.99R (2009.9) → no decision.
    assert _decide(2005.0) is None
    assert _decide(2009.9) is None


def test_tp1_moves_sl_to_bep_plus_buffer():
    """At/after TP1 the stop goes to break-even + buffer (default 0.1R)."""
    cfg = SLTPConfig(bep_buffer_r=0.1)
    d = _decide(2011.0, cfg=cfg)  # just past 1R
    assert d is not None
    assert d.reason == "breakeven"
    # entry + 0.1R = 2001
    assert d.new_sl == 2001.0


def test_tp1_never_loses():
    """After BEP, the stop is above entry → the trade cannot lose."""
    d = _decide(2015.0)  # 1.5R, before TP2
    assert d is not None
    assert d.new_sl > 2000.0


def test_tp2_moves_sl_to_tp1():
    """At/after TP2 the stop moves up to the TP1 level (1R)."""
    d = _decide(2021.0)  # past 2R
    assert d is not None
    assert d.reason in ("tp2_lock", "trailing")
    # Locked at least 1R (2010); trailing may push it a bit higher.
    assert d.new_sl >= 2010.0


def test_tp2_lock_reason_when_trailing_off():
    cfg = SLTPConfig(trailing_enabled=False)
    d = _decide(2021.0, cfg=cfg)
    assert d is not None
    assert d.reason == "tp2_lock"
    assert d.new_sl == 2010.0  # exact TP1 level


def test_trailing_only_after_tp2():
    """Trailing must NOT engage before TP2 — even in strong profit."""
    # 1.9R (2019) is before TP2 → only BEP rung applies, not trailing.
    d = _decide(2019.0)
    assert d is not None
    assert d.reason == "breakeven"
    # 2.9R (2029) is past TP2 by enough that the ATR trail exceeds TP1 →
    # trailing engages (2029 - 15 = 2014 > TP1 2010).
    d2 = _decide(2029.0)
    assert d2 is not None
    assert d2.reason == "trailing"
    assert d2.new_sl == 2014.0


def test_trailing_buy_uses_atr_beyond_tp2():
    cfg = SLTPConfig(trail_atr_factor=1.5)
    d = _decide(2035.0, cfg=cfg)  # 3.5R, well past TPmax
    assert d is not None
    assert d.reason == "trailing"
    # 2035 - 15 = 2020 (2R)
    assert d.new_sl == 2020.0


def test_trailing_never_below_tp1():
    """A tight trail must never drop the stop below the secured TP1 level."""
    cfg = SLTPConfig(trail_atr_factor=5.0)  # wide trail would go below entry
    d = _decide(2025.0, cfg=cfg)  # past TP2
    assert d is not None
    # 2025 - 50 = 1975, clamped up to TP1 = 2010.
    assert d.new_sl == 2010.0


def test_sell_ladder():
    """SELL mirror: entry 2000, risk 10, SL 2010."""
    # Past TP1 (1990) → BEP+buffer (entry - 0.1R = 1999).
    d = _decide(1989.0, sl=2010.0, direction="sell")
    assert d is not None
    assert d.reason == "breakeven"
    assert d.new_sl == 1999.0
    # Past TP2 (1980) → TP1 level (entry - 1R = 1990).
    cfg = SLTPConfig(trailing_enabled=False)
    d2 = _decide(1979.0, sl=2010.0, direction="sell", cfg=cfg)
    assert d2 is not None
    assert d2.reason == "tp2_lock"
    assert d2.new_sl == 1990.0


def test_never_widens_risk():
    """A stop already better than the proposed one → no change."""
    cfg = SLTPConfig(trailing_enabled=False)
    d = _decide(2021.0, sl=2015.0, cfg=cfg)  # current SL already above TP1
    assert d is None


def test_min_move_r_prevents_churn():
    cfg = SLTPConfig(bep_buffer_r=0.1, min_move_r=0.5)
    # current SL 2000.5, BEP target 2001 → move 0.05R < 0.5R → skip
    d = _decide(2012.0, sl=2000.5, cfg=cfg)
    assert d is None


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
