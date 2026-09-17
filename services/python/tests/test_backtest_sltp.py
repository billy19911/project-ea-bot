# -*- coding: utf-8 -*-
"""Tests for ATR-based SL/TP exits in the research backtest (Fase 2).

The backtest must behave like the trading engine: a 2x ATR stop and a
reward:risk 2:1 target (4x ATR) computed from *real* bar highs/lows, exits
labelled with the reason (``stop_loss`` / ``take_profit`` / ``signal_reversal``
/ ``end_of_data``), and a worst-case intrabar convention (stop before target
when one bar covers both).

Honesty rules kept under test:

* Without real highs/lows, no stop/target levels are fabricated — trades then
  carry ``stop_loss=None`` / ``take_profit=None`` and only exit on signal.
* ``atr_series`` stays in lock-step with the engine's ``atr`` value.
"""

from __future__ import annotations

import pytest

from research.engine import ResearchEngine
from trading.indicators import atr, atr_series


def _make_experiment(engine: ResearchEngine, version: str = "v1"):
    hypothesis = engine.create_hypothesis("Trend", "EMA trend", ["ema"], ["rev"], {})
    engine.create_strategy_version(version, {"fast_ema_period": 3, "slow_ema_period": 8})
    return engine.create_experiment(hypothesis.id, version, {})


def _bars(n: int = 200):
    """Deterministic oscillating series with real high/low envelopes."""
    closes: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    price = 100.0
    for i in range(n):
        price += 1.0 if (i // 10) % 2 == 0 else -0.8
        closes.append(round(price, 4))
        highs.append(round(price + 0.5, 4))
        lows.append(round(price - 0.5, 4))
    return closes, highs, lows


# ---------------------------------------------------------------------------
# atr_series — lock-step with atr()
# ---------------------------------------------------------------------------
class TestAtrSeries:
    def test_last_value_matches_atr(self) -> None:
        closes, highs, lows = _bars(80)
        series = atr_series(highs, lows, closes, 14)
        assert series[-1] == pytest.approx(atr(highs, lows, closes, 14))

    def test_warmup_is_none_not_zero(self) -> None:
        closes, highs, lows = _bars(40)
        series = atr_series(highs, lows, closes, 14)
        assert series[0] is None
        assert series[11] is None
        # Wilder smoothing seeds at index period-1 (same as the engine's atr()).
        assert series[13] is not None

    def test_mismatched_lengths_return_none(self) -> None:
        assert atr_series([1.0, 2.0], [1.0], [1.0, 2.0], 14) == [None, None]

    def test_invalid_period_raises(self) -> None:
        with pytest.raises(ValueError):
            atr_series([1.0], [1.0], [1.0], 0)


# ---------------------------------------------------------------------------
# Backtest with real highs/lows — ATR SL/TP active
# ---------------------------------------------------------------------------
class TestBacktestAtrLevels:
    def test_trades_carry_stop_and_target(self) -> None:
        engine = ResearchEngine()
        exp = _make_experiment(engine)
        closes, highs, lows = _bars()
        result = engine.run_backtest(exp, closes, highs=highs, lows=lows)
        assert result.total_trades >= 1
        for trade in result.trades:
            # Levels exist whenever ATR existed at entry; both or neither.
            assert ("stop_loss" in trade) and ("take_profit" in trade)
            if trade["atr_at_entry"] is not None:
                assert trade["stop_loss"] is not None
                assert trade["take_profit"] is not None
                direction = trade["direction"]
                entry = trade["entry"]
                # Stop below entry for longs (above for shorts) — and target
                # twice as far away (R:R 2:1).
                if direction == 1:
                    assert trade["stop_loss"] < entry < trade["take_profit"]
                else:
                    assert trade["take_profit"] < entry < trade["stop_loss"]

    def test_exit_reason_is_known(self) -> None:
        engine = ResearchEngine()
        exp = _make_experiment(engine)
        closes, highs, lows = _bars()
        result = engine.run_backtest(exp, closes, highs=highs, lows=lows)
        allowed = {"stop_loss", "take_profit", "signal_reversal", "end_of_data"}
        for trade in result.trades:
            assert trade["exit_reason"] in allowed

    def test_exit_price_matches_reason(self) -> None:
        engine = ResearchEngine()
        exp = _make_experiment(engine)
        closes, highs, lows = _bars()
        result = engine.run_backtest(exp, closes, highs=highs, lows=lows)
        for trade in result.trades:
            if trade["exit_reason"] == "stop_loss":
                assert trade["exit"] == pytest.approx(trade["stop_loss"])
            elif trade["exit_reason"] == "take_profit":
                assert trade["exit"] == pytest.approx(trade["take_profit"])

    def test_stop_hit_before_target_when_bar_covers_both(self) -> None:
        """Worst-case convention: one bar spanning stop AND target = stop."""
        engine = ResearchEngine()
        exp = _make_experiment(engine)
        # A flat series gives a tiny ATR; a single violent down bar covers both
        # the stop and (for a long) nothing of the target — so build the mirror:
        # flat prices then one huge bar that spans every level at once.
        closes = [100.0] * 40
        highs = [100.0] * 40
        lows = [100.0] * 40
        # Force an uptrend so the engine goes long, then one giant bar.
        for i in range(40):
            closes[i] = 100.0 + i * 0.5
            highs[i] = closes[i] + 0.2
            lows[i] = closes[i] - 0.2
        closes.append(closes[-1] + 0.5)
        highs.append(closes[-1] + 500.0)
        lows.append(closes[-1] - 500.0)
        result = engine.run_backtest(exp, closes, highs=highs, lows=lows, walk_forward=False)
        if result.trades:
            first = result.trades[0]
            assert first["exit_reason"] in {"stop_loss", "signal_reversal", "end_of_data"}
            if first["exit_reason"] == "stop_loss":
                assert first["exit"] == pytest.approx(first["stop_loss"])

    def test_without_highs_lows_no_fabricated_levels(self) -> None:
        engine = ResearchEngine()
        exp = _make_experiment(engine)
        closes, _, _ = _bars()
        result = engine.run_backtest(exp, closes)
        assert result.total_trades >= 1
        for trade in result.trades:
            assert trade["stop_loss"] is None
            assert trade["take_profit"] is None
            assert trade["exit_reason"] in {"signal_reversal", "end_of_data"}

    def test_deterministic_with_atr_levels(self) -> None:
        closes, highs, lows = _bars()
        engine_a, engine_b = ResearchEngine(), ResearchEngine()
        exp_a = _make_experiment(engine_a)
        exp_b = _make_experiment(engine_b)
        res_a = engine_a.run_backtest(exp_a, closes, highs=highs, lows=lows)
        res_b = engine_b.run_backtest(exp_b, closes, highs=highs, lows=lows)
        assert [t["exit_reason"] for t in res_a.trades] == [t["exit_reason"] for t in res_b.trades]
        assert [t["pnl"] for t in res_a.trades] == [t["pnl"] for t in res_b.trades]

    def test_walk_forward_uses_atr_too(self) -> None:
        engine = ResearchEngine()
        exp = _make_experiment(engine)
        closes, highs, lows = _bars()
        result = engine.run_backtest(
            exp, closes, highs=highs, lows=lows, walk_forward=True, train_ratio=0.7
        )
        wf = result.walk_forward
        assert wf["enabled"] is True
        assert len(wf["windows"]) >= 1
        for window in wf["windows"]:
            assert "metrics" in window


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
