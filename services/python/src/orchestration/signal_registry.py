# -*- coding: utf-8 -*-
"""Signal Registry — the authoritative per-symbol trade-signal state machine.

Why this exists (FOKUS #2 — "jangan muncul banyak sinyal"):

    Before this module the autonomous loop re-ran the FULL committee on every
    market event (every feed poll), so the same ``#BTCUSD BUY`` signal was
    produced and recorded over and over. When the Risk Gate approved but the
    execution engine failed closed (e.g. terminal not armed → 403), nothing
    was recorded as an entry, so the single-entry / cooldown guards never
    armed, and the identical ``BUY / ERROR`` row repeated indefinitely.

    The user's intent is a *conversation-style* flow:

    1. Supervisor asks "what's the market condition / is there a signal?".
    2. The committee convenes ONCE, analyses the real data.
    3. No signal → answer "no signal right now" (WAIT / NO_TRADE), do nothing.
    4. Signal exists → check whether it is worth executing.
    5. Worth executing → execute; while the trade is open the supervisor does
       NOT ask/re-analyse again.

    This registry is the single source of truth for "is there already a live
    signal for this symbol?". The pipeline consults it BEFORE running the
    committee and after every execution attempt.

State machine (per symbol)::

    NONE ──signal──> PENDING ──executing──> EXECUTING ──ok──> OPEN ──closed──> CLOSED
                        │                       │
                        │                       └──fail──> FAILED (terminal)
                        └──not worth executing──> SKIPPED (terminal)

    * ``PENDING``   — a signal exists but has not reached execution yet. While
                      PENDING, a new identical signal must NOT re-run the
                      committee; it is absorbed.
    * ``EXECUTING`` — an order was submitted, awaiting confirmation.
    * ``OPEN``      — a position is live. No re-analysis until it closes.
    * ``FAILED``    — execution failed. The signal is terminal but the symbol is
                      placed on a *cooldown* so a failing execution does not
                      spam a fresh identical signal every cycle.
    * ``SKIPPED``   — the committee decided the signal is not worth executing.

Only ONE non-terminal signal per symbol may exist at a time. This is the guard
the pipeline uses to answer "there is already a signal; do not convene again".

The registry is process-wide (a ``builtins`` slot, mirroring the pattern used by
``telegram.notifier`` / ``telegram.signal_lifecycle``) so the ``src.*`` and
top-level import identities share one instance. It is intentionally in-memory —
the authoritative audit of every cycle still lives in ``/decisions`` and the
trade ledger; this is a *gate*, not a ledger.
"""

from __future__ import annotations

import builtins
import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "SignalPhase",
    "ActiveSignal",
    "SignalRegistry",
    "get_signal_registry",
    "set_signal_registry",
    "reset_signal_registry",
]

# Shared-instance slot (survives duplicate module import paths).
_SLOT = "_xynn_signal_registry"


# ---------------------------------------------------------------------------
# Phases
# ---------------------------------------------------------------------------
class SignalPhase:
    """Signal lifecycle phases (plain strings for easy JSON/log use)."""

    PENDING = "PENDING"
    EXECUTING = "EXECUTING"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


# Phases that mean "a signal is still live for this symbol" → do not convene a
# fresh committee / do not emit a new signal.
_ACTIVE_PHASES = frozenset({SignalPhase.PENDING, SignalPhase.EXECUTING, SignalPhase.OPEN})

# Default cooldown after a FAILED execution (seconds). A failed execution puts
# the symbol to sleep so the identical signal is not re-emitted every cycle.
DEFAULT_FAILURE_COOLDOWN_S = 900.0  # 15 min


def _coerce_px(value: Any) -> Optional[float]:
    """Best-effort float; ``None`` when unavailable/NaN."""
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    return number


@dataclass
class ActiveSignal:
    """One symbol's current trade-signal state."""

    symbol: str
    direction: str  # BUY / SELL
    phase: str = SignalPhase.PENDING
    confidence: float = 0.0
    entry: Optional[float] = None
    sl: Optional[float] = None
    tp1: Optional[float] = None
    tp2: Optional[float] = None
    tpmax: Optional[float] = None
    ticket: Optional[Any] = None
    reason: str = ""
    proposal_id: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0

    # -- serialisation --------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "direction": self.direction,
            "phase": self.phase,
            "confidence": self.confidence,
            "entry": self.entry,
            "sl": self.sl,
            "tp1": self.tp1,
            "tp2": self.tp2,
            "tpmax": self.tpmax,
            "ticket": self.ticket,
            "reason": self.reason,
            "proposal_id": self.proposal_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @property
    def is_active(self) -> bool:
        """True while a signal for this symbol is still live."""
        return self.phase in _ACTIVE_PHASES


