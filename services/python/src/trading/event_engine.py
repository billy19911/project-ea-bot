# -*- coding: utf-8 -*-
"""Event Engine — priority, queue, history, deduplication for detected events.

Phase 5 extensions:
- EventPriority enum (LOW/MEDIUM/HIGH/CRITICAL)
- EVENT_PRIORITY_MAP for all EventTypes
- EventQueue with priority ordering and max_size
- EventHistory with filtering and max_size
- EventDeduplicator to prevent duplicate events within N bars
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

from .events import DetectedEvent, EventTypes


class EventPriority(Enum):
    """Priority levels for market events. Higher value = higher priority."""

    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


# Priority mapping covering every EventTypes member.
EVENT_PRIORITY_MAP: dict[EventTypes, EventPriority] = {
    # --- Risk events: CRITICAL ---
    EventTypes.DRAWDOWN_WARNING: EventPriority.CRITICAL,
    EventTypes.EXPOSURE_LIMIT_REACHED: EventPriority.CRITICAL,
    EventTypes.LIQUIDITY_WARNING: EventPriority.CRITICAL,
    # --- Price action breakouts/reversals/gaps: HIGH ---
    EventTypes.BREAKOUT: EventPriority.HIGH,
    EventTypes.BREAKDOWN: EventPriority.HIGH,
    EventTypes.REVERSAL: EventPriority.HIGH,
    EventTypes.GAP_UP: EventPriority.HIGH,
    EventTypes.GAP_DOWN: EventPriority.HIGH,
    EventTypes.VOLATILITY_SPIKE: EventPriority.HIGH,
    # --- Indicator crossovers: HIGH ---
    EventTypes.EMA_CROSSOVER: EventPriority.HIGH,
    EventTypes.MACD_CROSSOVER: EventPriority.HIGH,
    # --- Volatility regime shifts: MEDIUM ---
    EventTypes.VOLATILITY_EXPANDING: EventPriority.MEDIUM,
    EventTypes.VOLATILITY_CONTRACTING: EventPriority.MEDIUM,
    # --- Momentum: MEDIUM ---
    EventTypes.MOMENTUM_BULLISH: EventPriority.MEDIUM,
    EventTypes.MOMENTUM_BEARISH: EventPriority.MEDIUM,
    EventTypes.MOMENTUM_DIVERGENCE: EventPriority.MEDIUM,
    # --- Trend: MEDIUM (neutral is LOW) ---
    EventTypes.TREND_BULLISH: EventPriority.MEDIUM,
    EventTypes.TREND_BEARISH: EventPriority.MEDIUM,
    EventTypes.TREND_NEUTRAL: EventPriority.LOW,
    EventTypes.TREND_STRENGTHENING: EventPriority.MEDIUM,
    EventTypes.TREND_WEAKENING: EventPriority.MEDIUM,
    # --- RSI / Stochastic extremes: MEDIUM ---
    EventTypes.RSI_OVERBOUGHT: EventPriority.MEDIUM,
    EventTypes.RSI_OVERSOLD: EventPriority.MEDIUM,
    EventTypes.STOCH_OVERBOUGHT: EventPriority.MEDIUM,
    EventTypes.STOCH_OVERSOLD: EventPriority.MEDIUM,
    # --- Candlestick pattern: LOW ---
    EventTypes.DOJI: EventPriority.LOW,
}


def get_priority(event_type: EventTypes) -> EventPriority:
    """Return priority for an event type (default MEDIUM)."""
    return EVENT_PRIORITY_MAP.get(event_type, EventPriority.MEDIUM)


@dataclass
class PrioritizedEvent:
    """Event wrapper with priority for queue ordering."""

    event: DetectedEvent
    priority: EventPriority
    sequence: int


class EventQueue:
    """In-memory FIFO event queue with priority ordering and max size.

    Highest priority dequeues first; FIFO within same priority.
    Thread-safe via threading.Lock. Sync API so EventDetector.detect()
    (sync) can enqueue without an event loop.
    """

    def __init__(self, max_size: int = 1000) -> None:
        """Initialize the queue.

        Args:
            max_size: Maximum events held (default 1000).
        """
        self._max_size = max_size
        self._queue: list[PrioritizedEvent] = []
        self._lock = threading.Lock()
        self._sequence = 0

    @property
    def max_size(self) -> int:
        """Return max queue size."""
        return self._max_size

    def enqueue(self, event: DetectedEvent) -> bool:
        """Add event to queue.

        Args:
            event: Detected event to enqueue.

        Returns:
            True if enqueued, False if queue full.
        """
        with self._lock:
            if len(self._queue) >= self._max_size:
                return False
            priority = get_priority(event.event_type)
            self._queue.append(
                PrioritizedEvent(event=event, priority=priority, sequence=self._sequence)
            )
            self._sequence += 1
            return True

    def dequeue(self) -> Optional[DetectedEvent]:
        """Remove and return highest-priority event, else None."""
        with self._lock:
            if not self._queue:
                return None
            best_idx = 0
            best = self._queue[0]
            for i in range(1, len(self._queue)):
                cand = self._queue[i]
                if (cand.priority.value > best.priority.value) or (
                    cand.priority.value == best.priority.value and cand.sequence < best.sequence
                ):
                    best = cand
                    best_idx = i
            return self._queue.pop(best_idx).event

    def peek(self) -> list[DetectedEvent]:
        """Return queued events sorted by priority (highest first)."""
        with self._lock:
            ordered = sorted(self._queue, key=lambda x: (-x.priority.value, x.sequence))
            return [pe.event for pe in ordered]

    def clear(self) -> None:
        """Clear all queued events."""
        with self._lock:
            self._queue.clear()

    def __len__(self) -> int:
        """Return current queue size."""
        with self._lock:
            return len(self._queue)


class EventHistory:
    """In-memory event history with filtering and max-size eviction.

    Oldest events evicted on overflow. Thread-safe via threading.Lock.
    """

    def __init__(self, max_size: int = 10000) -> None:
        """Initialize history.

        Args:
            max_size: Maximum stored events (default 10000).
        """
        self._max_size = max_size
        self._history: list[DetectedEvent] = []
        self._lock = threading.Lock()

    @property
    def max_size(self) -> int:
        """Return max history size."""
        return self._max_size

    def add(self, event: DetectedEvent) -> None:
        """Append event, evicting oldest on overflow."""
        with self._lock:
            self._history.append(event)
            while len(self._history) > self._max_size:
                self._history.pop(0)

    def get(
        self,
        since: Optional[datetime] = None,
        symbol: Optional[str] = None,
        event_type: Optional[EventTypes] = None,
        limit: int = 100,
    ) -> list[DetectedEvent]:
        """Query history, newest first.

        Args:
            since: Only events at/after this time.
            symbol: Filter by symbol.
            event_type: Filter by type.
            limit: Max results (default 100).

        Returns:
            Matching events, newest first.
        """
        with self._lock:
            snapshot = list(self._history)
        results: list[DetectedEvent] = []
        for event in reversed(snapshot):
            if symbol is not None and event.symbol != symbol:
                continue
            if event_type is not None and event.event_type != event_type:
                continue
            if since is not None:
                try:
                    ets = datetime.fromisoformat(event.timestamp)
                except (ValueError, TypeError):
                    continue
                # Naive vs aware: normalize naive to same tz as event.
                if since.tzinfo is None and ets.tzinfo is not None:
                    ets = ets.replace(tzinfo=None)
                elif since.tzinfo is not None and ets.tzinfo is None:
                    continue
                if ets < since:
                    continue
            results.append(event)
            if len(results) >= limit:
                break
        return results

    def get_counts_by_type(self, since: Optional[datetime] = None) -> dict[EventTypes, int]:
        """Count stored events by type, optionally filtered by time."""
        with self._lock:
            snapshot = list(self._history)
        counts: dict[EventTypes, int] = {}
        for event in snapshot:
            if since is not None:
                try:
                    ets = datetime.fromisoformat(event.timestamp)
                except (ValueError, TypeError):
                    continue
                if since.tzinfo is None and ets.tzinfo is not None:
                    ets = ets.replace(tzinfo=None)
                elif since.tzinfo is not None and ets.tzinfo is None:
                    continue
                if ets < since:
                    continue
            counts[event.event_type] = counts.get(event.event_type, 0) + 1
        return counts

    def clear(self) -> None:
        """Clear all history."""
        with self._lock:
            self._history.clear()

    def __len__(self) -> int:
        """Return current history size."""
        with self._lock:
            return len(self._history)


class EventDeduplicator:
    """Skip repeat (symbol, event_type) emissions within N bars."""

    def __init__(self, dedup_window: int = 5) -> None:
        """Initialize deduplicator.

        Args:
            dedup_window: Bars to suppress repeats (default 5).
        """
        self._dedup_window = dedup_window
        self._last_bar: dict[tuple[str, EventTypes], int] = {}
        self._lock = threading.Lock()

    @property
    def dedup_window(self) -> int:
        """Return dedup window in bars."""
        return self._dedup_window

    def should_emit(self, symbol: str, event_type: EventTypes, bar_index: int) -> bool:
        """Check emission; record bar index on first/new-window hit.

        Args:
            symbol: Trading symbol.
            event_type: Event type.
            bar_index: Current bar index (monotonic).

        Returns:
            True if emit allowed, False if duplicate within window.
        """
        with self._lock:
            key = (symbol, event_type)
            last = self._last_bar.get(key)
            if last is None or bar_index - last > self._dedup_window:
                self._last_bar[key] = bar_index
                return True
            return False

    def clear(self) -> None:
        """Reset dedup state."""
        with self._lock:
            self._last_bar.clear()
