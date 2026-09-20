# -*- coding: utf-8 -*-
"""Crash / Restart / State Recovery — PRD_V2 § 37.

The system must restart **without losing trading state**. This module provides:

* :class:`CheckpointStore` — atomically persists the nine state domains named in
  the PRD (``system_state``, ``market_state``, ``decision_state``,
  ``order_state``, ``position_state``, ``risk_state``,
  ``circuit_breaker_state``, ``strategy_state``, ``scheduler_state``) to a
  single JSON checkpoint file (tmp+replace, corrupt file degrades safely).
* :class:`RecoveryCoordinator` — runs the deterministic recovery flow:

      START → LOAD CHECKPOINT → CHECK MT5 → QUERY BROKER → RECONCILE
            → RESTORE RISK STATE → RESTORE STRATEGY VERSION
            → RESTORE CIRCUIT BREAKER → READY / DEGRADED / HALTED

Critical rule (PRD §37): a process restart MUST NOT reset daily loss, drawdown,
consecutive losses, halt state, or open-position state. Those fields are
*latched* — :meth:`CheckpointStore.merge_risk_state` refuses to clear them, and
the coordinator carries them through the restart verbatim.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "RecoveryStatus",
    "CheckpointStore",
    "RecoveryCoordinator",
    "LATCHED_RISK_FIELDS",
]

# Risk-state fields that survive a restart — never cleared by recovery.
LATCHED_RISK_FIELDS: tuple[str, ...] = (
    "daily_loss",
    "drawdown",
    "consecutive_losses",
    "halted",
    "halt_reason",
)

# The nine persisted state domains (PRD §37 "Persist").
STATE_DOMAINS: tuple[str, ...] = (
    "system_state",
    "market_state",
    "decision_state",
    "order_state",
    "position_state",
    "risk_state",
    "circuit_breaker_state",
    "strategy_state",
    "scheduler_state",
)


class RecoveryStatus(str, Enum):
    """Outcome of a recovery attempt."""

    READY = "ready"
    DEGRADED = "degraded"
    HALTED = "halted"


@dataclass
class CheckpointStore:
    """Atomic JSON checkpoint of all persisted state domains.

    Missing or corrupt checkpoints degrade to an empty state (never raise).
    """

    path: Optional[str] = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _state: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.path is None:
            base = os.path.dirname(os.path.abspath(__file__))
            self.path = os.path.normpath(os.path.join(base, "..", "..", "checkpoint_state.json"))

    # -- persistence -------------------------------------------------------
    def load(self) -> dict[str, Any]:
        """Load the checkpoint from disk (degrades to empty on error)."""
        with self._lock:
            self._state = {domain: {} for domain in STATE_DOMAINS}
            if not os.path.exists(self.path or ""):
                return self._state
            try:
                with open(self.path, encoding="utf-8") as fh:  # type: ignore[arg-type]
                    raw = json.load(fh)
            except (OSError, ValueError) as exc:
                logger.warning("checkpoint: tidak terbaca (%s) — pakai state kosong", exc)
                return self._state
            if isinstance(raw, dict):
                for domain in STATE_DOMAINS:
                    value = raw.get(domain)
                    if isinstance(value, dict):
                        self._state[domain] = value
            return self._state

    def save(self, state: dict[str, Any]) -> None:
        """Atomically persist *state* (tmp + replace)."""
        with self._lock:
            self._state = {domain: dict(state.get(domain, {})) for domain in STATE_DOMAINS}
            tmp = (self.path or "") + ".tmp"
            try:
                with open(tmp, "w", encoding="utf-8") as fh:
                    json.dump(self._state, fh, indent=2, sort_keys=True)
                os.replace(tmp, self.path)  # type: ignore[arg-type]
            except OSError as exc:
                logger.warning("checkpoint: gagal menulis (%s)", exc)

    def snapshot(self) -> dict[str, Any]:
        """Return a deep-ish copy of the current in-memory state."""
        with self._lock:
            return {domain: dict(self._state.get(domain, {})) for domain in STATE_DOMAINS}

    # -- merge helpers -----------------------------------------------------
    @staticmethod
    def merge_risk_state(
        restored: dict[str, Any],
        incoming: dict[str, Any],
    ) -> dict[str, Any]:
        """Merge a naive incoming risk state onto a restored one.

        Latched fields (see :data:`LATCHED_RISK_FIELDS`) are **protected**:
        if the restored value is more severe (or simply present), the incoming
        value can never *reset* it. A restart therefore never clears daily
        loss / drawdown / consecutive losses / halt.

        Returns a merged dict safe to hand to the risk stack.
        """
        merged = dict(restored)
        for key, value in incoming.items():
            if key in LATCHED_RISK_FIELDS:
                # Keep whichever is present on the restored side; incoming is
                # only allowed to *increase* severity (handled by the risk
                # stack downstream), never to clear it.
                if key not in restored:
                    merged[key] = value
                continue
            merged[key] = value
        return merged


@dataclass
class RecoveryResult:
    """Outcome of :meth:`RecoveryCoordinator.recover`."""

    status: RecoveryStatus
    steps: list[str] = field(default_factory=list)
    halted: bool = False
    degraded: bool = False
    reason: str = ""
    risk_state: dict[str, Any] = field(default_factory=dict)
    open_positions: int = 0
    reconciliation_ok: bool = True
    mt5_connected: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "steps": list(self.steps),
            "halted": self.halted,
            "degraded": self.degraded,
            "reason": self.reason,
            "open_positions": self.open_positions,
            "reconciliation_ok": self.reconciliation_ok,
            "mt5_connected": self.mt5_connected,
            "risk_state": dict(self.risk_state),
        }


@dataclass
class RecoveryCoordinator:
    """Runs the deterministic crash-recovery flow.

    All external effects (MT5 connection, broker query, reconciliation) are
    injected callables so the flow is fully testable without a live terminal.
    """

    store: CheckpointStore
    check_mt5: Callable[[], bool] = field(default=lambda: True)
    query_broker_positions: Callable[[], int] = field(default=lambda: 0)
    reconcile: Callable[[dict[str, Any], int], bool] = field(default=lambda state, positions: True)
    restore_strategy_version: Optional[Callable[[dict[str, Any]], None]] = None
    restore_circuit_breaker: Optional[Callable[[dict[str, Any]], bool]] = None

    def recover(self) -> RecoveryResult:
        """Execute the full recovery flow and return the outcome."""
        steps: list[str] = ["start"]

        # 1. LOAD CHECKPOINT
        state = self.store.load()
        steps.append("load_checkpoint")

        # 2. CHECK MT5 CONNECTION
        mt5_connected = bool(self.check_mt5())
        steps.append("check_mt5")

        # 3. QUERY BROKER
        try:
            open_positions = int(self.query_broker_positions())
        except Exception as exc:  # noqa: BLE001 - broker failures must not crash recovery
            logger.warning("recovery: broker query failed (%s)", exc)
            open_positions = -1
        steps.append("query_broker")

        # 4. RECONCILE — internal vs broker truth.
        reconciliation_ok = False
        if mt5_connected and open_positions >= 0:
            try:
                reconciliation_ok = bool(self.reconcile(state, open_positions))
            except Exception as exc:  # noqa: BLE001
                logger.warning("recovery: reconcile failed (%s)", exc)
                reconciliation_ok = False
        steps.append("reconcile")

        # 5. RESTORE RISK STATE (never clears latched fields).
        risk_state = dict(state.get("risk_state", {}))
        # Restart must NOT clear these — assert them present/guarded.
        for fieldname in LATCHED_RISK_FIELDS:
            risk_state.setdefault(fieldname, 0 if fieldname != "halted" else False)
        steps.append("restore_risk_state")

        # 6. RESTORE STRATEGY VERSION
        if self.restore_strategy_version is not None:
            try:
                self.restore_strategy_version(state.get("strategy_state", {}))
            except Exception as exc:  # noqa: BLE001
                logger.warning("recovery: strategy restore failed (%s)", exc)
        steps.append("restore_strategy_version")

        # 7. RESTORE CIRCUIT BREAKER — a latched/halted breaker stays halted.
        breaker_state = dict(state.get("circuit_breaker_state", {}))
        breaker_ok = True
        if self.restore_circuit_breaker is not None:
            try:
                breaker_ok = bool(self.restore_circuit_breaker(breaker_state))
            except Exception as exc:  # noqa: BLE001
                logger.warning("recovery: breaker restore failed (%s)", exc)
                breaker_ok = False
        steps.append("restore_circuit_breaker")

        # 8. DECIDE STATUS.
        halted = bool(risk_state.get("halted")) or not breaker_ok
        degraded = (not mt5_connected) or (not reconciliation_ok)

        if halted:
            status = RecoveryStatus.HALTED
            reason = risk_state.get("halt_reason") or "halted state carried across restart"
        elif degraded:
            status = RecoveryStatus.DEGRADED
            if not mt5_connected:
                reason = "MT5 not connected after restart"
            else:
                reason = "reconciliation mismatch after restart"
        else:
            status = RecoveryStatus.READY
            reason = "recovered cleanly"

        steps.append("ready" if status is RecoveryStatus.READY else status.value)

        return RecoveryResult(
            status=status,
            steps=steps,
            halted=halted,
            degraded=degraded,
            reason=reason,
            risk_state=risk_state,
            open_positions=max(open_positions, 0),
            reconciliation_ok=reconciliation_ok,
            mt5_connected=mt5_connected,
        )
