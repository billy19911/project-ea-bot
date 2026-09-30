# -*- coding: utf-8 -*-
"""Entry lifecycle manager (Phase 4 §26–§29, §40–§41) — setup registry + idempotency.

Tracks live `SetupCandidate` objects keyed by STABLE ``setup_id`` and enforces:

* no duplicate entry intent: ``(setup_id, trigger_id, candle_ts)`` is unique
  (§40), guarded by a lock so concurrent events cannot both fire (§41);
* mitigation/retest policy via the associated Zone (§28–§29);
* time expiry (§26) and invalidation (§27).

Deterministic and thread-safe; never executes, never sets volume, never touches
MT5.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from .entry_zones import Zone, evaluate_invalidation, is_zone_expired

__all__ = ["SetupRecord", "EntryLifecycleManager"]


@dataclass
class SetupRecord:
    """A tracked setup + its zone + lifecycle metadata."""

    setup_id: str
    symbol: str
    direction: str
    zone: Optional[Zone] = None
    created_ts: float = field(default_factory=time.time)
    expires_ts: float = 0.0
    status: str = "CANDIDATE"
    # Idempotency ledger: fired entry keys for this setup.
    fired_keys: set = field(default_factory=set)

    def to_dict(self) -> dict[str, Any]:
        return {
            "setup_id": self.setup_id,
            "symbol": self.symbol,
            "direction": self.direction,
            "zone": self.zone.to_dict() if self.zone else None,
            "status": self.status,
            "created_ts": self.created_ts,
            "expires_ts": self.expires_ts,
            "fired_keys": sorted(self.fired_keys),
            "live": self.is_live(),
        }

    def is_live(self) -> bool:
        if self.status in ("INVALID", "EXPIRED", "CLOSED"):
            return False
        if self.expires_ts and time.time() > self.expires_ts:
            return False
        return True


class EntryLifecycleManager:
    """Registry of live setups with idempotency + lifecycle enforcement."""

    def __init__(self, *, max_records: int = 500) -> None:
        self._records: dict[str, SetupRecord] = {}
        self._lock = threading.RLock()
        self._max_records = max(1, int(max_records))

    # ------------------------------------------------------------------
    def register(
        self,
        setup_id: str,
        symbol: str,
        direction: str,
        *,
        zone: Optional[Zone] = None,
        expires_ts: float = 0.0,
    ) -> SetupRecord:
        """Register (or return the existing) setup record — stable identity."""
        with self._lock:
            existing = self._records.get(setup_id)
            if existing is not None:
                return existing
            if len(self._records) >= self._max_records:
                # Bounded: drop the oldest insertion.
                try:
                    oldest = next(iter(self._records))
                    self._records.pop(oldest, None)
                except StopIteration:
                    pass
            rec = SetupRecord(
                setup_id=setup_id,
                symbol=symbol,
                direction=direction,
                zone=zone,
                expires_ts=expires_ts,
            )
            self._records[setup_id] = rec
            return rec

    def get(self, setup_id: str) -> Optional[SetupRecord]:
        with self._lock:
            return self._records.get(setup_id)

    # ------------------------------------------------------------------
    def evaluate_lifecycle(
        self,
        setup_id: str,
        *,
        close_price: float = 0.0,
        now_ts: Optional[float] = None,
    ) -> tuple[str, str]:
        """Return the current lifecycle status: (status, reason) (§26–§27).

        Terminal statuses: INVALID (decisive close beyond boundary) / EXPIRED
        (time). Non-terminal: CANDIDATE / ARMED / WAITING_TRIGGER.
        """
        with self._lock:
            rec = self._records.get(setup_id)
            if rec is None:
                return "UNKNOWN", "setup not registered"
            now = float(now_ts if now_ts is not None else time.time())
            if rec.expires_ts and now > rec.expires_ts:
                rec.status = "EXPIRED"
                return "EXPIRED", "setup time expired"
            if rec.zone is not None:
                if is_zone_expired(rec.zone, now_ts=now):
                    rec.status = "EXPIRED"
                    return "EXPIRED", "zone time expired"
                inv, reason = evaluate_invalidation(rec.zone, close_price=close_price)
                if inv:
                    rec.zone.mark_invalidated(reason)
                    rec.status = "INVALID"
                    return "INVALID", reason
            return rec.status, "ok"

    # ------------------------------------------------------------------
    def claim_entry(
        self,
        setup_id: str,
        *,
        trigger_id: str,
        candle_ts: float,
    ) -> bool:
        """Idempotent entry claim (§40–§41): True only on the FIRST claim.

        Two concurrent callers with the same ``(setup_id, trigger_id,
        candle_ts)`` → exactly one True. Different candle/trigger → new claim.
        """
        key = f"{trigger_id}@{float(candle_ts):.3f}"
        with self._lock:
            rec = self._records.get(setup_id)
            if rec is None:
                return False
            if key in rec.fired_keys:
                return False
            rec.fired_keys.add(key)
            return True

    def has_fired(self, setup_id: str, *, trigger_id: str, candle_ts: float) -> bool:
        key = f"{trigger_id}@{float(candle_ts):.3f}"
        with self._lock:
            rec = self._records.get(setup_id)
            return bool(rec and key in rec.fired_keys)

    def mark_status(self, setup_id: str, status: str) -> None:
        with self._lock:
            rec = self._records.get(setup_id)
            if rec is not None:
                rec.status = status

    def clear(self, setup_id: str) -> None:
        with self._lock:
            self._records.pop(setup_id, None)

    def clear_all(self) -> None:
        with self._lock:
            self._records.clear()

    def count(self) -> int:
        with self._lock:
            return len(self._records)
