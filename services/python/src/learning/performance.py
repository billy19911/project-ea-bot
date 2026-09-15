# -*- coding: utf-8 -*-
"""Performance tracking for learning loop — EPIC 14.08–14.11.

Tracks performance by hour, session, regime, and setup with
minimum sample-size safeguards, plus supervisor KPI learning.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class TradeRecord:
    """A single recorded trade outcome."""

    pnl: float
    outcome: str = "UNKNOWN"
    hour: Optional[int] = None
    session: Optional[str] = None
    regime: Optional[str] = None
    setup: Optional[str] = None


@dataclass
class BucketStats:
    """Aggregated statistics for a performance bucket."""

    count: int = 0
    wins: int = 0
    losses: int = 0
    total_pnl: float = 0.0

    @property
    def avg_pnl(self) -> float:
        """Average PnL per trade."""
        return self.total_pnl / self.count if self.count else 0.0

    @property
    def win_rate(self) -> float:
        """Win rate percentage."""
        return (self.wins / self.count * 100.0) if self.count else 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize bucket stats."""
        return {
            "count": self.count,
            "wins": self.wins,
            "losses": self.losses,
            "avg_pnl": round(self.avg_pnl, 4),
            "win_rate": round(self.win_rate, 2),
            "total_pnl": round(self.total_pnl, 4),
        }


class PerformanceTracker:
    """Track performance by time, session, regime, and setup (14.08–14.11)."""

    def __init__(self, min_sample_size: int = 5) -> None:
        """Initialize tracker with minimum sample-size safeguard."""
        self.min_sample_size = min_sample_size
        self._trades: list[TradeRecord] = []
        self._hours: dict[int, BucketStats] = {}
        self._sessions: dict[str, BucketStats] = {}
        self._regimes: dict[str, BucketStats] = {}
        self._setups: dict[str, BucketStats] = {}

    def record_trade(
        self,
        pnl: float,
        outcome: str = "UNKNOWN",
        hour: Optional[int] = None,
        session: Optional[str] = None,
        regime: Optional[str] = None,
        setup: Optional[str] = None,
    ) -> None:
        """Record a trade into all applicable buckets."""
        record = TradeRecord(
            pnl=pnl,
            outcome=outcome,
            hour=hour,
            session=session,
            regime=regime,
            setup=setup,
        )
        self._trades.append(record)
        if hour is not None:
            self._update_bucket(self._hours, hour, record)
        if session is not None:
            self._update_bucket(self._sessions, session, record)
        if regime is not None:
            self._update_bucket(self._regimes, regime, record)
        if setup is not None:
            self._update_bucket(self._setups, setup, record)

    @staticmethod
    def _update_bucket(buckets: dict[Any, BucketStats], key: Any, record: TradeRecord) -> None:
        stats = buckets.setdefault(key, BucketStats())
        stats.count += 1
        stats.total_pnl += record.pnl
        if record.pnl > 0 or record.outcome == "WIN":
            stats.wins += 1
        elif record.pnl < 0 or record.outcome == "LOSS":
            stats.losses += 1

    def _get_stats(self, buckets: dict[Any, BucketStats], key: Any) -> Optional[dict[str, Any]]:
        stats = buckets.get(key)
        if stats is None or stats.count < self.min_sample_size:
            return None
        return stats.to_dict()

    def get_hour_stats(self, hour: int) -> Optional[dict[str, Any]]:
        """Hour stats, or None below min sample size (14.08)."""
        return self._get_stats(self._hours, hour)

    def get_session_stats(self, session: str) -> Optional[dict[str, Any]]:
        """Session stats, or None below min sample size (14.08)."""
        return self._get_stats(self._sessions, session)

    def get_regime_stats(self, regime: str) -> Optional[dict[str, Any]]:
        """Regime stats, or None below min sample size (14.09)."""
        return self._get_stats(self._regimes, regime)

    def get_setup_stats(self, setup: str) -> Optional[dict[str, Any]]:
        """Setup stats, or None below min sample size (14.10)."""
        return self._get_stats(self._setups, setup)

    def best_worst_hours(self) -> tuple[Optional[tuple], Optional[tuple]]:
        """Best and worst hours by avg PnL respecting min sample size."""
        eligible = {h: s for h, s in self._hours.items() if s.count >= self.min_sample_size}
        if not eligible:
            return (None, None)
        best = max(eligible.items(), key=lambda kv: kv[1].avg_pnl)
        worst = min(eligible.items(), key=lambda kv: kv[1].avg_pnl)
        return ((best[0], best[1].avg_pnl), (worst[0], worst[1].avg_pnl))

    def supervisor_kpis(self) -> dict[str, Any]:
        """Supervisor KPI learning: win rate, profit factor, expectancy (14.11)."""
        if not self._trades:
            return {
                "total_trades": 0,
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "expectancy": 0.0,
                "max_drawdown": 0.0,
                "false_signals": 0,
                "no_trade_quality": 0.0,
            }
        wins = [t for t in self._trades if t.pnl > 0]
        losses = [t for t in self._trades if t.pnl < 0]
        gross_profit = sum(t.pnl for t in wins)
        gross_loss = abs(sum(t.pnl for t in losses))
        profit_factor = (gross_profit / gross_loss) if gross_loss else float("inf")
        total = len(self._trades)
        expectancy = sum(t.pnl for t in self._trades) / total
        # Equity-curve drawdown
        equity = 0.0
        peak = 0.0
        max_dd = 0.0
        for t in self._trades:
            equity += t.pnl
            peak = max(peak, equity)
            max_dd = max(max_dd, peak - equity)
        false_signals = len([t for t in self._trades if t.outcome == "FALSE_SIGNAL"])
        return {
            "total_trades": total,
            "win_rate": round(len(wins) / total * 100.0, 2),
            "profit_factor": round(profit_factor, 4) if gross_loss else profit_factor,
            "expectancy": round(expectancy, 4),
            "max_drawdown": round(max_dd, 4),
            "false_signals": false_signals,
            "no_trade_quality": 0.0,
        }
