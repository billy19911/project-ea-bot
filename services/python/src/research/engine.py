# -*- coding: utf-8 -*-
"""Research engine for hypothesis testing, experiments, backtesting, and comparison.

Provides structured workflow for strategy hypothesis creation, parameter
experimentation, historical backtesting, and comparative analysis.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Hypothesis:
    """Structured trading hypothesis with entry/exit rules and parameters."""

    id: str
    name: str
    description: str
    entry_rules: list[str]
    exit_rules: list[str]
    parameters: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True)
class StrategyVersion:
    """Strategy parameter set with versioning and description."""

    version: str
    parameters: dict[str, Any]
    created_at: datetime
    description: str = ""


@dataclass
class Experiment:
    """Backtest experiment linking hypothesis, strategy version, and params.

    Attributes:
        id: Unique experiment identifier.
        name: Human-readable name.
        strategy_version: Strategy version key (e.g. "v1").
        parameters: Parameter overrides merged with strategy version params.
        hypothesis_id: Hypothesis ID this experiment tests.
        status: One of "pending", "running", "completed", "failed".
    """

    id: str
    name: str
    strategy_version: str
    parameters: dict[str, Any]
    hypothesis_id: str
    status: str


@dataclass
class BacktestResult:
    """Aggregated backtest metrics and trade history."""

    total_trades: int
    win_rate: float
    profit_factor: float
    sharpe_ratio: float
    max_drawdown: float
    expectation: float
    net_pnl: float
    trades: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Research Engine
# ---------------------------------------------------------------------------


class ResearchEngine:
    """Engine for hypothesis creation, experimentation, backtesting, comparison."""

    def __init__(self) -> None:
        """Initialise the research engine."""
        self._hypotheses: dict[str, Hypothesis] = {}
        self._strategy_versions: dict[str, StrategyVersion] = {}
        self._experiments: dict[str, Experiment] = {}
        self._backtest_results: dict[str, BacktestResult] = {}

    # -- Hypothesis management ------------------------------------------------

    def create_hypothesis(
        self,
        name: str,
        description: str,
        entry_rules: list[str] | None = None,
        exit_rules: list[str] | None = None,
        parameters: dict[str, Any] | None = None,
    ) -> Hypothesis:
        """Create and register a new trading hypothesis.

        Args:
            name: Human-readable hypothesis name.
            description: Description of the hypothesis logic.
            entry_rules: List of entry rule descriptions.
            exit_rules: List of exit rule descriptions.
            parameters: Dict of parameter names and allowed values.

        Returns:
            Created Hypothesis instance.
        """
        hypothesis_id = str(uuid.uuid4())
        hypothesis = Hypothesis(
            id=hypothesis_id,
            name=name,
            description=description,
            entry_rules=entry_rules or [],
            exit_rules=exit_rules or [],
            parameters=parameters or {},
            created_at=datetime.now(timezone.utc),
        )
        self._hypotheses[hypothesis_id] = hypothesis
        logger.info(f"Created hypothesis '{name}' ({hypothesis_id})")
        return hypothesis

    # -- Strategy version management ------------------------------------------

    def create_strategy_version(
        self,
        version: str,
        parameters: dict[str, Any] | None = None,
        description: str = "",
    ) -> StrategyVersion:
        """Create and register a strategy parameter set.

        Args:
            version: Version key (e.g. "v1", "v1.1", "baseline").
            parameters: Parameter dict (e.g. {"fast_ema_period": 9}).
            description: Optional description of the version.

        Returns:
            Created StrategyVersion instance.

        Raises:
            ValueError: If version already exists.
        """
        if version in self._strategy_versions:
            raise ValueError(f"Strategy version '{version}' already exists")

        strategy = StrategyVersion(
            version=version,
            parameters=parameters or {},
            created_at=datetime.now(timezone.utc),
            description=description,
        )
        self._strategy_versions[version] = strategy
        logger.info(f"Created strategy version '{version}'")
        return strategy

    def get_strategy_version(self, version: str) -> StrategyVersion | None:
        """Retrieve a strategy version by key.

        Args:
            version: Version key to look up.

        Returns:
            StrategyVersion or None if not found.
        """
        return self._strategy_versions.get(version)

    # -- Experiment management ------------------------------------------------

    def create_experiment(
        self,
        hypothesis_id: str,
        strategy_version: str,
        parameters: dict[str, Any] | None = None,
    ) -> Experiment:
        """Create and register an experiment.

        Experiment merges strategy version parameters with experiment-specific
        overrides.

        Args:
            hypothesis_id: ID of hypothesis being tested.
            strategy_version: Strategy version key.
            parameters: Optional parameter overrides.

        Returns:
            Created Experiment instance.

        Raises:
            ValueError: If hypothesis or strategy version not found.
        """
        if hypothesis_id not in self._hypotheses:
            raise ValueError(f"Unknown hypothesis '{hypothesis_id}'")
        if strategy_version not in self._strategy_versions:
            raise ValueError(f"Unknown strategy version '{strategy_version}'")

        experiment_id = str(uuid.uuid4())
        experiment = Experiment(
            id=experiment_id,
            name=f"{self._hypotheses[hypothesis_id].name}-{strategy_version}",
            strategy_version=strategy_version,
            parameters=parameters or {},
            hypothesis_id=hypothesis_id,
            status="pending",
        )
        self._experiments[experiment_id] = experiment
        logger.info(f"Created experiment '{experiment.name}' ({experiment_id})")
        return experiment

    # -- Metrics computation --------------------------------------------------

    def compute_metrics(self, trades: list[dict[str, Any]]) -> dict[str, float]:
        """Compute aggregate metrics from a trade list.

        Trades are dicts with at minimum {"pnl": float}.

        Args:
            trades: List of trade dicts with "pnl" key.

        Returns:
            Dict with keys: total_trades, win_rate, profit_factor,
            sharpe_ratio, max_drawdown, expectation, net_pnl.
        """
        if not trades:
            return {
                "total_trades": 0,
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "sharpe_ratio": 0.0,
                "max_drawdown": 0.0,
                "expectation": 0.0,
                "net_pnl": 0.0,
            }

        pnls = [t["pnl"] for t in trades if "pnl" in t]
        net_pnl = sum(pnls)
        total_trades = len(pnls)

        # Win rate
        wins = sum(1 for p in pnls if p > 0)
        win_rate = (wins / total_trades * 100.0) if total_trades > 0 else 0.0

        # Profit factor
        gross_profit = sum(p for p in pnls if p > 0)
        gross_loss = abs(sum(p for p in pnls if p < 0))
        if gross_loss > 0:
            profit_factor = gross_profit / gross_loss
        elif gross_profit > 0:
            profit_factor = float("inf")
        else:
            profit_factor = 0.0

        # Expectation
        expectation = (net_pnl / total_trades) if total_trades > 0 else 0.0

        # Sharpe ratio (simplified, no annualization)
        if len(pnls) > 1:
            mean_pnl = sum(pnls) / len(pnls)
            variance = sum((p - mean_pnl) ** 2 for p in pnls) / (len(pnls) - 1)
            std = variance**0.5
            sharpe_ratio = (mean_pnl / std) if std > 0 else 0.0
        else:
            sharpe_ratio = 0.0

        # Max drawdown from equity curve
        equity_curve = [0.0]
        for pnl in pnls:
            equity_curve.append(equity_curve[-1] + pnl)
        max_dd = 0.0
        peak = equity_curve[0]
        for equity in equity_curve:
            peak = max(peak, equity)
            if peak != 0:
                dd = abs(peak - equity) / abs(peak) * 100.0
                max_dd = max(max_dd, dd)

        return {
            "total_trades": total_trades,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "sharpe_ratio": sharpe_ratio,
            "max_drawdown": max_dd,
            "expectation": expectation,
            "net_pnl": net_pnl,
        }

    # -- Backtesting ----------------------------------------------------------

    def run_backtest(
        self,
        experiment: Experiment,
        historical_data: list[float],
    ) -> BacktestResult:
        """Run backtest on historical close prices.

        Replays bars, simulates trades based on merged parameters, and
        closes final position at end of data.

        Args:
            experiment: Experiment to backtest.
            historical_data: Close prices (oldest → newest).

        Returns:
            BacktestResult with metrics and trade list.

        Raises:
            ValueError: If experiment not registered.
        """
        if experiment.id not in self._experiments:
            raise ValueError(f"Experiment {experiment.id} not registered")

        if len(historical_data) < 5:
            result = BacktestResult(
                total_trades=0,
                win_rate=0.0,
                profit_factor=0.0,
                sharpe_ratio=0.0,
                max_drawdown=0.0,
                expectation=0.0,
                net_pnl=0.0,
                trades=[],
            )
            self._backtest_results[experiment.id] = result
            experiment.status = "completed"
            return result

        # Merge parameters: strategy version + experiment overrides
        params = dict(self._strategy_versions[experiment.strategy_version].parameters)
        params.update(experiment.parameters)

        # Minimal mock backtest: simulate EMA-based trend trades
        trades: list[dict[str, Any]] = []
        in_trade = False
        entry_price = 0.0
        direction = 0

        # Extract EMA periods with fallback
        fast_period = int(params.get("fast_ema_period", 2))
        slow_period = int(params.get("slow_ema_period", 3))

        for bar_idx, close in enumerate(historical_data):
            if bar_idx < slow_period:
                continue

            # Compute simple EMAs
            fast_ema = self._simple_ema(
                historical_data[max(0, bar_idx - fast_period + 1) : bar_idx + 1],
                fast_period,
            )
            slow_ema = self._simple_ema(
                historical_data[max(0, bar_idx - slow_period + 1) : bar_idx + 1],
                slow_period,
            )

            # Signal: buy if fast > slow, sell if fast < slow
            if not in_trade:
                if fast_ema > slow_ema:
                    entry_price = close
                    direction = 1
                    in_trade = True
                elif fast_ema < slow_ema:
                    entry_price = close
                    direction = -1
                    in_trade = True

            elif in_trade:
                # Exit on crossover reversal
                if direction == 1 and fast_ema < slow_ema:
                    pnl = (close - entry_price) * direction
                    trades.append(
                        {
                            "entry": entry_price,
                            "exit": close,
                            "direction": direction,
                            "pnl": pnl,
                            "exit_reason": "signal_reversal",
                        }
                    )
                    in_trade = False
                elif direction == -1 and fast_ema > slow_ema:
                    pnl = (entry_price - close) * abs(direction)
                    trades.append(
                        {
                            "entry": entry_price,
                            "exit": close,
                            "direction": direction,
                            "pnl": pnl,
                            "exit_reason": "signal_reversal",
                        }
                    )
                    in_trade = False

        # Close final position at last price
        if in_trade:
            close = historical_data[-1]
            pnl = (close - entry_price) if direction == 1 else (entry_price - close)
            trades.append(
                {
                    "entry": entry_price,
                    "exit": close,
                    "direction": direction,
                    "pnl": pnl,
                    "exit_reason": "end_of_data",
                }
            )

        # Compute metrics
        metrics = self.compute_metrics(trades)
        result = BacktestResult(
            total_trades=metrics["total_trades"],
            win_rate=metrics["win_rate"],
            profit_factor=metrics["profit_factor"],
            sharpe_ratio=metrics["sharpe_ratio"],
            max_drawdown=metrics["max_drawdown"],
            expectation=metrics["expectation"],
            net_pnl=metrics["net_pnl"],
            trades=trades,
        )
        self._backtest_results[experiment.id] = result
        experiment.status = "completed"
        logger.info(
            f"Backtest completed: {result.total_trades} trades, " f"PnL={result.net_pnl:.2f}"
        )
        return result

    def _simple_ema(self, data: list[float], period: int) -> float:
        """Compute simple EMA (uses SMA for first value).

        Args:
            data: Price series (oldest → newest).
            period: EMA period.

        Returns:
            Latest EMA value.
        """
        if len(data) < period:
            return sum(data) / len(data) if data else 0.0
        alpha = 2.0 / (period + 1)
        ema = sum(data[:period]) / period
        for price in data[period:]:
            ema = price * alpha + ema * (1 - alpha)
        return ema

    # -- Comparison -----------------------------------------------------------

    def compare_experiments(self, exp1: Experiment, exp2: Experiment) -> dict[str, Any]:
        """Compare results of two completed experiments side-by-side.

        Args:
            exp1: First experiment.
            exp2: Second experiment.

        Returns:
            Dict with keys: experiment_1, experiment_2, difference.
                Difference shows delta in all metrics.

        Raises:
            ValueError: If either experiment has no backtest result.
        """
        if exp1.id not in self._backtest_results or exp2.id not in self._backtest_results:
            raise ValueError("Cannot compare: requires completed backtests for both experiments")

        result1 = self._backtest_results[exp1.id]
        result2 = self._backtest_results[exp2.id]

        diff = {
            "total_trades": result2.total_trades - result1.total_trades,
            "win_rate": result2.win_rate - result1.win_rate,
            "profit_factor": result2.profit_factor - result1.profit_factor,
            "sharpe_ratio": result2.sharpe_ratio - result1.sharpe_ratio,
            "max_drawdown": result2.max_drawdown - result1.max_drawdown,
            "expectation": result2.expectation - result1.expectation,
            "net_pnl": result2.net_pnl - result1.net_pnl,
        }

        return {
            "experiment_1": {
                "id": exp1.id,
                "name": exp1.name,
                "total_trades": result1.total_trades,
                "win_rate": result1.win_rate,
                "profit_factor": result1.profit_factor,
                "sharpe_ratio": result1.sharpe_ratio,
                "max_drawdown": result1.max_drawdown,
                "expectation": result1.expectation,
                "net_pnl": result1.net_pnl,
            },
            "experiment_2": {
                "id": exp2.id,
                "name": exp2.name,
                "total_trades": result2.total_trades,
                "win_rate": result2.win_rate,
                "profit_factor": result2.profit_factor,
                "sharpe_ratio": result2.sharpe_ratio,
                "max_drawdown": result2.max_drawdown,
                "expectation": result2.expectation,
                "net_pnl": result2.net_pnl,
            },
            "difference": diff,
        }
