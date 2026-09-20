# -*- coding: utf-8 -*-
"""Tests for Phase 41c/41d — parameter sensitivity & rule-engine status."""

from src.research.monte_carlo import (
    MonteCarloResult,
    ParameterSensitivity,
    classify_status,
    parameter_sensitivity,
)


def _mc(
    median_return: float = 5.0,
    perc5_return: float = 1.0,
    prob_severe_dd: float = 0.0,
    raw_returns: list | None = None,
) -> MonteCarloResult:
    return MonteCarloResult(
        median_return=median_return,
        perc5_return=perc5_return,
        prob_severe_dd=prob_severe_dd,
        raw_returns=raw_returns if raw_returns is not None else [1.0] * 10,
        status="OK",
    )


def test_status_insufficient_data() -> None:
    status, reasons = classify_status(_mc(), num_trades=5)
    assert status == "INSUFFICIENT_DATA"
    assert any("trades" in r for r in reasons)


def test_status_failed_negative_median() -> None:
    status, reasons = classify_status(_mc(median_return=-2.0), num_trades=100)
    assert status == "FAILED"
    assert any("median return negative" in r for r in reasons)


def test_status_fragile_perc5() -> None:
    status, reasons = classify_status(_mc(perc5_return=-3.0), num_trades=100)
    assert status == "FRAGILE"
    assert any("5th-percentile" in r for r in reasons)


def test_status_fragile_severe_dd() -> None:
    status, reasons = classify_status(_mc(prob_severe_dd=0.5), num_trades=100)
    assert status == "FRAGILE"
    assert any("severe drawdown" in r for r in reasons)


def test_status_fragile_cliff_edge() -> None:
    sens = ParameterSensitivity(baseline_metric=10.0, cliff_edge=True, worst_drop_pct=60.0)
    status, reasons = classify_status(_mc(), sensitivity=sens, num_trades=100)
    assert status == "FRAGILE"
    assert any("cliff edge" in r for r in reasons)


def test_status_robust() -> None:
    status, reasons = classify_status(_mc(), num_trades=100)
    assert status == "ROBUST"
    assert any("passed" in r for r in reasons)


def test_parameter_sensitivity_no_cliff() -> None:
    # A metric that is insensitive to the parameter → no cliff edge.
    def evaluate(params: dict) -> float:
        return 10.0

    sens = parameter_sensitivity(evaluate, {"fast_ema_period": 10}, cliff_drop_pct=40.0)
    assert isinstance(sens, ParameterSensitivity)
    assert not sens.cliff_edge
    assert len(sens.points) == 4


def test_parameter_sensitivity_cliff_detected() -> None:
    # A metric that collapses as soon as the parameter deviates → cliff edge.
    def evaluate(params: dict) -> float:
        val = params["fast_ema_period"]
        return 10.0 if val == 10 else 0.0

    sens = parameter_sensitivity(evaluate, {"fast_ema_period": 10}, cliff_drop_pct=40.0)
    assert sens.cliff_edge
    assert sens.worst_drop_pct >= 40.0


def test_parameter_sensitivity_skips_non_numeric() -> None:
    def evaluate(params: dict) -> float:
        return 5.0

    sens = parameter_sensitivity(evaluate, {"mode": "trend", "period": 20})
    # Only the numeric 'period' should be varied → 4 points.
    assert len(sens.points) == 4
    assert all(p.parameter == "period" for p in sens.points)
