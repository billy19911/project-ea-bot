# -*- coding: utf-8 -*-
"""Strategy Memory (§17) — per-strategy performance notes and statistics.

Strategy memory keeps a per-strategy record (free-form notes plus an isolated
cumulative statistics accumulator). Strategies never bleed into one another:
each key maps to its own record and stats. The store is size-bounded. No
external database is required.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class StrategyRecord:
    """Notes and rolling statistics for a single strategy."""

    name: str
    notes: dict[str, Any] = field(default_factory=dict)
    trades: int = 0
    wins: int = 0
    losses: int = 0
    total_pnl: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "notes": dict(self.notes),
            "stats": {
                "trades": self.trades,
                "wins": self.wins,
                "losses": self.losses,
                "total_pnl": self.total_pnl,
            },
        }

    def stats(self) -> dict[str, Any]:
        """Return the cumulative statistics snapshot."""
        win_rate = (self.wins / self.trades) if self.trades else 0.0
        return {
            "trades": self.trades,
            "wins": self.wins,
            "losses": self.losses,
            "total_pnl": self.total_pnl,
            "win_rate": win_rate,
        }


class StrategyMemory:
    """Thread-safe, size-bounded per-strategy store with isolated stats."""

    def __init__(self, max_size: int = 200) -> None:
        if max_size <= 0:
            raise ValueError("max_size must be positive")
        self.max_size = max_size
        self._records: dict[str, StrategyRecord] = {}
        self._order: list[str] = []
        self._lock = threading.Lock()

    def _get_or_create_locked(self, strategy: str) -> StrategyRecord:
        record = self._records.get(strategy)
        if record is None:
            record = StrategyRecord(name=strategy)
            self._records[strategy] = record
            self._order.append(strategy)
        return record

    def record(self, strategy: str, notes: Optional[dict[str, Any]] = None) -> StrategyRecord:
        """Merge ``notes`` into the strategy's record (creating it if new)."""
        if not strategy or not str(strategy).strip():
            raise ValueError("StrategyMemory strategy name must be non-empty")
        with self._lock:
            record = self._get_or_create_locked(strategy)
            # Refresh recency for eviction ordering.
            if strategy in self._order:
                self._order.remove(strategy)
                self._order.append(strategy)
            if notes:
                record.notes.update(notes)
            self._evict_locked()
            return record

    def record_outcome(self, strategy: str, pnl: float, win: bool) -> StrategyRecord:
        """Accumulate a single trade outcome for ``strategy``."""
        with self._lock:
            record = self._get_or_create_locked(strategy)
            if strategy in self._order:
                self._order.remove(strategy)
                self._order.append(strategy)
            record.trades += 1
            if win:
                record.wins += 1
            else:
                record.losses += 1
            record.total_pnl += float(pnl)
            self._evict_locked()
            return record

    def get(self, strategy: str) -> Optional[dict[str, Any]]:
        """Return the strategy's notes dict (None if unknown)."""
        with self._lock:
            record = self._records.get(strategy)
            if record is None:
                return None
            return dict(record.notes)

    def stats(self, strategy: str) -> dict[str, Any]:
        """Return statistics for ``strategy`` (empty defaults if unknown)."""
        with self._lock:
            record = self._records.get(strategy)
            if record is None:
                return {
                    "trades": 0,
                    "wins": 0,
                    "losses": 0,
                    "total_pnl": 0.0,
                    "win_rate": 0.0,
                }
            return record.stats()

    def strategies(self) -> list[str]:
        """Return the tracked strategy names (most-recently-touched last)."""
        with self._lock:
            return list(self._order)

    def __len__(self) -> int:
        with self._lock:
            return len(self._records)

    def _evict_locked(self) -> None:
        """Evict oldest-touched strategies until within ``max_size``."""
        while len(self._order) > self.max_size:
            oldest = self._order.pop(0)
            self._records.pop(oldest, None)
