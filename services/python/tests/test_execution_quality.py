# -*- coding: utf-8 -*-
"""Tests for Execution Quality Analytics (Phase 47)."""

from src.observability.execution_quality import ExecutionQualityAnalytics, ExecutionRecord


def _rec(
    requested: float = 1.0850,
    fill: float = 1.0850,
    direction: int = 1,
    rejected: bool = False,
    partial: bool = False,
    latency: float = 50.0,
    session: str = "london",
    volatility: str = "normal",
) -> ExecutionRecord:
    return ExecutionRecord(
        requested_entry=requested,
        actual_fill=fill,
        direction=direction,
        latency_ms=latency,
        rejected=rejected,
        partial=partial,
        session=session,
        volatility=volatility,
    )


def test_slippage_direction_buy_adverse() -> None:
    # Buy filled higher than requested → positive (adverse) slippage.
    rec = _rec(requested=1.0850, fill=1.0853, direction=1)
    assert round(rec.slippage, 6) == 0.0003


def test_slippage_direction_sell_adverse() -> None:
    # Sell filled lower than requested → positive (adverse) slippage.
    rec = _rec(requested=1.0850, fill=1.0847, direction=-1)
    assert round(rec.slippage, 6) == 0.0003


def test_average_and_p95_slippage() -> None:
    analytics = ExecutionQualityAnalytics()
    for fill in (1.0851, 1.0852, 1.0853, 1.0854, 1.0855):
        analytics.record(_rec(requested=1.0850, fill=fill))
    assert round(analytics.average_slippage(), 6) == 0.0003
    assert analytics.p95_slippage() >= 0.0004


def test_rejection_and_partial_rates() -> None:
    analytics = ExecutionQualityAnalytics()
    analytics.record(_rec())
    analytics.record(_rec(rejected=True))
    analytics.record(_rec(partial=True))
    analytics.record(_rec())
    assert analytics.rejection_rate() == 0.25
    assert analytics.partial_fill_rate() == 0.25


def test_fill_delay() -> None:
    analytics = ExecutionQualityAnalytics()
    analytics.record(_rec(latency=100))
    analytics.record(_rec(latency=200))
    assert analytics.fill_delay() == 150.0


def test_by_session_and_volatility() -> None:
    analytics = ExecutionQualityAnalytics()
    analytics.record(_rec(session="london", volatility="high", latency=80))
    analytics.record(_rec(session="new_york", volatility="low", latency=40))
    by_session = analytics.by_session()
    assert "london" in by_session and "new_york" in by_session
    assert by_session["london"]["avg_latency_ms"] == 80.0
    by_vol = analytics.by_volatility()
    assert set(by_vol) == {"high", "low"}


def test_summary_contains_all_metrics() -> None:
    analytics = ExecutionQualityAnalytics()
    analytics.record(_rec())
    summary = analytics.summary()
    for key in (
        "average_slippage",
        "p95_slippage",
        "fill_delay",
        "rejection_rate",
        "partial_fill_rate",
        "execution_by_session",
        "execution_by_volatility",
    ):
        assert key in summary


def test_alerts_fire_on_high_slippage() -> None:
    analytics = ExecutionQualityAnalytics(high_slippage_threshold=0.0001)
    analytics.record(_rec(requested=1.0850, fill=1.0860))
    alerts = analytics.alerts()
    assert any("slippage" in a for a in alerts)


def test_alerts_fire_on_high_rejection() -> None:
    analytics = ExecutionQualityAnalytics(high_rejection_rate=0.10)
    analytics.record(_rec(rejected=True))
    analytics.record(_rec())
    analytics.record(_rec())
    alerts = analytics.alerts()
    assert any("rejection rate" in a for a in alerts)


def test_no_alerts_when_clean() -> None:
    analytics = ExecutionQualityAnalytics()
    analytics.record(_rec())
    assert analytics.alerts() == []
