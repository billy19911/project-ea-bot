# -*- coding: utf-8 -*-
"""Tests for PRD §18.3/§32.23 supervisor KPI completeness."""

from __future__ import annotations

from learning.performance import PerformanceTracker

# ---------------------------------------------------------------------------
# no_trade_quality
# ---------------------------------------------------------------------------


def test_no_trade_quality_computed():
    tracker = PerformanceTracker(min_sample_size=1)
    # 3 correct no-trade decisions (avoided loss) + 1 missed gain = 75%.
    tracker.record_no_trade_decision(would_have_won=False, reason="low_confidence")
    tracker.record_no_trade_decision(would_have_won=False, reason="risk_limit")
    tracker.record_no_trade_decision(would_have_won=False, reason="no_setup")
    tracker.record_no_trade_decision(would_have_won=True, reason="low_confidence")

    kpis = tracker.supervisor_kpis()
    assert kpis["no_trade_decisions"] == 4
    assert kpis["no_trade_quality"] == 75.0


def test_no_trade_quality_pure():
    tracker = PerformanceTracker(min_sample_size=1)
    tracker.record_no_trade_decision(would_have_won=False)
    tracker.record_no_trade_decision(would_have_won=False)
    assert tracker.no_trade_quality() == 100.0


def test_no_trade_quality_none_when_empty():
    tracker = PerformanceTracker()
    assert tracker.no_trade_quality() is None
    kpis = tracker.supervisor_kpis()
    assert kpis["no_trade_quality"] == 0.0
    assert kpis["no_trade_decisions"] == 0


# ---------------------------------------------------------------------------
# Breakdowns
# ---------------------------------------------------------------------------


def test_breakdowns_present_and_deterministic():
    tracker = PerformanceTracker(min_sample_size=1)
    tracker.record_trade(
        pnl=100.0, outcome="WIN", session="london", hour=9, regime="up", setup="bo"
    )
    tracker.record_trade(
        pnl=-40.0, outcome="LOSS", session="asia", hour=3, regime="range", setup="fade"
    )
    tracker.record_trade(pnl=60.0, outcome="WIN", session="london", hour=9, regime="up", setup="bo")

    kpis = tracker.supervisor_kpis()
    breakdowns = kpis["breakdowns"]
    assert set(breakdowns) == {"by_session", "by_hour", "by_regime", "by_setup"}
    assert breakdowns["by_session"]["london"]["count"] == 2
    assert breakdowns["by_session"]["london"]["win_rate"] == 100.0
    assert breakdowns["by_session"]["asia"]["count"] == 1
    assert breakdowns["by_hour"]["9"]["count"] == 2
    assert breakdowns["by_regime"]["up"]["total_pnl"] == 160.0
    assert breakdowns["by_setup"]["bo"]["count"] == 2


def test_breakdowns_empty_history():
    tracker = PerformanceTracker()
    breakdowns = tracker.breakdowns()
    assert breakdowns == {
        "by_session": {},
        "by_hour": {},
        "by_regime": {},
        "by_setup": {},
    }
    kpis = tracker.supervisor_kpis()
    assert kpis["breakdowns"] == breakdowns


# ---------------------------------------------------------------------------
# Bounded history
# ---------------------------------------------------------------------------


def test_history_is_bounded():
    tracker = PerformanceTracker(min_sample_size=1, max_history=5)
    for i in range(12):
        tracker.record_trade(pnl=float(i), outcome="WIN", hour=9)
    assert len(tracker._trades) == 5
    # Buckets rebuilt from retained trades only.
    assert tracker.get_hour_stats(9)["count"] == 5


def test_no_trade_history_is_bounded():
    tracker = PerformanceTracker(max_history=3)
    for _ in range(10):
        tracker.record_no_trade_decision(would_have_won=False)
    assert len(tracker._no_trades) == 3
    assert tracker.no_trade_quality() == 100.0


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------


def test_existing_kpis_still_present():
    tracker = PerformanceTracker(min_sample_size=1)
    tracker.record_trade(pnl=100.0)
    tracker.record_trade(pnl=-50.0)
    kpis = tracker.supervisor_kpis()
    for key in (
        "total_trades",
        "win_rate",
        "profit_factor",
        "expectancy",
        "max_drawdown",
        "false_signals",
        "no_trade_quality",
        "breakdowns",
    ):
        assert key in kpis
