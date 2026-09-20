# -*- coding: utf-8 -*-
"""Tests for System SLO / Health Target (Phase 56)."""

from src.monitoring.slo import ALL_SLIS, DEFAULT_SLOS, SLO, SLIName, SLOTracker


def test_all_slis_covered_by_default_slos() -> None:
    covered = {s.sli for s in DEFAULT_SLOS}
    assert set(ALL_SLIS) <= covered


def test_percentiles_computed() -> None:
    tracker = SLOTracker()
    for v in range(1, 101):  # 1..100
        tracker.record(SLIName.MARKET_FEED_FRESHNESS, float(v))
    stats = tracker.stats(SLIName.MARKET_FEED_FRESHNESS)
    assert stats is not None
    assert stats.count == 100
    assert 49 <= stats.p50 <= 51
    assert stats.p95 > stats.p50
    assert stats.p99 >= stats.p95


def test_no_data_verdict() -> None:
    tracker = SLOTracker()
    result = tracker.evaluate(SLIName.LLM_AVAILABILITY)
    assert result["status"] == "NO_DATA"
    assert result["breach"] is False


def test_latency_breach_detected() -> None:
    tracker = SLOTracker()
    # Feed freshness target p95 = 5s; feed lots of stale values.
    for _ in range(100):
        tracker.record(SLIName.MARKET_FEED_FRESHNESS, 30.0)
    result = tracker.evaluate(SLIName.MARKET_FEED_FRESHNESS)
    assert result["status"] == "BREACH"
    assert result["breach"] is True


def test_latency_ok() -> None:
    tracker = SLOTracker()
    for _ in range(100):
        tracker.record(SLIName.MARKET_FEED_FRESHNESS, 1.0)
    result = tracker.evaluate(SLIName.MARKET_FEED_FRESHNESS)
    assert result["status"] == "OK"


def test_ratio_breach_detected() -> None:
    tracker = SLOTracker()
    # API availability target 0.999; send lower availability samples.
    for _ in range(100):
        tracker.record(SLIName.API_AVAILABILITY, 0.9)
    result = tracker.evaluate(SLIName.API_AVAILABILITY)
    assert result["breach"] is True


def test_ratio_ok() -> None:
    tracker = SLOTracker()
    for _ in range(100):
        tracker.record(SLIName.API_AVAILABILITY, 1.0)
    result = tracker.evaluate(SLIName.API_AVAILABILITY)
    assert result["breach"] is False


def test_custom_slo_no_slo_verdict() -> None:
    tracker = SLOTracker(slos=())
    tracker.record("custom_sli", 1.0)
    result = tracker.evaluate("custom_sli")
    assert result["status"] == "NO_SLO"


def test_breaching_and_report() -> None:
    tracker = SLOTracker()
    for _ in range(100):
        tracker.record(SLIName.MARKET_FEED_FRESHNESS, 99.0)  # breach
        tracker.record(SLIName.API_AVAILABILITY, 1.0)  # ok
    breaching = tracker.breaching()
    assert any(r["sli"] == SLIName.MARKET_FEED_FRESHNESS for r in breaching)
    report = tracker.report()
    assert SLIName.MARKET_FEED_FRESHNESS in report["breaching"]


def test_custom_slo_override() -> None:
    tracker = SLOTracker()
    tracker.record(SLIName.SCHEDULER_HEALTH, 0.5)
    slo = SLO(SLIName.SCHEDULER_HEALTH, 0.4, kind="ratio")
    result = tracker.evaluate(SLIName.SCHEDULER_HEALTH, slo)
    # 0.5 >= 0.4 → OK
    assert result["breach"] is False