class SignalRegistry:
    """Process-wide, thread-safe registry of active trade signals.

    Args:
        clock: Injectable clock (unix seconds) for tests.
        failure_cooldown_s: After a FAILED execution, how long before a fresh
            signal for the same symbol may be raised again.
    """

    def __init__(
        self,
        clock: Optional[Any] = None,
        failure_cooldown_s: float = DEFAULT_FAILURE_COOLDOWN_S,
    ) -> None:
        self._clock = clock or time.time
        self._lock = threading.RLock()
        self._signals: dict[str, ActiveSignal] = {}
        self._failure_cooldown_s = float(failure_cooldown_s)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    @staticmethod
    def _key(symbol: Any) -> str:
        return str(symbol or "").strip().upper()

    def get(self, symbol: Any) -> Optional[ActiveSignal]:
        """Return the current signal record for ``symbol`` (or ``None``)."""
        with self._lock:
            return self._signals.get(self._key(symbol))

    def active(self, symbol: Any) -> Optional[ActiveSignal]:
        """Return the signal record only when it is still live (non-terminal)."""
        record = self.get(symbol)
        if record is not None and record.is_active:
            return record
        return None

    def has_active(self, symbol: Any) -> bool:
        """True when a signal for ``symbol`` is PENDING / EXECUTING / OPEN."""
        return self.active(symbol) is not None

    def in_failure_cooldown(self, symbol: Any) -> bool:
        """True when ``symbol`` is inside the post-failure cooldown window."""
        record = self.get(symbol)
        if record is None or record.phase != SignalPhase.FAILED:
            return False
        elapsed = float(self._clock()) - float(record.updated_at or record.created_at or 0.0)
        return elapsed < self._failure_cooldown_s

    def should_convene(self, symbol: Any) -> tuple[bool, str]:
        """Decide whether the committee should run for ``symbol`` now.

        Returns:
            ``(convene, reason)``. ``convene`` is False when a signal is already
            live (PENDING/EXECUTING/OPEN) or the symbol is in the post-failure
            cooldown — the caller must NOT re-run the committee and must answer
            with the existing signal instead.
        """
        record = self.get(symbol)
        if record is None:
            return True, ""
        if record.is_active:
            return False, (
                f"sinyal {record.direction} untuk {record.symbol} masih aktif "
                f"({record.phase}); tidak perlu rapat ulang"
            )
        if record.phase == SignalPhase.FAILED and self.in_failure_cooldown(symbol):
            remaining = int(
                self._failure_cooldown_s
                - (float(self._clock()) - float(record.updated_at or record.created_at or 0.0))
            )
            return False, (
                f"eksekusi sinyal {record.symbol} baru gagal "
                f"({record.reason or 'tidak diketahui'}); "
                f"tunggu {max(remaining, 0)}s sebelum analisa ulang"
            )
        return True, ""

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------
    def open_signal(
        self,
        symbol: Any,
        direction: str,
        *,
        confidence: float = 0.0,
        levels: Optional[dict[str, Any]] = None,
        proposal_id: str = "",
    ) -> ActiveSignal:
        """Create/refresh the PENDING signal for ``symbol``.

        If an identical live signal already exists it is refreshed (confidence
        raised, levels filled) instead of replaced — so re-observing the same
        signal never opens a second one.
        """
        key = self._key(symbol)
        levels = levels if isinstance(levels, dict) else {}
        now = float(self._clock())
        with self._lock:
            existing = self._signals.get(key)
            if existing is not None and existing.is_active and existing.direction == direction:
                existing.confidence = max(existing.confidence, float(confidence or 0.0))
                for name in ("entry", "sl", "tp1", "tp2", "tpmax"):
                    value = _coerce_px(levels.get(name))
                    if value is not None:
                        setattr(existing, name, value)
                existing.updated_at = now
                if proposal_id:
                    existing.proposal_id = str(proposal_id)
                return existing

            record = ActiveSignal(
                symbol=key,
                direction=str(direction or "").upper(),
                phase=SignalPhase.PENDING,
                confidence=float(confidence or 0.0),
                entry=_coerce_px(levels.get("entry")),
                sl=_coerce_px(levels.get("sl")),
                tp1=_coerce_px(levels.get("tp1")),
                tp2=_coerce_px(levels.get("tp2")),
                tpmax=_coerce_px(levels.get("tpmax")),
                proposal_id=str(proposal_id or ""),
                created_at=now,
                updated_at=now,
            )
            self._signals[key] = record
            return record

    def mark_executing(self, symbol: Any, reason: str = "order dikirim") -> Optional[ActiveSignal]:
        """Move the symbol's signal to EXECUTING (order submitted)."""
        return self._transition(symbol, SignalPhase.EXECUTING, reason)

    def mark_open(
        self, symbol: Any, ticket: Any, reason: str = "entry terbuka"
    ) -> Optional[ActiveSignal]:
        """Move the symbol's signal to OPEN (a position is live)."""
        record = self._transition(symbol, SignalPhase.OPEN, reason)
        if record is not None:
            record.ticket = ticket
        return record

    def mark_closed(self, symbol: Any, reason: str = "posisi ditutup") -> Optional[ActiveSignal]:
        """Move the symbol's signal to CLOSED (terminal, clears the gate)."""
        return self._transition(symbol, SignalPhase.CLOSED, reason)

    def mark_failed(self, symbol: Any, reason: str = "eksekusi gagal") -> Optional[ActiveSignal]:
        """Move the symbol's signal to FAILED (terminal + cooldown)."""
        return self._transition(symbol, SignalPhase.FAILED, reason)

    def mark_skipped(
        self, symbol: Any, reason: str = "sinyal tidak layak dieksekusi"
    ) -> Optional[ActiveSignal]:
        """Move the symbol's signal to SKIPPED (terminal)."""
        return self._transition(symbol, SignalPhase.SKIPPED, reason)

    def clear(self, symbol: Any) -> None:
        """Forget the signal record for ``symbol`` entirely."""
        key = self._key(symbol)
        with self._lock:
            self._signals.pop(key, None)

    def reset(self) -> None:
        """Drop every tracked signal (tests / explicit reset)."""
        with self._lock:
            self._signals.clear()

    def snapshot(self) -> list[dict[str, Any]]:
        """Return a list of every tracked signal (for diagnostics/UI)."""
        with self._lock:
            return [record.to_dict() for record in self._signals.values()]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    def _transition(self, symbol: Any, phase: str, reason: str) -> Optional[ActiveSignal]:
        key = self._key(symbol)
        now = float(self._clock())
        with self._lock:
            record = self._signals.get(key)
            if record is None:
                # A transition without a prior open is only meaningful for
                # terminal states observed from the outside (e.g. a close for a
                # position we did not open); ignore it rather than invent state.
                return None
            record.phase = phase
            record.reason = str(reason or "")
            record.updated_at = now
            return record


