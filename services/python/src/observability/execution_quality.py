# -*- coding: utf-8 -*-
"""Execution Quality Analytics — PRD_V2 §47.

Tracks the quality of order execution (requested entry vs. actual fill,
slippage, spread, latency, rejections, partial fills, and the market state at
fill time) and produces the metrics the execution policy consumes.

Important (PRD §47): these insights feed the **execution policy**, not the
strategy signal. Nothing here changes a signal without separate validation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

__all__ = [
    "ExecutionRecord",
    "ExecutionQualityAnalytics",
]


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (pct / 100.0) * (len(sorted_values) - 1)
    low = int(rank)
    high = min(low + 1, len(sorted_values) - 1)
    frac = rank - low
    return sorted_values[low] * (1 - frac) + sorted_values[high] * frac


@dataclass
class ExecutionRecord:
    """A single execution observation (PRD §47 Track)."""

    requested_entry: float
    actual_fill: float
    direction: int = 1  # +1 buy, -1 sell
    spread: float = 0.0
    latency_ms: float = 0.0
    rejected: bool = False
    partial: bool = False
    filled_ratio: float = 1.0
    session: Optional[str] = None
    volatility: Optional[str] = None
    timestamp: Optional[datetime] = None

    @property
    def slippage(self) -> float:
        """Adverse slippage in price units (positive = worse than requested)."""
        if self.rejected:
            return 0.0
        # For a buy, a fill above the request is adverse; for a sell, below.
        return (self.actual_fill - self.requested_entry) * self.direction


@dataclass
class ExecutionQualityAnalytics:
    """Aggregate execution-quality metrics (PRD §47 Metrics).

    Args:
        high_slippage_threshold: Slippage value above which an alert fires.
        high_rejection_rate: Rejection-rate fraction above which an alert fires.
    """

    high_slippage_threshold: float = 0.0005
    high_rejection_rate: float = 0.10
    _records: list[ExecutionRecord] = field(default_factory=list, repr=False)

    def record(self, rec: ExecutionRecord) -> ExecutionRecord:
        self._records.append(rec)
        return rec

    def records(self) -> list[ExecutionRecord]:
        return list(self._records)

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------
    def _fills(self) -> list[ExecutionRecord]:
        return [r for r in self._records if not r.rejected]

    def average_slippage(self) -> float:
        fills = self._fills()
        if not fills:
            return 0.0
        return sum(r.slippage for r in fills) / len(fills)

    def p95_slippage(self) -> float:
        slips = sorted(r.slippage for r in self._fills())
        return _percentile(slips, 95.0)

    def fill_delay(self) -> float:
        fills = self._fills()
        if not fills:
            return 0.0
        return sum(r.latency_ms for r in fills) / len(fills)

    def rejection_rate(self) -> float:
        if not self._records:
            return 0.0
        return sum(1 for r in self._records if r.rejected) / len(self._records)

    def partial_fill_rate(self) -> float:
        if not self._records:
            return 0.0
        return sum(1 for r in self._records if r.partial) / len(self._records)

    def by_session(self) -> dict[str, dict[str, float]]:
        buckets: dict[str, list[ExecutionRecord]] = {}
        for rec in self._records:
            if rec.session:
                buckets.setdefault(rec.session, []).append(rec)
        return {s: self._summarize(recs) for s, recs in buckets.items()}

    def by_volatility(self) -> dict[str, dict[str, float]]:
        buckets: dict[str, list[ExecutionRecord]] = {}
        for rec in self._records:
            if rec.volatility:
                buckets.setdefault(rec.volatility, []).append(rec)
        return {v: self._summarize(recs) for v, recs in buckets.items()}

    @staticmethod
    def _summarize(records: list[ExecutionRecord]) -> dict[str, float]:
        fills = [r for r in records if not r.rejected]
        avg_slip = (sum(r.slippage for r in fills) / len(fills)) if fills else 0.0
        avg_lat = (sum(r.latency_ms for r in fills) / len(fills)) if fills else 0.0
        reject = (sum(1 for r in records if r.rejected) / len(records)) if records else 0.0
        partial = (sum(1 for r in records if r.partial) / len(records)) if records else 0.0
        return {
            "count": float(len(records)),
            "avg_slippage": avg_slip,
            "avg_latency_ms": avg_lat,
            "rejection_rate": reject,
            "partial_fill_rate": partial,
        }

    def summary(self) -> dict[str, Any]:
        """Return the full metric set (PRD §47 Metrics)."""
        return {
            "average_slippage": self.average_slippage(),
            "p95_slippage": self.p95_slippage(),
            "fill_delay": self.fill_delay(),
            "rejection_rate": self.rejection_rate(),
            "partial_fill_rate": self.partial_fill_rate(),
            "execution_by_session": self.by_session(),
            "execution_by_volatility": self.by_volatility(),
        }

    # ------------------------------------------------------------------
    # Alerting
    # ------------------------------------------------------------------
    def alerts(self) -> list[str]:
        """Return alert messages for degraded execution quality."""
        alerts: list[str] = []
        if self.average_slippage() > self.high_slippage_threshold:
            alerts.append(
                f"average slippage {self.average_slippage():.6f} exceeds "
                f"threshold {self.high_slippage_threshold:.6f}"
            )
        if self.rejection_rate() > self.high_rejection_rate:
            alerts.append(
                f"rejection rate {self.rejection_rate():.2%} exceeds "
                f"threshold {self.high_rejection_rate:.2%}"
            )
        return alerts
