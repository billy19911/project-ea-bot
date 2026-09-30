# -*- coding: utf-8 -*-
"""Zone model (Phase 4 §5–§13, §26–§29) — stable identity + lifecycle.
A Zone is a price area derived from market structure (OB/FVG). It is NOT a
setup, NOT a trigger, NOT an entry (§3). Zones carry:
* stable identity: ``{SYMBOL}-{TF}-{DIR}-{TYPE}-{anchor_price}-{anchor_index}``
  so the same structural zone keeps one id across ticks (no new id per tick);
* mitigation states: FRESH → TOUCHED → PARTIALLY_MITIGATED → FULLY_MITIGATED →
  INVALIDATED;
* touch/retest tracking with configurable ``max_retests``;
* explicit invalidation price + rule, and time expiry.
Pure functions over injected data — no I/O, no MT5, trivially unit-testable.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

__all__ = [
    "Zone",
    "ZoneTouch",
    "zone_identity",
    "detect_zone_touch",
    "evaluate_invalidation",
    "is_zone_expired",
]
# Mitigation states (§28).
MITIGATION_FRESH = "FRESH"
MITIGATION_TOUCHED = "TOUCHED"
MITIGATION_PARTIAL = "PARTIALLY_MITIGATED"
MITIGATION_FULL = "FULLY_MITIGATED"
MITIGATION_INVALIDATED = "INVALIDATED"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_ts() -> float:
    import time

    return time.time()


def zone_identity(
    *,
    symbol: str,
    timeframe: str,
    direction: str,
    zone_type: str,
    anchor_price: float,
    anchor_index: int,
) -> str:
    """Stable zone id: ``{SYM}-{TF}-{DIR}-{TYPE}-{price}-{index}`` (§5).
    The anchor is the structural origin (e.g. OB origin candle index + mid
    price, FVG middle-candle index + mid). Identical structure ⇒ identical id.
    """
    sym = str(symbol or "UNK").upper()
    tf = str(timeframe or "M15").upper()
    d = str(direction or "").upper()
    zt = str(zone_type or "").upper()
    price_part = f"{float(anchor_price):.5f}"
    raw = f"{sym}|{tf}|{d}|{zt}|{price_part}|{int(anchor_index)}"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
    return f"{sym}-{tf}-{d}-{zt}-{digest}"


@dataclass
class Zone:
    """A structural price zone with lifecycle tracking (§5–§13, §26–§29)."""

    zone_id: str
    symbol: str
    direction: str  # LONG (demand/bullish) | SHORT (supply/bearish)
    zone_type: str  # ORDER_BLOCK | FVG
    timeframe: str
    top: float
    bottom: float
    invalidation_price: float
    invalidation_rule: str = ""
    created_at: str = field(default_factory=_now_iso)
    created_ts: float = field(default_factory=_now_ts)
    expires_at_ts: float = 0.0  # 0 = no time expiry
    mitigation: str = MITIGATION_FRESH
    touch_count: int = 0
    first_touch_ts: float = 0.0
    last_touch_ts: float = 0.0
    # Quality/displacement metadata explaining WHY the zone exists (§7).
    displacement_atr: float = 0.0
    gap_atr: float = 0.0
    structure_break: str = ""
    origin_index: int = -1
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def mid(self) -> float:
        return (self.top + self.bottom) / 2.0

    @property
    def height(self) -> float:
        return max(self.top - self.bottom, 0.0)

    def is_live(self) -> bool:
        """False when fully mitigated, invalidated, or expired."""
        if self.mitigation in (MITIGATION_FULL, MITIGATION_INVALIDATED):
            return False
        if self.expires_at_ts and _now_ts() > self.expires_at_ts:
            return False
        return True

    def record_touch(self, ts: Optional[float] = None) -> None:
        """Record a zone touch; advances mitigation FRESH→TOUCHED→PARTIAL."""
        now = float(ts if ts is not None else _now_ts())
        object.__setattr__(self, "touch_count", self.touch_count + 1)
        if not self.first_touch_ts:
            object.__setattr__(self, "first_touch_ts", now)
        object.__setattr__(self, "last_touch_ts", now)
        if self.mitigation == MITIGATION_FRESH:
            object.__setattr__(self, "mitigation", MITIGATION_TOUCHED)
        elif self.mitigation == MITIGATION_TOUCHED:
            object.__setattr__(self, "mitigation", MITIGATION_PARTIAL)

    def mark_fully_mitigated(self) -> None:
        object.__setattr__(self, "mitigation", MITIGATION_FULL)

    def mark_invalidated(self, reason: str = "") -> None:
        object.__setattr__(self, "mitigation", MITIGATION_INVALIDATED)
        if reason:
            self.metadata["invalidation_reason"] = reason

    def retests_exceeded(self, max_retests: int) -> bool:
        """True when touch_count exceeds the allowed retests (§29)."""
        return self.touch_count > max(0, int(max_retests))

    def to_dict(self) -> dict[str, Any]:
        return {
            "zone_id": self.zone_id,
            "symbol": self.symbol,
            "direction": self.direction,
            "zone_type": self.zone_type,
            "timeframe": self.timeframe,
            "top": self.top,
            "bottom": self.bottom,
            "mid": self.mid,
            "invalidation_price": self.invalidation_price,
            "invalidation_rule": self.invalidation_rule,
            "mitigation": self.mitigation,
            "touch_count": self.touch_count,
            "first_touch_ts": self.first_touch_ts,
            "last_touch_ts": self.last_touch_ts,
            "displacement_atr": self.displacement_atr,
            "gap_atr": self.gap_atr,
            "structure_break": self.structure_break,
            "origin_index": self.origin_index,
            "created_at": self.created_at,
            "live": self.is_live(),
        }


@dataclass(frozen=True)
class ZoneTouch:
    """Result of deterministic zone-touch detection (§12)."""

    touched: bool
    zone_id: str = ""
    touch_price: float = 0.0
    # Which price established the touch: bid/ask/mid/close.
    price_kind: str = ""
    reason: str = ""


def detect_zone_touch(
    zone: Zone,
    *,
    bid: float = 0.0,
    ask: float = 0.0,
    candle_high: float = 0.0,
    candle_low: float = 0.0,
    tolerance: float = 0.0,
) -> ZoneTouch:
    """Deterministic zone-touch detection (§12, §34).
    LONG (demand): touch when bid (executable sell price) or the candle range
    reaches the zone. SHORT (supply): touch when ask reaches the zone.
    Candle range intersection also counts (wick touch). Touch NEVER implies
    entry — it yields WAIT_TRIGGER downstream.
    Args:
        zone: The zone to test.
        bid/ask: Live executable prices (0 = unavailable).
        candle_high/candle_low: Current/trigger candle range (0 = unavailable).
        tolerance: Extra buffer beyond the band (price units).
    Returns:
        ZoneTouch with touched=True only on a real intersection.
    """
    top = zone.top + max(tolerance, 0.0)
    bottom = zone.bottom - max(tolerance, 0.0)
    is_long = str(zone.direction).upper() in ("LONG", "BUY", "BULLISH")
    # 1. Executable price touch (bid for LONG exits/entries, ask for SHORT).
    ref = bid if is_long else ask
    if ref and ref > 0 and bottom <= ref <= top:
        return ZoneTouch(
            touched=True,
            zone_id=zone.zone_id,
            touch_price=ref,
            price_kind="bid" if is_long else "ask",
            reason=f"{'bid' if is_long else 'ask'} inside zone",
        )
    # 2. Candle range intersection (wick touch counts as touch, not entry).
    if candle_high > 0 and candle_low > 0 and candle_low <= top and candle_high >= bottom:
        mid = (candle_high + candle_low) / 2.0
        return ZoneTouch(
            touched=True,
            zone_id=zone.zone_id,
            touch_price=mid,
            price_kind="candle_range",
            reason="candle range intersects zone",
        )
    return ZoneTouch(touched=False, zone_id=zone.zone_id, reason="no intersection")


def evaluate_invalidation(
    zone: Zone,
    *,
    close_price: float = 0.0,
) -> tuple[bool, str]:
    """Deterministic invalidation check (§27).
    LONG OB/FVG: invalid when price CLOSES decisively below the invalidation
    boundary. SHORT: closes decisively above. A wick beyond the zone is NOT
    invalidation — only a close. Returns (invalidated, reason).
    """
    if close_price <= 0:
        return False, "no close price"
    is_long = str(zone.direction).upper() in ("LONG", "BUY", "BULLISH")
    if is_long and close_price < zone.invalidation_price:
        return True, (
            f"LONG invalidated: close {close_price} below invalidation "
            f"{zone.invalidation_price} ({zone.invalidation_rule})"
        )
    if not is_long and close_price > zone.invalidation_price:
        return True, (
            f"SHORT invalidated: close {close_price} above invalidation "
            f"{zone.invalidation_price} ({zone.invalidation_rule})"
        )
    return False, "close inside invalidation boundary"


def is_zone_expired(zone: Zone, *, now_ts: Optional[float] = None) -> bool:
    """True when the zone passed its time expiry (§26)."""
    if not zone.expires_at_ts:
        return False
    now = float(now_ts if now_ts is not None else _now_ts())
    return now > zone.expires_at_ts
