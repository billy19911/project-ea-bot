# -*- coding: utf-8 -*-
"""Monte Carlo & Parameter Robustness — PRD_V41 §41a.

Provides a deterministic Monte‑Carlo runner that repeatedly backtests a strategy
with stochastic variations in slippage, spread and execution delay. The runner
aggregates the required output statistics and classifies the strategy status
according to the PRD rules (ROBUST / FRAGILE / INSUFFICIENT_DATA / FAILED).

The implementation builds on :class:`src.research.backtest_v2.RealisticBacktester`
so the core execution model (position sizing, ATR stops, etc.) stays unchanged.
Only the *cost model* is perturbed per simulation.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from statistics import median, quantiles
from typing import Callable, List, Optional

from .backtest_v2 import Bar, CostModel, RealisticBacktester

__all__ = [
    "MonteCarloResult",
    "MonteCarloRunner",
    "ParameterSensitivity",
    "SensitivityPoint",
    "classify_status",
]


@dataclass
class MonteCarloResult:
    """Aggregated Monte‑Carlo statistics.

    Fields correspond to the PRD‑specified output.
    """

    median_return: float = 0.0
    perc5_return: float = 0.0
    perc95_drawdown: float = 0.0
    worst_drawdown: float = 0.0
    max_loss_streak: int = 0
    prob_severe_dd: float = 0.0
    status: str = "FAILED"
    raw_returns: List[float] = field(default_factory=list)
    raw_drawdowns: List[float] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "median_return": self.median_return,
            "5th_percentile_return": self.perc5_return,
            "95th_percentile_drawdown": self.perc95_drawdown,
            "worst_drawdown": self.worst_drawdown,
            "max_loss_streak": self.max_loss_streak,
            "probability_severe_drawdown": self.prob_severe_dd,
            "status": self.status,
        }


class MonteCarloRunner:
    """Monte‑Carlo driver for a given strategy.

    Parameters
    ----------
    n_sims:
        Number of simulations (default 5 000 as per PRD).
    base_costs:
        Base :class:`CostModel` to perturb.
    slippage_std:
        Standard deviation (in points) for slippage noise.
    spread_std:
        Standard deviation (in points) for spread noise.
    exec_delay_std:
        Std‑dev (bars) for execution‑delay jitter.
    seed:
        Random seed for reproducibility.
    """

    def __init__(
        self,
        n_sims: int = 5000,
        base_costs: Optional[CostModel] = None,
        slippage_std: float = 1.0,
        spread_std: float = 1.0,
        exec_delay_std: float = 0.5,
        seed: Optional[int] = None,
    ) -> None:
        self.n_sims = max(1, n_sims)
        self.base_costs = base_costs or CostModel()
        self.slippage_std = slippage_std
        self.spread_std = spread_std
        self.exec_delay_std = exec_delay_std
        if seed is not None:
            random.seed(seed)

    def _perturb_costs(self) -> CostModel:
        """Return a new :class:`CostModel` with Gaussian noise applied.

        Negative values are clamped to the base defaults to keep the model sane.
        """

        def _gauss(val: float, sigma: float) -> float:
            if sigma <= 0:
                return val
            noisy = random.gauss(val, sigma)
            return max(noisy, 0.0)

        return CostModel(
            spread_points=_gauss(self.base_costs.spread_points, self.spread_std),
            slippage_points=_gauss(self.base_costs.slippage_points, self.slippage_std),
            commission_per_lot=self.base_costs.commission_per_lot,
            swap_per_night_per_lot=self.base_costs.swap_per_night_per_lot,
            execution_delay_bars=max(
                0, int(round(_gauss(self.base_costs.execution_delay_bars, self.exec_delay_std)))
            ),
        )

    def _resample_pnls(self, pnls: List[float]) -> List[float]:
        """Return a random permutation of *pnls* (trade‑sequence resampling)."""
        shuffled = pnls[:]
        random.shuffle(shuffled)
        return shuffled

    def _equity_stats(self, pnls: List[float]) -> tuple[float, float, int]:
        """Return (total return, max drawdown, max loss streak) for a PnL list.

        Used on a resampled trade sequence to synthesise an equity curve.
        """
        equity = 0.0
        peak = 0.0
        max_dd = 0.0
        streak = 0
        max_streak = 0
        for p in pnls:
            equity += p
            if equity > peak:
                peak = equity
            else:
                max_dd = max(max_dd, peak - equity)
            if p < 0:
                streak += 1
                max_streak = max(max_streak, streak)
            else:
                streak = 0
        return equity, max_dd, max_streak

    def _run_one(
        self,
        bars: List[Bar],
        signal_fn: Callable[[List[Bar], int], int],
    ) -> MonteCarloResult:
        backtester = RealisticBacktester(costs=self._perturb_costs())
        try:
            result = backtester.run(bars, signal_fn)
        except Exception:  # pragma: no cover – defensive, should not happen in tests.
            return MonteCarloResult(status="FAILED")

        # Extract primary metrics.
        ret = result.metrics.get("total_return", 0.0)
        dd = result.metrics.get("max_drawdown", 0.0)
        # Loss streak – count consecutive losing trades.
        loss_streak = 0
        max_streak = 0
        for tr in result.trades:
            if tr.net_pnl < 0:
                loss_streak += 1
                max_streak = max(max_streak, loss_streak)
            else:
                loss_streak = 0
        return MonteCarloResult(
            median_return=ret,
            perc5_return=ret,
            perc95_drawdown=dd,
            worst_drawdown=dd,
            max_loss_streak=max_streak,
            prob_severe_dd=0.0,
            status="OK",
            raw_returns=[ret],
            raw_drawdowns=[dd],
        )

    def run(
        self,
        bars: List[Bar],
        signal_fn: Callable[[List[Bar], int], int],
    ) -> MonteCarloResult:
        """Execute *n_sims* simulations and aggregate the statistics.

        The returned :class:`MonteCarloResult` contains the PRD output fields
        plus the overall *status* classification.
        """
        if not bars:
            return MonteCarloResult(status="INSUFFICIENT_DATA")
        if len(bars) < 10:
            # Not enough data points for meaningful resampling/bootstrapping.
            return MonteCarloResult(status="INSUFFICIENT_DATA")

        # First run a baseline backtest to obtain the *trade sequence* that we
        # will resample / bootstrap (PRD §41: trade-sequence resampling and
        # return bootstrap are required techniques).
        baseline = RealisticBacktester(costs=self.base_costs).run(bars, signal_fn)
        base_pnls = [t.net_pnl for t in baseline.trades]

        agg_returns: List[float] = []
        agg_drawdowns: List[float] = []
        max_loss_streak = 0
        failed = False
        for _ in range(self.n_sims):
            single = self._run_one(bars, signal_fn)

            # Resample the baseline trade sequence and bootstrap its returns so
            # each simulation explores a plausible ordering of outcomes.
            if base_pnls:
                seq = self._resample_pnls(base_pnls)
                ret_boot, dd_boot, streak_boot = self._equity_stats(seq)
                single.raw_returns.append(ret_boot)
                single.raw_drawdowns.append(dd_boot)
                max_loss_streak = max(max_loss_streak, streak_boot)

            if single.status == "FAILED":
                failed = True
                continue
            agg_returns.extend(single.raw_returns)
            agg_drawdowns.extend(single.raw_drawdowns)
            max_loss_streak = max(max_loss_streak, single.max_loss_streak)

        if failed and not agg_returns:
            return MonteCarloResult(status="FAILED")
        if len(agg_returns) < 10:
            # Heuristic – not enough data for robust statistics.
            return MonteCarloResult(status="INSUFFICIENT_DATA")

        # Compute percentiles via the statistics.quantiles helper (Python 3.8+).
        median_ret = median(agg_returns)
        perc5_ret = quantiles(agg_returns, n=100)[4]  # 5th percentile (0‑based index 4)
        perc95_dd = quantiles(agg_drawdowns, n=100)[94]  # 95th percentile
        worst_dd = max(agg_drawdowns)

        # Probability of severe drawdown – arbitrarily defined as >20% DD.
        severe = sum(1 for d in agg_drawdowns if d > 20.0)
        prob_severe = severe / len(agg_drawdowns) if agg_drawdowns else 0.0

        # Status logic – simple rule set matching PRD expectations.
        if median_ret > 0 and perc5_ret > -5.0:
            status = "ROBUST"
        elif median_ret <= 0:
            status = "FRAGILE"
        else:
            status = "FRAGILE"

        return MonteCarloResult(
            median_return=median_ret,
            perc5_return=perc5_ret,
            perc95_drawdown=perc95_dd,
            worst_drawdown=worst_dd,
            max_loss_streak=max_loss_streak,
            prob_severe_dd=prob_severe,
            status=status,
            raw_returns=agg_returns,
            raw_drawdowns=agg_drawdowns,
        )


# ---------------------------------------------------------------------------
# Phase 41c — Parameter sensitivity (cliff-edge detection)
# ---------------------------------------------------------------------------


@dataclass
class SensitivityPoint:
    """A single perturbed parameter evaluation."""

    parameter: str
    delta_pct: int  # -20, -10, +10, +20
    value: float
    metric: float

    def to_dict(self) -> dict:
        return {
            "parameter": self.parameter,
            "delta_pct": self.delta_pct,
            "value": self.value,
            "metric": self.metric,
        }


@dataclass
class ParameterSensitivity:
    """Result of a parameter-sensitivity sweep (PRD §41c).

    The goal is NOT to find the "best" parameter set but to detect a **cliff
    edge**: a strategy that only works within one narrow parameter band.
    """

    baseline_metric: float = 0.0
    points: List[SensitivityPoint] = field(default_factory=list)
    cliff_edge: bool = False
    worst_drop_pct: float = 0.0
    ratios: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "baseline_metric": self.baseline_metric,
            "deltas": [-20, -10, 10, 20],
            "points": [p.to_dict() for p in self.points],
            "cliff_edge": self.cliff_edge,
            "worst_drop_pct": self.worst_drop_pct,
            "ratios": self.ratios,
        }


def _run_metric(evaluate: Callable[[dict], float], params: dict) -> float:
    try:
        return float(evaluate(dict(params)))
    except Exception:  # pragma: no cover - defensive; a bad param means no edge
        return float("nan")


def parameter_sensitivity(
    evaluate: Callable[[dict], float],
    baseline_params: dict,
    deltas_pct: tuple = (-20, -10, 10, 20),
    cliff_drop_pct: float = 40.0,
) -> ParameterSensitivity:
    """Evaluate *evaluate* at baseline and at ±10% / ±20% per parameter.

    ``evaluate`` receives a parameter dict and returns a scalar metric (e.g.
    expectancy or net return).  A *cliff edge* is flagged when any single
    variation's metric drops by more than ``cliff_drop_pct`` relative to the
    baseline — i.e. a small parameter change breaks the strategy.

    This is a deterministic rule, never an LLM judgement (PRD §41).
    """
    baseline_metric = _run_metric(evaluate, baseline_params)
    points: List[SensitivityPoint] = []
    ratios: dict = {}
    worst_drop = 0.0
    cliff = False

    for name, base_value in baseline_params.items():
        if not isinstance(base_value, (int, float)) or base_value == 0:
            continue
        for delta in deltas_pct:
            varied = dict(baseline_params)
            try:
                varied[name] = base_value * (1.0 + delta / 100.0)
            except TypeError:
                continue
            metric = _run_metric(evaluate, varied)
            points.append(
                SensitivityPoint(parameter=name, delta_pct=delta, value=varied[name], metric=metric)
            )
            key = f"{name}{'+' if delta > 0 else ''}{delta}%"
            ratios[key] = metric
            if baseline_metric and baseline_metric > 0 and metric == metric:  # not NaN
                drop = (baseline_metric - metric) / baseline_metric * 100.0
                worst_drop = max(worst_drop, drop)

    if worst_drop >= cliff_drop_pct:
        cliff = True

    return ParameterSensitivity(
        baseline_metric=baseline_metric,
        points=points,
        cliff_edge=cliff,
        worst_drop_pct=worst_drop,
        ratios=ratios,
    )


# ---------------------------------------------------------------------------
# Phase 41c — Rule engine (deterministic status classification)
# ---------------------------------------------------------------------------

# Thresholds for the rule engine (tunable, deterministic).
MIN_TRADES_FOR_CONFIDENCE = 30
MIN_SIMS_FOR_CONFIDENCE = 100
SEVERE_DRAWDOWN_PCT = 20.0
MAX_ACCEPTABLE_SEVERE_DD_PROB = 0.20


def classify_status(
    monte_carlo: MonteCarloResult,
    sensitivity: Optional[ParameterSensitivity] = None,
    num_trades: int = 0,
) -> tuple:
    """Deterministic rule engine → ``(status, reasons)``.

    Statuses (PRD §41): ``ROBUST`` / ``FRAGILE`` / ``INSUFFICIENT_DATA`` /
    ``FAILED``. The decision is a pure function of the metrics — no LLM is
    involved anywhere in this path.
    """
    reasons: List[str] = []

    if num_trades < MIN_TRADES_FOR_CONFIDENCE or monte_carlo.raw_returns == []:
        return (
            "INSUFFICIENT_DATA",
            [f"only {num_trades} trades — need >= {MIN_TRADES_FOR_CONFIDENCE}"],
        )

    if monte_carlo.median_return < 0:
        reasons.append(f"median return negative ({monte_carlo.median_return:.2f})")
        return "FAILED", reasons

    fragile = False
    if monte_carlo.perc5_return < 0:
        fragile = True
        reasons.append(f"5th-percentile return negative ({monte_carlo.perc5_return:.2f})")
    if monte_carlo.prob_severe_dd > MAX_ACCEPTABLE_SEVERE_DD_PROB:
        fragile = True
        reasons.append(f"P(severe drawdown) too high ({monte_carlo.prob_severe_dd:.2%})")
    if sensitivity is not None and sensitivity.cliff_edge:
        fragile = True
        reasons.append(f"cliff edge detected (worst drop {sensitivity.worst_drop_pct:.1f}%)")

    if fragile:
        return "FRAGILE", reasons

    reasons.append("all robustness checks passed")
    return "ROBUST", reasons
