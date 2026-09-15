# -*- coding: utf-8 -*-
"""Trading Modes — PRD_V2 §23 Trading Modes.

The :class:`TradingModeManager` owns the explicit, auditable operating mode of
the system. Mode transitions are recorded (from/to/reason/timestamp) in a
bounded history so the control plane can always explain the current mode.

Safety rules (fail-safe, stricter-wins):

* ``LIVE`` requires BOTH an explicit confirmation phrase AND a PASSED
  live-readiness gate. The gate logic is *not* duplicated here — the manager
  delegates to :class:`readiness.gate.LiveReadinessGate` (calling
  ``is_ready()`` and ``activate_live()``).
* Downgrades to ``PAPER``/``OFFLINE`` (and ``EMERGENCY_STOP``) are *always*
  allowed, from any mode, so the system can always be made safe.
* A blocked transition is still written to the audit history
  (``allowed=False``) for visibility — never silently dropped.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "TradingMode",
    "TradingModeError",
    "ModeTransitionRecord",
    "TradingModeManager",
]


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class TradingMode(str, Enum):
    """Operating mode of the trading system (PRD_V2 §23).

    The canonical PRD set is: OFFLINE, BACKTEST, PAPER, DEMO, LIVE,
    EMERGENCY_STOP. ``OFF`` is an alias kept for callers that use the terse
    spelling, and ``RESEARCH`` is retained as a research-only mode.
    """

    OFFLINE = "OFFLINE"
    RESEARCH = "RESEARCH"
    BACKTEST = "BACKTEST"
    PAPER = "PAPER"
    DEMO = "DEMO"
    LIVE = "LIVE"
    EMERGENCY_STOP = "EMERGENCY_STOP"
    # Alias.
    OFF = "OFF"


# Modes that are always safe to enter (downgrade / fail-safe). Ordered from the
# safest to the least safe so "downgrade" can be detected.
_SAFE_MODES = {
    TradingMode.EMERGENCY_STOP,
    TradingMode.OFFLINE,
    TradingMode.OFF,
    TradingMode.RESEARCH,
}

# Modes that carry real or simulated-order risk.
_RISKY_MODES = {TradingMode.DEMO, TradingMode.LIVE}


class TradingModeError(RuntimeError):
    """Raised when a mode transition is blocked."""


@dataclass
class ModeTransitionRecord:
    """A single audited mode transition (or blocked attempt)."""

    from_mode: TradingMode
    to_mode: TradingMode
    reason: str = ""
    timestamp: str = field(default_factory=_utcnow)
    allowed: bool = True
    actor: str = "operator"

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_mode": self.from_mode.value,
            "to_mode": self.to_mode.value,
            "reason": self.reason,
            "timestamp": self.timestamp,
            "allowed": self.allowed,
            "actor": self.actor,
        }


class TradingModeManager:
    """Owns and audits the system's trading mode (§23).

    Args:
        initial_mode: Starting mode (default OFFLINE).
        readiness_gate: The :class:`~readiness.gate.LiveReadinessGate` used to
            authorise LIVE. When omitted, LIVE is never allowed.
        history_limit: Maximum number of audit records kept (bounded).
    """

    def __init__(
        self,
        initial_mode: TradingMode = TradingMode.OFFLINE,
        readiness_gate: Optional[Any] = None,
        history_limit: int = 100,
    ) -> None:
        self._mode = initial_mode
        self._gate = readiness_gate
        self._history_limit = max(1, history_limit)
        self._history: list[ModeTransitionRecord] = []

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------
    @property
    def mode(self) -> TradingMode:
        return self._mode

    @property
    def confirmation_phrase(self) -> str:
        """The exact phrase required to enter LIVE.

        Delegated to the readiness gate when available so there is a single
        source of truth (no duplicated phrase literals).
        """
        if self._gate is not None:
            try:
                from readiness.gates import LIVE_CONFIRMATION_PHRASE

                return LIVE_CONFIRMATION_PHRASE
            except Exception:  # pragma: no cover - defensive
                pass
        from readiness.gates import LIVE_CONFIRMATION_PHRASE

        return LIVE_CONFIRMATION_PHRASE

    def history(self) -> list[ModeTransitionRecord]:
        return list(self._history)

    # ------------------------------------------------------------------
    # Transitions
    # ------------------------------------------------------------------
    def transition(
        self,
        to_mode: TradingMode,
        confirmation: str = "",
        reason: str = "",
        actor: str = "operator",
    ) -> ModeTransitionRecord:
        """Attempt a mode transition.

        Args:
            to_mode: Target mode.
            confirmation: Confirmation phrase (required for LIVE).
            reason: Human-readable reason recorded in the audit history.
            actor: Who requested the transition.

        Returns:
            The recorded transition.

        Raises:
            TradingModeError: when the transition is not allowed.
        """
        from_mode = self._mode

        # Fail-safe: downgrades into a safe mode are ALWAYS allowed.
        if to_mode in _SAFE_MODES:
            return self._commit(from_mode, to_mode, reason, actor, allowed=True)

        # LIVE is the only mode with hard preconditions.
        if to_mode is TradingMode.LIVE:
            return self._enter_live(from_mode, confirmation, reason, actor)

        # Other non-safe transitions (e.g. PAPER, DEMO, BACKTEST) are permitted.
        return self._commit(from_mode, to_mode, reason, actor, allowed=True)

    def force_downgrade(
        self,
        to_mode: TradingMode = TradingMode.PAPER,
        reason: str = "forced downgrade",
        actor: str = "system",
    ) -> ModeTransitionRecord:
        """Force a downgrade to a safe mode — never blocked (fail-safe)."""
        if to_mode not in _SAFE_MODES and to_mode not in (
            TradingMode.PAPER,
            TradingMode.BACKTEST,
        ):
            # Only ever downgrade — refuse to *raise* the mode here.
            raise TradingModeError(
                f"force_downgrade cannot enter {to_mode.value}; use transition()"
            )
        record = self._commit(self._mode, to_mode, reason, actor, allowed=True)
        logger.warning("Trading mode forced to %s: %s", to_mode.value, reason)
        return record

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _enter_live(
        self,
        from_mode: TradingMode,
        confirmation: str,
        reason: str,
        actor: str,
    ) -> ModeTransitionRecord:
        # 1. Readiness gate — must be present and PASSED.
        if self._gate is None or not self._readiness_ok():
            self._record_blocked(from_mode, TradingMode.LIVE, reason, actor)
            raise TradingModeError(
                "LIVE transition blocked — readiness gate not PASSED " "(PRD_V2 §23/§19.10)."
            )

        # 2. Confirmation phrase — exact match required.
        if confirmation != self.confirmation_phrase:
            self._record_blocked(from_mode, TradingMode.LIVE, reason, actor)
            raise TradingModeError("LIVE transition blocked — confirmation phrase mismatch.")

        # 3. Delegate the actual activation to the readiness gate (single source
        #    of truth; the manager does not reimplement gate logic).
        if self._gate is not None and hasattr(self._gate, "activate_live"):
            try:
                self._gate.activate_live(confirmation=confirmation, activated_by=actor)
            except Exception as exc:  # ActivationBlockedError → fail closed
                self._record_blocked(from_mode, TradingMode.LIVE, reason, actor)
                raise TradingModeError(f"LIVE transition blocked — {exc}") from exc

        return self._commit(from_mode, TradingMode.LIVE, reason, actor, allowed=True)

    def _readiness_ok(self) -> bool:
        if self._gate is None:
            return False
        if hasattr(self._gate, "is_ready"):
            return bool(self._gate.is_ready())
        return False

    def _commit(
        self,
        from_mode: TradingMode,
        to_mode: TradingMode,
        reason: str,
        actor: str,
        allowed: bool,
    ) -> ModeTransitionRecord:
        record = ModeTransitionRecord(
            from_mode=from_mode,
            to_mode=to_mode,
            reason=reason,
            allowed=allowed,
            actor=actor,
        )
        self._mode = to_mode
        self._append(record)
        logger.info(
            "Trading mode %s → %s (reason=%s, actor=%s)",
            from_mode.value,
            to_mode.value,
            reason,
            actor,
        )
        return record

    def _record_blocked(
        self,
        from_mode: TradingMode,
        to_mode: TradingMode,
        reason: str,
        actor: str,
    ) -> None:
        self._append(
            ModeTransitionRecord(
                from_mode=from_mode,
                to_mode=to_mode,
                reason=reason,
                allowed=False,
                actor=actor,
            )
        )

    def _append(self, record: ModeTransitionRecord) -> None:
        self._history.append(record)
        if len(self._history) > self._history_limit:
            self._history = self._history[-self._history_limit :]
