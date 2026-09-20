# -*- coding: utf-8 -*-
"""Performance Intelligence Engine — PRD_V2 §42.

Turns trade history into statistical insight across many *dimensions* so the
research loop can see where edge actually lives. This module is deliberately
**advisory only** — it never overrides a strategy, gate, or the risk stack.

Dimensions (PRD §42)::

    hour, weekday, session, symbol, timeframe, strategy, setup, regime,
    volatility, spread_bucket, rr_bucket, agent_consensus, model, direction,
    holding_time

Minimum-sample rule (PRD §42): a bucket with ``count < min_sample`` is returned
with ``reliable=False`` and ``status="INSUFFICIENT_SAMPLE"`` — never presented
as a trustworthy insight.

Every record carries ``advisory=True`` so no caller can mistake these results
for authority to change live behaviour automatically.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Optional

__all__ = [
    "TradeRow",
    "BucketInsight",
    "PerformanceIntelligence",
    "DIMENSIONS",
]

# The 15 dimensions the engine can group by (PRD §42).
DIMENSIONS: tuple[str, ...] = (
    "hour",
    "weekday",
    "session",
    "symbol",
    "timeframe",
    "strategy",
    "setup",
    "regime",
    "volatility",
    "spread_bucket",
    "rr_bucket",
    "agent_consensus",
    "model",
    "direction",
    "holding_time",
)


@dataclass
class TradeRow:
    """A single closed trade with the attributes used for analysis.

    All dimension attributes are optional; a missing attribute simply drops the
    trade from that dimension's grouping.
    """

    pnl: float
    r_multiple: float = 0.0
    timestamp: Optional[datetime] = None
    weekday: Optional[str] = None
    session: Optional[str] = None
    symbol: Optional[str] = None
    timeframe: Optional[str] = None
    strategy: Optional[str] = None
    setup: Optional[str] = None
    regime: Optional[str] = None
    volatility: Optional[str] = None
    spread_bucket: Optional[str] = None
    rr_bucket: Optional[str] = None
    agent_consensus: Optional[str] = None
    model: Optional[str] = None
    direction: Optional[str] = None
    holding_time: Optional[str] = None

    def value_for(self, dimension: str) -> Optional[str]:
        """Return the bucket key for *dimension* (None when unavailable)."""
        if dimension == "hour":
            return str(self.timestamp.hour) if self.timestamp else None
        if dimension == "weekday":
            if self.weekday:
                return self.weekday
            return self.timestamp.strftime("%A") if self.timestamp else None
        return getattr(self, dimension, None)


@dataclass
class BucketInsight:
    """Statistics for a single bucket of a single dimension."""

    dimension: str
    key: str
    count: int = 0
    wins: int = 0
    losses: int = 0
    total_pnl: float = 0.0
    total_r: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    reliable: bool = False
    status: str = "INSUFFICIENT_SAMPLE"
    advisory: bool = True

    @property
    def win_rate(self) -> float:
        return (self.wins / self.count * 100.0) if self.count else 0.0

    @property
    def expectancy(self) -> float:
        return self.total_pnl / self.count if self.count else 0.0

    @property
    def avg_r(self) -> float:
        return self.total_r / self.count if self.count else 0.0

    @property
    def profit_factor(self) -> float:
        if self.gross_loss > 0:
            return self.gross_profit / self.gross_loss
        return float("inf") if self.gross_profit > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "key": self.key,
            "count": self.count,
            "win_rate": round(self.win_rate, 2),
            "expectancy": round(self.expectancy, 4),
            "avg_r": round(self.avg_r, 4),
            "profit_factor": (
                round(self.profit_factor, 4) if self.profit_factor != float("inf") else float("inf")
            ),
            "total_pnl": round(self.total_pnl, 4),
            "reliable": self.reliable,
            "status": self.status,
            "advisory": self.advisory,
        }


@dataclass
class PerformanceIntelligence:
    """Group trades by dimension and compute per-bucket insights (PRD §42).

    Args:
        min_sample: Minimum trades for a bucket to be considered reliable.
    """

    min_sample: int = 30
    _buckets: dict[str, dict[str, BucketInsight]] = field(default_factory=dict, repr=False)

    # ------------------------------------------------------------------
    def analyze(
        self,
        trades: Iterable[TradeRow],
        dimensions: Optional[Iterable[str]] = None,
    ) -> dict[str, list[BucketInsight]]:
        """Group *trades* by each dimension and return insights per dimension."""
        dims = list(dimensions) if dimensions is not None else list(DIMENSIONS)
        out: dict[str, list[BucketInsight]] = {}
        for dim in dims:
            if dim not in DIMENSIONS:
                continue
            out[dim] = self._analyze_dimension(dim, trades)
        return out

    def _analyze_dimension(self, dim: str, trades: Iterable[TradeRow]) -> list[BucketInsight]:
        buckets: dict[str, BucketInsight] = {}
        for trade in trades:
            key = trade.value_for(dim)
            if key is None:
                continue
            bucket = buckets.get(key)
            if bucket is None:
                bucket = BucketInsight(dimension=dim, key=key)
                buckets[key] = bucket
            bucket.count += 1
            bucket.total_pnl += trade.pnl
            bucket.total_r += trade.r_multiple
            if trade.pnl > 0:
                bucket.wins += 1
                bucket.gross_profit += trade.pnl
            elif trade.pnl < 0:
                bucket.losses += 1
                bucket.gross_loss += abs(trade.pnl)

        insights: list[BucketInsight] = []
        for bucket in buckets.values():
            bucket.reliable = bucket.count >= self.min_sample
            bucket.status = "RELIABLE" if bucket.reliable else "INSUFFICIENT_SAMPLE"
            insights.append(bucket)
        # Deterministic ordering: highest count first, then key.
        insights.sort(key=lambda b: (-b.count, b.key))
        return insights

    def top_buckets(
        self,
        trades: Iterable[TradeRow],
        dimension: str,
        limit: int = 5,
    ) -> list[BucketInsight]:
        """Return the top reliable buckets by expectancy for *dimension*."""
        insights = [b for b in self._analyze_dimension(dimension, trades) if b.reliable]
        insights.sort(key=lambda b: (-b.expectancy, b.key))
        return insights[:limit]

    def unreliable_buckets(
        self,
        trades: Iterable[TradeRow],
        dimension: str,
    ) -> list[BucketInsight]:
        """Return buckets that are below the minimum-sample threshold."""
        return [b for b in self._analyze_dimension(dimension, trades) if not b.reliable]
