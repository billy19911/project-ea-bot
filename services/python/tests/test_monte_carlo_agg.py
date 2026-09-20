# -*- coding: utf-8 -*-
"""Tests for Monte Carlo metric aggregation (Phase 41b)."""

from datetime import datetime, timedelta, timezone

from src.research.backtest_v2 import Bar, CostModel
from src.research.monte_carlo import MonteCarloRunner


def _bars(num: int, start_price: float = 1.08) -> list[Bar]:
    base = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
    bars = []
    price = start_price
    for i in range(num):
        bars.append(
            Bar(
                time=base + timedelta(hours=i),
                open=price,
                high=price * 1.001,
                low=price * 0.999,
                close=price,
            )
        )
        price += 0.0005
    return bars


def _simple_signal(_bars: list[Bar], idx: int) -> int:
    if idx < 1:
        return 0
    return 1 if _bars[idx].close >= _bars[idx - 1].close else -1


def test_basic_aggregation() -> None:
    bars = _bars(30)
    runner = MonteCarloRunner(n_sims=100, seed=42)
    result = runner.run(bars, _simple_signal)
    # All fields should be present and sensible.
    for field in [
        "median_return",
        "perc5_return",
        "perc95_drawdown",
        "worst_drawdown",
        "max_loss_streak",
        "prob_severe_dd",
        "status",
    ]:
        assert hasattr(result, field), f"missing {field}"
    assert result.status in {"ROBUST", "FRAGILE"}


def test_insufficient_data() -> None:
    # Too few bars leads to insufficient data after bootstrap.
    bars = _bars(3)
    runner = MonteCarloRunner(n_sims=10, seed=1)
    result = runner.run(bars, _simple_signal)
    assert result.status == "INSUFFICIENT_DATA"


def test_resampling_effect() -> None:
    # With a constant flat price series the baseline has zero trades –
    # after resampling we still expect zero returns.
    bars = [
        Bar(time=datetime(2024, 1, 1, tzinfo=timezone.utc), open=1.0, high=1.0, low=1.0, close=1.0)
        for _ in range(20)
    ]
    runner = MonteCarloRunner(
        n_sims=20,
        seed=99,
        spread_std=0.0,
        slippage_std=0.0,
        base_costs=CostModel(spread_points=0.0, slippage_points=0.0),
        exec_delay_std=0.0,
    )

    result = runner.run(bars, _simple_signal)
    # No variation, median return should be <=0 and status FRAGILE.
    assert result.median_return <= 0.0
    assert result.status == "FRAGILE"
