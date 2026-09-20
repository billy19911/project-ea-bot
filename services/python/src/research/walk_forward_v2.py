# -*- coding: utf-8 -*-
"""Walk-Forward Validation — PRD_V2 §40.

Tests a strategy on **out-of-sample** (OOS) windows using a rolling
train → test split, so robustness is judged per OOS period rather than on a
single aggregate number.

Model::

    Window 1: TRAIN[t0..t1)  TEST[t1..t2)
    Window 2: TRAIN[t1..t2)  TEST[t2..t3)
    Window 3: TRAIN[t2..t3)  TEST[t3..t4)

Each OOS window produces the required output record::

    {
      "period": "2024-Q2",
      "trades": 143,
      "expectancy_r": 0.19,
      "max_dd_pct": 7.2,
      "profit_factor": 1.31,
      "status": "PASS"
    }

Governance (PRD §40): aggregated results alone are not sufficient — *every*
OOS period is stored and returned.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional

from .backtest_v2 import Bar, RealisticBacktester

__all__ = [
    "WindowResult",
    "WalkForwardReport",
    "WalkForwardValidator",
]

SignalFn = Callable[[list[Bar], int], int]
ParamSearchFn = Callable[[list[Bar]], dict[str, Any]]


def _quarter_label(dt: datetime) -> str:
    """Return a ``YYYY-Qn`` label for *dt*."""
    quarter = (dt.month - 1) // 3 + 1
    return f"{dt.year}-Q{quarter}"


@dataclass
class WindowResult:
    """A single out-of-sample window result (PRD §40 output schema)."""

    period: str
    trades: int
    expectancy_r: float
    max_dd_pct: float
    profit_factor: float
    status: str
    train_start: Optional[datetime] = None
    train_end: Optional[datetime] = None
    test_start: Optional[datetime] = None
    test_end: Optional[datetime] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "period": self.period,
            "trades": self.trades,
            "expectancy_r": self.expectancy_r,
            "max_dd_pct": self.max_dd_pct,
            "profit_factor": self.profit_factor,
            "status": self.status,
        }


@dataclass
class WalkForwardReport:
    """Aggregate walk-forward report plus every stored OOS window."""

    windows: list[WindowResult] = field(default_factory=list)
    pass_count: int = 0
    fail_count: int = 0
    robust: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "windows": [w.to_dict() for w in self.windows],
            "pass_count": self.pass_count,
            "fail_count": self.fail_count,
            "robust": self.robust,
        }


class WalkForwardValidator:
    """Rolling train → test walk-forward validator.

    Args:
        backtester: The realistic backtester used for each window.
        n_windows: Number of rolling OOS windows.
        train_ratio: Fraction of each window used for training. The remaining
            fraction is the OOS test segment.
        min_trades: A window with fewer trades is marked ``INSUFFICIENT``.
        min_profit_factor: Minimum PF to PASS a window.
        min_expectancy_r: Minimum expectancy (R) to PASS a window.
        max_dd_pct: Maximum drawdown (%) allowed to PASS a window.
    """

    def __init__(
        self,
        backtester: Optional[RealisticBacktester] = None,
        n_windows: int = 3,
        train_ratio: float = 0.75,
        min_trades: int = 1,
        min_profit_factor: float = 1.0,
        min_expectancy_r: float = 0.0,
        max_dd_pct: float = 50.0,
    ) -> None:
        self.backtester = backtester or RealisticBacktester()
        self.n_windows = max(1, n_windows)
        self.train_ratio = min(max(train_ratio, 0.1), 0.9)
        self.min_trades = min_trades
        self.min_profit_factor = min_profit_factor
        self.min_expectancy_r = min_expectancy_r
        self.max_dd_pct = max_dd_pct

    def _split_bounds(self, n_bars: int) -> list[tuple[int, int, int]]:
        """Return ``[(train_start, train_end, test_end), ...]`` bar indices.

        The series is divided into ``n_windows`` overlapping windows. Each
        window is ``window_size`` bars; the first ``train_ratio`` portion is
        the train segment and the rest is the OOS test segment.
        """
        if n_bars < self.n_windows + 2:
            return []
        window_size = max(2, n_bars // self.n_windows)
        train_len = max(1, int(window_size * self.train_ratio))
        bounds: list[tuple[int, int, int]] = []
        for w in range(self.n_windows):
            start = (
                w * (n_bars - window_size) // max(1, self.n_windows - 1)
                if self.n_windows > 1
                else 0
            )
            train_start = start
            train_end = min(start + train_len, n_bars - 1)
            test_end = min(train_end + (window_size - train_len), n_bars)
            if train_end >= n_bars or test_end <= train_end:
                continue
            bounds.append((train_start, train_end, test_end))
        return bounds

    def validate(
        self,
        bars: list[Bar],
        signal_fn: SignalFn,
        param_search: Optional[ParamSearchFn] = None,
    ) -> WalkForwardReport:
        """Run walk-forward validation and return the full report.

        Args:
            bars: Chronological bars.
            signal_fn: Strategy signal function ``(bars, idx) -> -1|0|1``.
            param_search: Optional callable that, given a train segment,
                returns tuned parameters. Currently accepted for API
                compatibility; the injected ``signal_fn`` is used for both
                segments (the harness is strategy-agnostic).
        """
        report = WalkForwardReport()
        n = len(bars)
        bounds = self._split_bounds(n)

        for train_start, train_end, test_end in bounds:
            test_bars = bars[train_end:test_end]
            if len(test_bars) < 2:
                continue
            result = self.backtester.run(test_bars, signal_fn)
            metrics = result.metrics
            trades = int(metrics.get("total_trades", len(result.trades)))
            expectancy_r = float(metrics.get("average_r", 0.0))
            max_dd = float(metrics.get("max_drawdown", 0.0))
            pf = float(metrics.get("profit_factor", 0.0))

            if trades < self.min_trades:
                status = "INSUFFICIENT"
            elif (
                pf >= self.min_profit_factor
                and expectancy_r >= self.min_expectancy_r
                and max_dd <= self.max_dd_pct
            ):
                status = "PASS"
            else:
                status = "FAIL"

            period = (
                _quarter_label(test_bars[0].time) if test_bars else _quarter_label(bars[0].time)
            )
            report.windows.append(
                WindowResult(
                    period=period,
                    trades=trades,
                    expectancy_r=round(expectancy_r, 4),
                    max_dd_pct=round(max_dd, 4),
                    profit_factor=round(pf, 4) if pf != float("inf") else float("inf"),
                    status=status,
                    train_start=bars[train_start].time,
                    train_end=bars[train_end].time,
                    test_start=test_bars[0].time,
                    test_end=test_bars[-1].time,
                )
            )

        report.pass_count = sum(1 for w in report.windows if w.status == "PASS")
        report.fail_count = sum(1 for w in report.windows if w.status == "FAIL")
        report.robust = (
            report.pass_count > 0
            and report.fail_count == 0
            and len(report.windows) == self.n_windows
        )
        return report
