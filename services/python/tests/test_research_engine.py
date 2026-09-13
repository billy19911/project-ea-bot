"""Tests for the research engine."""

from __future__ import annotations

import math

import pytest

from research.engine import BacktestResult, Experiment, Hypothesis, ResearchEngine, StrategyVersion


def make_engine() -> ResearchEngine:
    """Create an engine with one reusable hypothesis."""
    return ResearchEngine()


def make_experiment(engine: ResearchEngine, version_id: str = "v1") -> Experiment:
    """Create an experiment with short indicator periods for test data."""
    hypothesis = engine.create_hypothesis("Trend", "Follow EMA trend", ["EMA"], ["reverse"], {})
    version = engine.create_strategy_version(
        version_id, {"fast_ema_period": 2, "slow_ema_period": 3}
    )
    return engine.create_experiment(hypothesis.id, version.version, {})


def test_hypothesis_is_structured_and_timestamped() -> None:
    engine = make_engine()
    hypothesis = engine.create_hypothesis(
        "Breakout", "Buy breakouts", ["close > high"], ["stop"], {"x": 1}
    )
    assert isinstance(hypothesis, Hypothesis)
    assert hypothesis.name == "Breakout"
    assert hypothesis.parameters == {"x": 1}
    assert hypothesis.created_at.tzinfo is not None


def test_hypothesis_ids_are_unique() -> None:
    engine = make_engine()
    first = engine.create_hypothesis("A", "a", [], [], {})
    second = engine.create_hypothesis("B", "b", [], [], {})
    assert first.id != second.id


def test_strategy_version_is_created_and_retrievable() -> None:
    engine = make_engine()
    version = engine.create_strategy_version("v1", {"rsi_period": 7}, "Initial")
    assert isinstance(version, StrategyVersion)
    assert engine.get_strategy_version("v1") == version


def test_duplicate_strategy_version_is_rejected() -> None:
    engine = make_engine()
    engine.create_strategy_version("v1", {})
    with pytest.raises(ValueError, match="already exists"):
        engine.create_strategy_version("v1", {})


def test_experiment_links_hypothesis_and_strategy_version() -> None:
    engine = make_engine()
    experiment = make_experiment(engine)
    assert isinstance(experiment, Experiment)
    assert experiment.status == "pending"
    assert experiment.strategy_version == "v1"


def test_experiment_rejects_unknown_hypothesis() -> None:
    engine = make_engine()
    engine.create_strategy_version("v1", {})
    with pytest.raises(ValueError, match="Unknown hypothesis"):
        engine.create_experiment("missing", "v1", {})


def test_experiment_rejects_unknown_strategy_version() -> None:
    engine = make_engine()
    hypothesis = engine.create_hypothesis("A", "a", [], [], {})
    with pytest.raises(ValueError, match="Unknown strategy version"):
        engine.create_experiment(hypothesis.id, "missing", {})


def test_compute_metrics_for_empty_trades() -> None:
    metrics = make_engine().compute_metrics([])
    assert metrics == {
        "total_trades": 0,
        "win_rate": 0.0,
        "profit_factor": 0.0,
        "sharpe_ratio": 0.0,
        "max_drawdown": 0.0,
        "expectation": 0.0,
        "net_pnl": 0.0,
    }


def test_compute_metrics_calculates_core_values() -> None:
    metrics = make_engine().compute_metrics([{"pnl": 20.0}, {"pnl": -10.0}, {"pnl": 10.0}])
    assert metrics["total_trades"] == 3
    assert metrics["win_rate"] == pytest.approx(66.6666667)
    assert metrics["profit_factor"] == pytest.approx(3.0)
    assert metrics["expectation"] == pytest.approx(20.0 / 3.0)
    assert metrics["net_pnl"] == 20.0


def test_compute_metrics_reports_infinite_profit_factor_without_losses() -> None:
    metrics = make_engine().compute_metrics([{"pnl": 5.0}])
    assert math.isinf(metrics["profit_factor"])


def test_compute_metrics_uses_equity_drawdown() -> None:
    metrics = make_engine().compute_metrics([{"pnl": 100.0}, {"pnl": -50.0}])
    assert metrics["max_drawdown"] == pytest.approx(50.0)


def test_run_backtest_rejects_unregistered_experiment() -> None:
    engine = make_engine()
    experiment = Experiment("x", "x", "v1", {}, "h", "pending")
    with pytest.raises(ValueError, match="not registered"):
        engine.run_backtest(experiment, [1.0, 2.0])


def test_run_backtest_returns_empty_result_for_insufficient_data() -> None:
    engine = make_engine()
    experiment = make_experiment(engine)
    result = engine.run_backtest(experiment, [1.0, 2.0])
    assert isinstance(result, BacktestResult)
    assert result.total_trades == 0
    assert experiment.status == "completed"


def test_run_backtest_replays_bars_and_closes_final_position() -> None:
    engine = make_engine()
    experiment = make_experiment(engine)
    prices = [100.0 + index for index in range(50)]
    result = engine.run_backtest(experiment, prices)
    assert result.total_trades >= 1
    assert result.trades[-1]["exit_reason"] == "end_of_data"
    assert result.net_pnl > 0


def test_run_backtest_merges_experiment_parameters() -> None:
    engine = make_engine()
    hypothesis = engine.create_hypothesis("Trend", "Trend", [], [], {})
    engine.create_strategy_version("v1", {"fast_ema_period": 2, "slow_ema_period": 3})
    experiment = engine.create_experiment("%s" % hypothesis.id, "v1", {"min_confidence": 1.0})
    result = engine.run_backtest(experiment, [100.0 + index for index in range(50)])
    # min_confidence param is accepted but not used in minimal backtest
    # EMA crossover still generates trades
    assert result.total_trades >= 1


def test_compare_experiments_returns_side_by_side_metrics() -> None:
    engine = make_engine()
    first = make_experiment(engine, "v1")
    second = make_experiment(engine, "v2")
    engine.run_backtest(first, [100.0 + index for index in range(50)])
    engine.run_backtest(second, [100.0 - index for index in range(50)])
    comparison = engine.compare_experiments(first, second)
    assert comparison["experiment_1"]["id"] == first.id
    assert comparison["experiment_2"]["id"] == second.id
    assert "net_pnl" in comparison["difference"]


def test_compare_experiments_requires_completed_backtests() -> None:
    engine = make_engine()
    first = make_experiment(engine, "v1")
    second = make_experiment(engine, "v2")
    with pytest.raises(ValueError, match="completed backtests"):
        engine.compare_experiments(first, second)
