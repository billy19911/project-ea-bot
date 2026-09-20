# -*- coding: utf-8 -*-
"""Tests for Performance Intelligence Engine (Phase 42)."""

from datetime import datetime, timezone

from src.review.performance_intelligence import DIMENSIONS, PerformanceIntelligence, TradeRow


def _ts(hour: int, weekday: int = 1) -> datetime:
    # 2024-01-01 is a Monday.
    return datetime(2024, 1, 1 + (weekday % 7), hour, 0, tzinfo=timezone.utc)


def _trade(pnl: float, hour: int = 14, symbol: str = "EURUSD", **kwargs) -> TradeRow:
    return TradeRow(pnl=pnl, r_multiple=pnl / 100.0, timestamp=_ts(hour), symbol=symbol, **kwargs)


def test_dimensions_present() -> None:
    for dim in ("hour", "weekday", "session", "symbol", "regime", "direction"):
        assert dim in DIMENSIONS


def test_grouping_by_hour() -> None:
    trades = [_trade(10.0, hour=14) for _ in range(40)] + [_trade(-5.0, hour=15) for _ in range(35)]
    engine = PerformanceIntelligence(min_sample=30)
    result = engine.analyze(trades, dimensions=["hour"])
    buckets = {b.key: b for b in result["hour"]}
    assert buckets["14"].count == 40
    assert buckets["14"].wins == 40
    assert buckets["15"].count == 35
    assert buckets["15"].losses == 35


def test_insufficient_sample_rule() -> None:
    trades = [_trade(10.0, hour=9) for _ in range(3)]
    engine = PerformanceIntelligence(min_sample=30)
    result = engine.analyze(trades, dimensions=["hour"])
    bucket = result["hour"][0]
    assert bucket.reliable is False
    assert bucket.status == "INSUFFICIENT_SAMPLE"


def test_reliable_bucket() -> None:
    trades = [_trade(10.0, hour=14) for _ in range(35)]
    engine = PerformanceIntelligence(min_sample=30)
    result = engine.analyze(trades, dimensions=["hour"])
    bucket = result["hour"][0]
    assert bucket.reliable is True
    assert bucket.status == "RELIABLE"
    assert bucket.win_rate == 100.0


def test_profit_factor_and_expectancy() -> None:
    trades = [_trade(100.0, hour=14) for _ in range(20)] + [
        _trade(-50.0, hour=14) for _ in range(20)
    ]
    engine = PerformanceIntelligence(min_sample=10)
    result = engine.analyze(trades, dimensions=["hour"])
    bucket = result["hour"][0]
    assert bucket.count == 40
    assert bucket.profit_factor == 2000.0 / 1000.0  # gross profit 2000 / gross loss 1000
    assert bucket.expectancy == (2000.0 - 1000.0) / 40


def test_advisory_only_flag() -> None:
    trades = [_trade(10.0, hour=14) for _ in range(35)]
    engine = PerformanceIntelligence(min_sample=30)
    result = engine.analyze(trades, dimensions=["hour"])
    for bucket in result["hour"]:
        assert bucket.advisory is True
        assert bucket.to_dict()["advisory"] is True


def test_top_buckets_reliable_only() -> None:
    trades = [_trade(50.0, hour=14) for _ in range(40)] + [  # reliable, high expectancy
        _trade(1.0, hour=15) for _ in range(3)
    ]  # unreliable
    engine = PerformanceIntelligence(min_sample=30)
    top = engine.top_buckets(trades, "hour", limit=5)
    assert len(top) == 1
    assert top[0].key == "14"
    unreliable = engine.unreliable_buckets(trades, "hour")
    assert [b.key for b in unreliable] == ["15"]


def test_missing_dimension_values_skipped() -> None:
    trades = [TradeRow(pnl=10.0)]  # no timestamp/symbol
    engine = PerformanceIntelligence(min_sample=1)
    result = engine.analyze(trades, dimensions=["hour", "symbol"])
    assert result["hour"] == []
    assert result["symbol"] == []