# ---------------------------------------------------------------------------
# Process-wide singleton (shared via a builtins slot)
# ---------------------------------------------------------------------------
def get_signal_registry() -> SignalRegistry:
    """Return the process-wide :class:`SignalRegistry` (creating it lazily)."""
    registry = getattr(builtins, _SLOT, None)
    if registry is None:
        registry = SignalRegistry()
        setattr(builtins, _SLOT, registry)
    return registry


def set_signal_registry(registry: Optional[SignalRegistry]) -> None:
    """Attach a specific registry (mainly for tests). ``None`` detaches."""
    if registry is None:
        if hasattr(builtins, _SLOT):
            delattr(builtins, _SLOT)
    else:
        setattr(builtins, _SLOT, registry)


def reset_signal_registry() -> None:
    """Replace the process-wide registry with a fresh one (tests)."""
    set_signal_registry(SignalRegistry())


# Environment knob: master switch for the "don't re-convene while a signal is
# live" gate. Default ON; set SIGNAL_PENDING_GUARD=false to disable.
def is_pending_guard_enabled() -> bool:
    """Whether the pipeline should skip re-analysis while a signal is live."""
    value = os.getenv("SIGNAL_PENDING_GUARD", "true").strip().lower()
    return value not in ("0", "false", "no", "off")
