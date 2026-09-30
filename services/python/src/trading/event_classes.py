# -*- coding: utf-8 -*-
"""Event classification and gating for task-02 event-driven supervisor.

This module implements the EVENT CLASS taxonomy from PRD_V2 §15 + MASTER_PLAN
section 4 (TASK 02):

  * TRADE_TRIGGER — may trigger committee analysis:
    BREAKOUT, BREAKDOWN, REVERSAL, STRUCTURE_SHIFT, MOMENTUM_CONFIRMATION,
    ZONE_ENTRY, VOLATILITY_EXPANSION

  * CONTEXT_UPDATE — update context, do NOT create trade proposal:
    NEWS_UPDATE, ECONOMIC_EVENT, REGIME_CHANGE, VOLATILITY_CHANGE

  * HOUSEKEEPING — must NEVER create trade signal:
    RECONCILIATION, HEALTH_CHECK, METRICS, RISK_*, DRAWDOWN_, MARGIN_*

  * TRADE_CLOSE — review/learning only; evaluate opportunity AFTER close
    (but do not blind-repeat previous signals)

The classifier is deterministic and conservative: unknown/ambiguous event types
map to a safe default (CONTEXT_UPDATE level) to avoid breaking existing flows
while still stopping obvious spam (HOUSEKEEPING events).

Duplicate-suppression uses the same classification plus an event-fingerprint
(symbol+type+bar_index) to prevent repeated committee cycles for identical
events.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class EventClassKind(str, Enum):
    """Event class constants."""

    TRADE_TRIGGER = "TRADE_TRIGGER"
    CONTEXT_UPDATE = "CONTEXT_UPDATE"
    HOUSEKEEPING = "HOUSEKEEPING"
    TRADE_CLOSE = "TRADE_CLOSE"


# Trade-trigger event types (plan's canonical list).
_TRADE_TRIGGER_TYPES = frozenset(
    {
        # Plan's explicit TRADE_TRIGGER list
        "BREAKOUT",
        "BREAKDOWN",
        "REVERSAL",
        "STRUCTURE_SHIFT",
        "MOMENTUM_CONFIRMATION",
        "ZONE_ENTRY",
        "VOLATILITY_EXPANSION",
        # Phase-4 trigger-evaluation events (entry-level, allowed)
        "TRIGGER_APPROACHING",
        "SETUP_FORMED",
        "SETUP_INVALIDATED",
        # Momentum / regime events the production detector emits as real triggers
        # (the committee synthesises BUY/SELL proposals from these).
        "MOMENTUM_BULLISH",
        "MOMENTUM_BEARISH",
        "MOMENTUM_DIVERGENCE",
        "EMA_CROSSOVER",
        "MACD_CROSSOVER",
        "RSI_OVERBOUGHT",
        "RSI_OVERSOLD",
        "STOCH_OVERBOUGHT",
        "STOCH_OVERSOLD",
        "GAP_UP",
        "GAP_DOWN",
        "VOLATILITY_SPIKE",
        "VOLATILITY_EXPANDING",
        "DOJI",
    }
)

# Housekeeping event type patterns (must never create proposals).
_HOUSEKEEPING_PREFIXES = (
    "RISK_",
    "DRAWDOWN_",
    "EXPOSURE_",
    "MARGIN_",
    "PORTFOLIO_",
    "CORRELATION",
    "RECONCILIATION",
    "HEALTH_CHECK",
    "METRICS",
)
_HOUSEKEEPING_TYPES = frozenset(
    {
        "LIQUIDITY_WARNING",
        "POSITION_OPENED",
        "POSITION_CLOSED",
    }
)

# Context-update patterns (update context, no new proposals). Used for events
# that carry information but should not themselves convene the committee.
_CONTEXT_UPDATE_PREFIXES = (
    "NEWS_",
    "ECONOMIC_",
    "MACRO_",
    "SOCIAL_",
)
_CONTEXT_UPDATE_TYPES = frozenset(
    {
        "REGIME_CHANGE",  # named context update in the plan (not a trade trigger)
        "VOLATILITY_CHANGE",
    }
)

# Regime/trend events: the production feed loop's primary output. The committee
# synthesises actionable proposals from these, so they qualify as trade triggers
# but are subject to the duplicate-suppression window.
_TREND_TRIGGER_PREFIXES = ("TREND_",)


def classify_event_class(event_type: str) -> EventClassKind:
    """Classify an event type into one of the four event classes.

    Args:
        event_type: Raw event type string (e.g., "BREAKOUT", "RISK_DRAWDOWN").

    Returns:
        EventClassKind enum value indicating the event class.

    Design note:
        Unknown/ambiguous types map to CONTEXT_UPDATE (safe default, won't break
        existing flows). Known-housekeeping types block proposals entirely.
        TREND_*, MOMENTUM_*, BREAKOUT, etc. are classified as TRADE_TRIGGER since
        these are what the production feed loop emits and the committee acts on.
    """
    raw = str(event_type or "").upper().strip()

    # 1. Housekeeping types (highest priority — must never allow proposals).
    for prefix in _HOUSEKEEPING_PREFIXES:
        if raw.startswith(prefix):
            return EventClassKind.HOUSEKEEPING
    if raw in _HOUSEKEEPING_TYPES:
        return EventClassKind.HOUSEKEEPING

    # 2. Trade-close (review/learning path).
    if raw in ("TRADE_CLOSE", "POST_TRADE_REVIEW"):
        return EventClassKind.TRADE_CLOSE

    # 3. News/economic context events (update context, no proposal needed).
    for prefix in _CONTEXT_UPDATE_PREFIXES:
        if raw.startswith(prefix):
            return EventClassKind.CONTEXT_UPDATE
    if raw in _CONTEXT_UPDATE_TYPES:
        return EventClassKind.CONTEXT_UPDATE

    # 4. Explicit trade triggers (plan's canonical list).
    if raw in _TRADE_TRIGGER_TYPES:
        return EventClassKind.TRADE_TRIGGER

    # 5. Trend/regime events (production detector's primary output).
    for prefix in _TREND_TRIGGER_PREFIXES:
        if raw.startswith(prefix):
            return EventClassKind.TRADE_TRIGGER

    # Default: treat as context update (no new proposal needed).
    return EventClassKind.CONTEXT_UPDATE


def is_trade_trigger(event_type: str) -> bool:
    """Return True if event_type is a TRADE_TRIGGER class event.

    Housekeeping/CONTEXT_UPDATE events return False.
    """
    return classify_event_class(event_type) == EventClassKind.TRADE_TRIGGER


def should_run_committee(event_type: str) -> bool:
    """Return True if the committee should run for this event type.

    Criteria:
      - TRADE_TRIGGER events: YES
      - CONTEXT_UPDATE/HOUSEKEEPING: NO (context update only)
      - TRADE_CLOSE: NO (handled by review path)

    This is the gate logic for the event-driven supervisor.
    """
    return classify_event_class(event_type) == EventClassKind.TRADE_TRIGGER


@dataclass
class DuplicateRecord:
    """Track deduplicated event instances."""

    symbol: str
    event_type: str
    fingerprint: tuple
    timestamp: float
    ttl_seconds: float
    result: Optional[str] = None  # "SIGNAL", "NO_TRADE", "BLOCKED"


class EventFingerprintGuillotine:
    """Suppress repeated identical events via TTL-based deduplication.

    This is TASK 02's duplicate-event guard: the same (symbol, event_type,
    bar_fingerprint) within the suppression window does NOT re-run the committee.

    Attributes:
        default_ttl_seconds: Time-to-live for duplicate suppression (default 300s).
        max_size: Maximum dedup records held (memory guard, default 10000).
    """

    def __init__(self, default_ttl_seconds: float = 300.0, max_size: int = 10000) -> None:
        self._default_ttl = float(default_ttl_seconds)
        self._max_size = int(max_size)
        self._records: dict[tuple[str, str], DuplicateRecord] = {}
        self._clock = time.monotonic
        self._evictions = 0

    def _key(self, symbol: str, event_type: str) -> tuple[str, str]:
        return (str(symbol or "").upper(), str(event_type or "").upper())

    def check_and_record(
        self,
        symbol: str,
        event_type: str,
        fingerprint: tuple,
        ttl_seconds: Optional[float] = None,
        result: Optional[str] = None,
    ) -> bool:
        """Check if (symbol,event_type,fingerprint) has been seen recently.

        If new: record it and return True (allow processing).
        If duplicate: return False (suppress) without changing the record.

        Args:
            symbol: Trading symbol (e.g., XAUUSD).
            event_type: Event type (e.g., BREAKOUT).
            fingerprint: Deterministic tuple identifying the event instance
                (e.g., (bar_index, last_close, bar_time)).
            ttl_seconds: Optional override for this specific event's TTL.
            result: Optional result code ("SIGNAL"/"NO_TRADE"/"BLOCKED") to store.

        Returns:
            True if this is a NEW unique event (allow processing), False if it's
            a duplicate within TTL (suppress).
        """
        key = self._key(symbol, event_type)
        now = self._clock()
        ttl = float(ttl_seconds or self._default_ttl)

        existing = self._records.get(key)
        if existing is not None:
            # Eviction policy: compact stale records periodically.
            if len(self._records) > self._max_size * 0.75:
                self._evict_stale(now)

        if existing is None or now > existing.timestamp + existing.ttl_seconds:
            # New or expired: record this instance.
            if len(self._records) >= self._max_size:
                self._evict_stale(now)
            self._records[key] = DuplicateRecord(
                symbol=symbol,
                event_type=event_type,
                fingerprint=fingerprint,
                timestamp=now,
                ttl_seconds=ttl,
                result=result,
            )
            return True

        # Still within TTL: compare fingerprints.
        if existing.fingerprint == fingerprint:
            # Identical: suppress.
            return False
        else:
            # Different fingerprint (materially changed market state): refresh.
            self._records[key] = DuplicateRecord(
                symbol=symbol,
                event_type=event_type,
                fingerprint=fingerprint,
                timestamp=now,
                ttl_seconds=ttl,
                result=result,
            )
            return True

    def _evict_stale(self, now: float) -> None:
        """Remove records older than their TTL (background compaction)."""
        kept: dict[tuple[str, str], DuplicateRecord] = {}
        evicted_count = 0
        for record in self._records.values():
            if now < record.timestamp + record.ttl_seconds:
                kept[(record.symbol, record.event_type)] = record
            else:
                evicted_count += 1
        self._records = kept
        if evicted_count > 0:
            self._evictions += 1

    @property
    def count(self) -> int:
        """Return current dedup record count."""
        return len(self._records)

    @property
    def total_evictions(self) -> int:
        """Return total records evicted since instantiation."""
        return self._evictions


class EventGate:
    """Combine event-class classification + duplicate suppression.

    This is the TASK 02 qualifying-event gate that sits between the EventQueue
    and the TradingPipeline (scheduler). It enforces:

      1. Non-qualifying events (HOUSEKEEPING/CONTEXT_UPDATE) do not reach committee.
      2. Identical events within TTL do not re-run committee.
      3. Qualifying events with materially changed fingerprints proceed.
    """

    def __init__(
        self,
        duplicate_ttl_seconds: float = 300.0,
        max_dedup_records: int = 10000,
    ) -> None:
        self.classification_enabled = True
        self.duplicate_gating_enabled = True
        self.fingerprints = EventFingerprintGuillotine(
            default_ttl_seconds=duplicate_ttl_seconds,
            max_size=max_dedup_records,
        )
        self._stats: dict[str, int] = {
            "checked": 0,
            "allowed": 0,
            "blocked_classification": 0,
            "blocked_duplicate": 0,
        }

    def check(
        self,
        event_type: str,
        symbol: str,
        fingerprint: Optional[tuple] = None,
        metadata: Optional[dict] = None,
    ) -> tuple[bool, str]:
        """Decide whether an event may proceed to the committee.

        Args:
            event_type: Event type string.
            symbol: Trading symbol.
            fingerprint: Optional deterministic tuple (bar_index, close, time).
            metadata: Optional event metadata (bar_index, etc.).

        Returns:
            (allowed, reason). When allowed=False, reason explains why.
        """
        self._stats["checked"] += 1
        event_type_str = str(event_type or "").upper()
        symbol_str = str(symbol or "")

        # 1. Class check: non-qualifying types blocked immediately.
        if self.classification_enabled:
            kind = classify_event_class(event_type_str)
            if kind != EventClassKind.TRADE_TRIGGER:
                self._stats["blocked_classification"] += 1
                reason = f"non-qualifying event class ({kind.value}); skipping committee"
                return False, reason

        # 2. Duplicate check: suppress identical events within TTL.
        if self.duplicate_gating_enabled and fingerprint is not None:
            if not self.fingerprints.check_and_record(
                symbol=symbol_str,
                event_type=event_type_str,
                fingerprint=fingerprint,
            ):
                self._stats["blocked_duplicate"] += 1
                return False, "duplicate event suppressed within TTL window"

        self._stats["allowed"] += 1
        return True, ""

    def record_result(self, event_type: str, symbol: str, fingerprint: tuple, result: str) -> None:
        """Record the cycle result for future duplicate checks.

        This updates the dedup record so future identical events see "SIGNAL"
        or "NO_TRADE" status.
        """
        self.fingerprints.check_and_record(
            symbol=symbol,
            event_type=str(event_type).upper(),
            fingerprint=fingerprint,
            result=result,
        )

    def stats(self) -> dict[str, int]:
        """Return statistics about classification/dedup activity."""
        return {
            **self._stats,
            "dedup_count": self.fingerprints.count,
            "total_evictions": self.fingerprints.total_evictions,
        }
