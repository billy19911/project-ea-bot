# -*- coding: utf-8 -*-
"""Tests for Phase 39 — Research Engine 2.0 realistic backtester."""

from datetime import datetime, timedelta, timezone

from src.research.backtest_v2 import Bar, CostModel, RealisticBacktester, RiskConfig, SymbolSpec


def _make_bars(prices: list[float], start_hour: int = 8) -> list[Bar]:
    base = datetime(2024, 1, 1, start_hour, 0, tzinfo=timezone.utc)
    bars = []
    for i, p in enumerate(prices):
        bars.append(
            Bar(
                time=base + timedelta(hours=i),
                open=p,
                high=p * 1.001,
                low=p * 0.999,
                close=p,
            )
        )
    return bars


def _ema_signal(bars: list[Bar], idx: int) -> int:
    """Tiny deterministic momentum signal for tests."""
    if idx < 2:
        return 0
    return 1 if bars[idx].close >= bars[idx - 1].close else -1


def test_metrics_present() -> None:
    prices = [1.08 + 0.0005 * i for i in range(50)]
    bars = _make_bars(prices)
    bt = RealisticBacktester()
    result = bt.run(bars, _ema_signal)
    required = [
        "total_return",
        "net_profit",
        "profit_factor",
        "expectancy",
        "win_rate",
        "loss_rate",
        "average_r",
        "max_drawdown",
        "max_consecutive_losses",
        "recovery_factor",
        "sharpe",
        "sortino",
        "trade_frequency",
        "average_hold_time",
    ]
    for key in required:
        assert key in result.metrics, f"missing metric {key}"


def test_breakdowns_present() -> None:
    prices = [1.08 + 0.0005 * i for i in range(50)]
    bars = _make_bars(prices)
    bt = RealisticBacktester()
    result = bt.run(bars, _ema_signal)
    assert isinstance(result.profit_by_session, dict)
    assert isinstance(result.profit_by_hour, dict)
    assert isinstance(result.profit_by_regime, dict)


def test_costs_reduce_net_pnl() -> None:
    prices = [1.08 + 0.0005 * i for i in range(60)]
    bars = _make_bars(prices)
    no_cost = RealisticBacktester(
        costs=CostModel(spread_points=0, slippage_points=0, commission_per_lot=0)
    ).run(bars, _ema_signal)
    with_cost = RealisticBacktester(
        costs=CostModel(spread_points=20, slippage_points=5, commission_per_lot=10)
    ).run(bars, _ema_signal)
    assert with_cost.metrics["net_profit"] <= no_cost.metrics["net_profit"]


def test_session_filter_blocks_trades() -> None:
    prices = [1.08 + 0.0005 * i for i in range(50)]
    bars = _make_bars(prices, start_hour=2)  # 02:00 UTC start
    bt = RealisticBacktester(risk=RiskConfig(session_hours_utc=(7, 20)))
    result = bt.run(bars, _ema_signal)
    # All trades (if any) must have entered within the allowed window.
    for t in result.trades:
        assert 7 <= t.entry_time.hour < 20


def test_empty_trades_degrades_safely() -> None:
    bars = _make_bars([1.08, 1.08, 1.08])
    bt = RealisticBacktester()

    def flat(_bars: list[Bar], _idx: int) -> int:
        return 0

    result = bt.run(bars, flat)
    assert result.metrics["net_profit"] == 0.0
    assert result.metrics["total_return"] == 0.0
    assert result.trades == []


def test_symbol_spec_normalizes_lot() -> None:
    spec = SymbolSpec(min_lot=0.01, lot_step=0.01)
    assert spec.normalize_lot(0.005) == 0.01
    assert spec.normalize_lot(0.123) == 0.12
    assert spec.normalize_lot(100.0) == 100.0  # no max clamp here
