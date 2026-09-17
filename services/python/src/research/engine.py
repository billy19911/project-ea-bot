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

from trading.indicators import atr_series, ema

logger = logging.getLogger(__name__)

# Default train/test split ratio for walk-forward validation (§18 / P2-24).
DEFAULT_TRAIN_RATIO = 0.7
# Minimum bars required to attempt a backtest at all.
_MIN_BARS = 5


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
    """Aggregated backtest metrics and trade history.

    Attributes:
        walk_forward: Walk-forward validation metadata (windows, per-window
            metrics, aggregate) — empty dict when walk-forward is disabled.
    """

    total_trades: int
    win_rate: float
    profit_factor: float
    sharpe_ratio: float
    max_drawdown: float
    expectation: float
    net_pnl: float
    trades: list[dict[str, Any]] = field(default_factory=list)
    walk_forward: dict[str, Any] = field(default_factory=dict)


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
        train_ratio: float = DEFAULT_TRAIN_RATIO,
        walk_forward: bool = True,
        highs: list[float] | None = None,
        lows: list[float] | None = None,
    ) -> BacktestResult:
        """Run a realistic, indicator-based backtest over historical closes.

        The simulation reuses the project's real EMA implementation
        (:func:`trading.indicators.ema`) — there is no hand-rolled indicator maths
        here — and is fully deterministic (no randomness, no new deps).

        When ``walk_forward`` is enabled (default), the data is split into a
        train window and a test window (``train_ratio``, default 70/30). A
        backtest is run on each window and the results are aggregated into a
        ``walk_forward`` metadata dict (windows, per-window metrics, aggregate).

        Args:
            experiment: Experiment to backtest (must be registered).
            historical_data: Close prices (oldest → newest).
            train_ratio: Fraction of bars used for the train window (0<r<1).
            walk_forward: Whether to compute walk-forward metadata.
            highs: Optional real high prices (same length) — enables ATR-based
                stop-loss / take-profit exits on each simulated trade.
            lows: Optional real low prices (same length) — enables ATR-based
                stop-loss / take-profit exits on each simulated trade.

        Returns:
            BacktestResult with metrics, trade list, and walk-forward metadata.

        Raises:
            ValueError: If experiment not registered.
        """
        if experiment.id not in self._experiments:
            raise ValueError(f"Experiment {experiment.id} not registered")

        if len(historical_data) < _MIN_BARS:
            result = BacktestResult(
                total_trades=0,
                win_rate=0.0,
                profit_factor=0.0,
                sharpe_ratio=0.0,
                max_drawdown=0.0,
                expectation=0.0,
                net_pnl=0.0,
                trades=[],
                walk_forward={"enabled": bool(walk_forward), "windows": [], "aggregate": {}},
            )
            self._backtest_results[experiment.id] = result
            experiment.status = "completed"
            return result

        # Merge parameters: strategy version + experiment overrides
        params = dict(self._strategy_versions[experiment.strategy_version].parameters)
        params.update(experiment.parameters)

        # Full-series simulation drives the headline metrics/trades.
        trades = self._simulate(historical_data, params, highs=highs, lows=lows)
        metrics = self.compute_metrics(trades)

        walk_forward_meta: dict[str, Any] = {"enabled": bool(walk_forward)}
        if walk_forward:
            walk_forward_meta = self._walk_forward(
                historical_data, params, train_ratio, highs=highs, lows=lows
            )

        result = BacktestResult(
            total_trades=metrics["total_trades"],
            win_rate=metrics["win_rate"],
            profit_factor=metrics["profit_factor"],
            sharpe_ratio=metrics["sharpe_ratio"],
            max_drawdown=metrics["max_drawdown"],
            expectation=metrics["expectation"],
            net_pnl=metrics["net_pnl"],
            trades=trades,
            walk_forward=walk_forward_meta,
        )
        self._backtest_results[experiment.id] = result
        experiment.status = "completed"
        logger.info(
            f"Backtest completed: {result.total_trades} trades, " f"PnL={result.net_pnl:.2f}"
        )
        return result

    # -- Simulation internals -------------------------------------------------

    def _simulate(
        self,
        prices: list[float],
        params: dict[str, Any],
        highs: list[float] | None = None,
        lows: list[float] | None = None,
    ) -> list[dict[str, Any]]:
        """Simulate EMA-crossover trades over a price series (deterministic).

        Uses the project's real :func:`trading.indicators.ema` for both the fast
        and slow lines, enters on a crossover and exits on the opposite
        crossover (or at end of data). The final open position is always closed
        so realised PnL reflects the whole series.

        When *highs* and *lows* are supplied (real bars), each trade also gets
        ATR-based stop-loss / take-profit levels — the same 2×ATR stop and
        R:R 2:1 target the trading engine proposes. Intrabar the stop is checked
        before the target (worst-case convention), and the exit is labelled with
        ``exit_reason``: ``stop_loss`` / ``take_profit`` / ``signal_reversal`` /
        ``end_of_data``. Without real highs/lows no ATR levels are fabricated —
        trades then exit on signal only.
        """
        fast_period = int(params.get("fast_ema_period", 3))
        slow_period = int(params.get("slow_ema_period", 8))
        if fast_period < 1:
            fast_period = 1
        if slow_period <= fast_period:
            slow_period = fast_period + 1

        trades: list[dict[str, Any]] = []
        in_trade = False
        entry_price = 0.0
        direction = 0
        stop_loss: float | None = None
        take_profit: float | None = None
        entry_atr: float | None = None
        entry_bar = 0

        # ATR levels need real highs/lows; without them the trades simply carry
        # no stop/target (no fabricated levels from closes).
        use_atr = (
            highs is not None
            and lows is not None
            and len(highs) == len(prices)
            and len(lows) == len(prices)
        )
        atr_values: list[float | None] = [None] * len(prices)
        if use_atr:
            atr_values = atr_series(
                list(highs),  # type: ignore[arg-type]
                list(lows),  # type: ignore[arg-type]
                list(prices),
                int(params.get("atr_period", 14)),
            )

        stop_multiplier = float(params.get("atr_stop_multiplier", 2.0))
        reward_risk = float(params.get("reward_risk_ratio", 2.0))
        if stop_multiplier <= 0:
            stop_multiplier = 2.0
        if reward_risk <= 0:
            reward_risk = 2.0

        for bar_idx in range(len(prices)):
            window = prices[: bar_idx + 1]
            if len(window) < slow_period:
                continue
            fast_ema = ema(window, fast_period)
            slow_ema = ema(window, slow_period)
            if fast_ema is None or slow_ema is None:
                continue
            close = prices[bar_idx]

            if not in_trade:
                if fast_ema > slow_ema:
                    entry_price, direction, in_trade = close, 1, True
                elif fast_ema < slow_ema:
                    entry_price, direction, in_trade = close, -1, True
                if in_trade:
                    entry_bar = bar_idx
                    entry_atr = atr_values[bar_idx] if use_atr else None
                    if entry_atr is not None and entry_atr > 0:
                        stop_loss = entry_price - direction * stop_multiplier * entry_atr
                        take_profit = (
                            entry_price + direction * stop_multiplier * reward_risk * entry_atr
                        )
                    else:
                        stop_loss = None
                        take_profit = None
            else:
                exit_price: float | None = None
                exit_reason = ""

                # Intrabar stop/target using the real high/low of this bar.
                # Worst-case convention: the stop is assumed hit before the
                # target when a bar covers both — never an optimistic guess.
                if stop_loss is not None and take_profit is not None:
                    bar_high = float(highs[bar_idx]) if use_atr else close
                    bar_low = float(lows[bar_idx]) if use_atr else close
                    if direction == 1:
                        if bar_low <= stop_loss:
                            exit_price, exit_reason = stop_loss, "stop_loss"
                        elif bar_high >= take_profit:
                            exit_price, exit_reason = take_profit, "take_profit"
                    else:
                        if bar_high >= stop_loss:
                            exit_price, exit_reason = stop_loss, "stop_loss"
                        elif bar_low <= take_profit:
                            exit_price, exit_reason = take_profit, "take_profit"

                reversed_trend = (direction == 1 and fast_ema < slow_ema) or (
                    direction == -1 and fast_ema > slow_ema
                )
                if exit_price is None and reversed_trend:
                    exit_price, exit_reason = close, "signal_reversal"

                if exit_price is not None:
                    pnl = (exit_price - entry_price) * direction
                    trades.append(
                        {
                            "entry": entry_price,
                            "exit": exit_price,
                            "direction": direction,
                            "pnl": pnl,
                            "exit_reason": exit_reason,
                            "stop_loss": stop_loss,
                            "take_profit": take_profit,
                            "atr_at_entry": entry_atr,
                            "entry_bar": entry_bar,
                            "exit_bar": bar_idx,
                        }
                    )
                    in_trade = False
                    stop_loss = None
                    take_profit = None
                    entry_atr = None

        # Close final position at last price.
        if in_trade:
            close = prices[-1]
            pnl = (close - entry_price) * direction
            trades.append(
                {
                    "entry": entry_price,
                    "exit": close,
                    "direction": direction,
                    "pnl": pnl,
                    "exit_reason": "end_of_data",
                    "stop_loss": stop_loss,
                    "take_profit": take_profit,
                    "atr_at_entry": entry_atr,
                    "entry_bar": entry_bar,
                    "exit_bar": len(prices) - 1,
                }
            )
        return trades

    def _walk_forward(
        self,
        prices: list[float],
        params: dict[str, Any],
        train_ratio: float,
        highs: list[float] | None = None,
        lows: list[float] | None = None,
    ) -> dict[str, Any]:
        """Split data into train/test windows and aggregate their metrics.

        A single 70/30 split is used by default (``train_ratio``). Each window is
        backtested independently; the result carries the split indices, the
        per-window metrics and an aggregate across all windows.
        """
        ratio = train_ratio if 0.0 < train_ratio < 1.0 else DEFAULT_TRAIN_RATIO
        n = len(prices)
        split_idx = int(n * ratio)
        # Guarantee non-empty, overlapping-safe windows even for tiny inputs.
        split_idx = min(max(split_idx, 1), n - 1)

        windows: list[dict[str, Any]] = []
        splits = {
            "train": (0, split_idx),
            "test": (split_idx, n),
        }
        for name, (start, end) in splits.items():
            window_prices = prices[start:end]
            window_highs = highs[start:end] if highs is not None else None
            window_lows = lows[start:end] if lows is not None else None
            trades = self._simulate(window_prices, params, highs=window_highs, lows=window_lows)
            metrics = self.compute_metrics(trades)
            windows.append(
                {
                    "split": {"train": [0, split_idx], "test": [split_idx, n]},
                    "name": name,
                    "range": [start, end],
                    "metrics": metrics,
                }
            )

        aggregate = self._aggregate_windows(windows)
        return {
            "enabled": True,
            "train_ratio": ratio,
            "windows": windows,
            "aggregate": aggregate,
        }

    @staticmethod
    def _aggregate_windows(windows: list[dict[str, Any]]) -> dict[str, Any]:
        """Aggregate per-window metrics into a single summary."""
        total_trades = sum(w["metrics"]["total_trades"] for w in windows)
        net_pnl = sum(w["metrics"]["net_pnl"] for w in windows)
        # Trade-weighted win rate across windows (0 when no trades).
        weighted_wins = sum(
            w["metrics"]["win_rate"] * w["metrics"]["total_trades"] for w in windows
        )
        win_rate = (weighted_wins / total_trades) if total_trades > 0 else 0.0
        max_drawdown = max((w["metrics"]["max_drawdown"] for w in windows), default=0.0)
        return {
            "windows": len(windows),
            "total_trades": total_trades,
            "net_pnl": net_pnl,
            "win_rate": win_rate,
            "max_drawdown": max_drawdown,
        }

    # -- Read-only accessors (UI/UX ide #6) -----------------------------------

    def list_hypotheses(self) -> list[Hypothesis]:
        """Return all registered hypotheses (insertion order)."""
        return list(self._hypotheses.values())

    def list_experiments(self) -> list[Experiment]:
        """Return all registered experiments (insertion order)."""
        return list(self._experiments.values())

    def get_experiment(self, experiment_id: str) -> Experiment | None:
        """Return an experiment by id, or None when unknown."""
        return self._experiments.get(experiment_id)

    def get_backtest_result(self, experiment_id: str) -> BacktestResult | None:
        """Return the stored backtest result for an experiment, or None."""
        return self._backtest_results.get(experiment_id)

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
