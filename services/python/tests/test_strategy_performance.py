# -*- coding: utf-8 -*-
"""Tests for real strategy performance computation (FOKUS #4).

The Strategy Center showed "—" because metrics_summary was never populated.
These tests pin the metric definitions and the honest NO_DATA behaviour.
"""

from __future__ import annotations

from strategy.performance import (
    _extract_pnls,
    _max_drawdown,
    apply_performance_to_registry,
    compute_performance,
)
from strategy.registry import StrategyRegistry


def test_no_trades_returns_no_data_not_fake_zero():
    perf = compute_performance([])
    assert perf["status"] == "NO_DATA"
    assert perf["trades"] == 0
    # No fabricated metric keys — the UI must render "—", not a fake 0.
    assert "win_rate" not in perf
    assert "profit_factor" not in perf


def test_win_rate_and_profit_factor():
    # 3 wins (10, 20, 30) and 1 loss (-20): win rate 75%, PF = 60/20 = 3.0.
    perf = compute_performance([10.0, 20.0, 30.0, -20.0])
    assert perf["trades"] == 4
    assert perf["win_rate"] == 75.0
    assert perf["profit_factor"] == 3.0
    assert perf["total_pnl"] == 40.0


def test_max_drawdown_on_equity_curve():
    # Equity curve: 100, 50, 120, 20 → peak 120, trough 20 → DD 100.
    assert _max_drawdown([100.0, 50.0, 120.0, 20.0]) == 100.0


def test_max_drawdown_monotonic_curve_is_zero():
    assert _max_drawdown([10.0, 20.0, 30.0]) == 0.0


def test_sharpe_zero_variance_is_zero():
    perf = compute_performance([5.0, 5.0, 5.0])
    assert perf["sharpe"] == 0.0


def test_low_sample_status():
    perf = compute_performance([1.0, -1.0, 2.0])
    assert perf["status"] == "LOW_SAMPLE"
    assert perf["trades"] == 3


def test_extract_pnls_skips_non_numeric_and_missing():
    lessons = [
        {"pnl": 10.0},
        {"pnl": "bad"},
        {"pnl": None},
        {"no_pnl": 1},
        {"pnl": float("nan")},
        {"pnl": 5},
    ]
    assert _extract_pnls(lessons) == [10.0, 5.0]


def test_apply_performance_writes_to_active_strategy():
    registry = StrategyRegistry()
    registry.register("technical_analysis", "v1.0.0", {"min_confidence": 0.5})
    registry.activate("technical_analysis", "v1.0.0")

    lessons = [{"pnl": 100.0}, {"pnl": -50.0}, {"pnl": 25.0}]
    perf = apply_performance_to_registry(registry, lessons)

    assert perf["trades"] == 3
    stored = registry.get("technical_analysis", "v1.0.0").metrics_summary
    assert stored["win_rate"] == perf["win_rate"]
    assert stored["profit_factor"] == perf["profit_factor"]


def test_apply_performance_no_data_sets_status():
    registry = StrategyRegistry()
    registry.register("technical_analysis", "v1.0.0", {})
    registry.activate("technical_analysis", "v1.0.0")
    perf = apply_performance_to_registry(registry, [])
    assert perf["status"] == "NO_DATA"
    assert registry.get("technical_analysis", "v1.0.0").metrics_summary["status"] == "NO_DATA"
