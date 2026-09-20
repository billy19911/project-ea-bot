# -*- coding: utf-8 -*-
"""Multi-Level Circuit Breaker & Capital Preservation — PRD_V2 §36.

Upgrades the binary kill switch into a *layered* control with six states:

    NORMAL → CAUTION → RISK_REDUCED → ENTRY_BLOCKED → EMERGENCY_FLATTEN → HALTED

Design rules (PRD §36):

* Every transition carries a machine-readable *reason* and trigger source.
* Critical states (ENTRY_BLOCKED / EMERGENCY_FLATTEN / HALTED) are **latched**:
  they do not clear on their own — an explicit recovery condition must pass.
* No LLM (or any agent) can override or reset a latched state: reset requires a
  deterministic recovery condition supplied by the operator/system.
* The current state + trigger + reason are exposed for the dashboard/Telegram.

The module is *pure and deterministic*: it never calls MT5 and never uses an
LLM. It only evaluates injected condition signals against a fixed policy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Optional

__all__ = [
    "BreakerLevel",
    "TriggerType",
    "LevelRecord",
    "MultiLevelBreaker",
]


class BreakerLevel(str, Enum):
    """Ordered operating levels (higher index = more restrictive)."""

    NORMAL = "normal"
    CAUTION = "caution"
    RISK_REDUCED = "risk_reduced"
    ENTRY_BLOCKED = "entry_blocked"
    EMERGENCY_FLATTEN = "emergency_flatten"
    HALTED = "halted"


# Severity order for comparison / latching.
_ORDER = [
    BreakerLevel.NORMAL,
    BreakerLevel.CAUTION,
    BreakerLevel.RISK_REDUCED,
    BreakerLevel.ENTRY_BLOCKED,
    BreakerLevel.EMERGENCY_FLATTEN,
    BreakerLevel.HALTED,
]

# States that latch: they must not auto-clear; an explicit recovery is required.
_LATCHED = {
    BreakerLevel.ENTRY_BLOCKED,
    BreakerLevel.EMERGENCY_FLATTEN,
    BreakerLevel.HALTED,
}


class TriggerType(str, Enum):
    """Recognised trigger categories (PRD §36)."""

    SPREAD_SPIKE = "spread_spike"
    FEED_STALE = "feed_stale"
    MT5_DISCONNECTED = "mt5_disconnected"
    DAILY_LOSS = "daily_loss"
    DRAWDOWN = "drawdown"
    CONSECUTIVE_LOSSES = "consecutive_losses"
    ABNORMAL_ORDER_FREQUENCY = "abnormal_order_frequency"
    RECONCILIATION_MISMATCH = "reconciliation_mismatch"
    EXECUTION_REJECTION_SPIKE = "execution_rejection_spike"
    DATABASE_UNAVAILABLE = "database_unavailable"
    MODEL_FAILURE = "model_failure"
    MANUAL = "manual"
    RECOVERY = "recovery"


# Which level each trigger forces, per policy (PRD §36 "Example policy").
_TRIGGER_LEVEL: dict[TriggerType, BreakerLevel] = {
    TriggerType.SPREAD_SPIKE: BreakerLevel.RISK_REDUCED,
    TriggerType.FEED_STALE: BreakerLevel.CAUTION,
    TriggerType.MT5_DISCONNECTED: BreakerLevel.ENTRY_BLOCKED,
    TriggerType.DAILY_LOSS: BreakerLevel.ENTRY_BLOCKED,
    TriggerType.DRAWDOWN: BreakerLevel.EMERGENCY_FLATTEN,
    TriggerType.CONSECUTIVE_LOSSES: BreakerLevel.RISK_REDUCED,
    TriggerType.ABNORMAL_ORDER_FREQUENCY: BreakerLevel.RISK_REDUCED,
    TriggerType.RECONCILIATION_MISMATCH: BreakerLevel.ENTRY_BLOCKED,
    TriggerType.EXECUTION_REJECTION_SPIKE: BreakerLevel.ENTRY_BLOCKED,
    TriggerType.DATABASE_UNAVAILABLE: BreakerLevel.HALTED,
    TriggerType.MODEL_FAILURE: BreakerLevel.CAUTION,
    TriggerType.MANUAL: BreakerLevel.HALTED,
}


@dataclass(frozen=True)
class LevelRecord:
    """Immutable record of a level transition."""

    from_level: BreakerLevel
    to_level: BreakerLevel
    trigger: TriggerType
    reason: str
    timestamp: str
    source: str = "system"

    def to_dict(self) -> dict[str, Any]:
        return {
            "from": self.from_level.value,
            "to": self.to_level.value,
            "trigger": self.trigger.value,
            "reason": self.reason,
            "timestamp": self.timestamp,
            "source": self.source,
        }


@dataclass
class MultiLevelBreaker:
    """Layered circuit breaker with latching and recovery conditions.

    Args:
        level: Initial level (defaults to NORMAL).
        risk_multiplier: Position-size multiplier applied at RISK_REDUCED.
    """

    level: BreakerLevel = BreakerLevel.NORMAL
    risk_multiplier: float = 0.5
    history: list[LevelRecord] = field(default_factory=list)
    _latched: bool = False
    _current_trigger: Optional[TriggerType] = None
    _current_reason: str = ""
    _since: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------
    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    @property
    def latched(self) -> bool:
        """True when the current state is latched (needs explicit recovery)."""
        return self._latched

    @property
    def current_trigger(self) -> Optional[TriggerType]:
        return self._current_trigger

    @property
    def current_reason(self) -> str:
        return self._current_reason

    # ------------------------------------------------------------------
    # Transition
    # ------------------------------------------------------------------
    def _set(
        self,
        to_level: BreakerLevel,
        trigger: TriggerType,
        reason: str,
        source: str = "system",
    ) -> LevelRecord:
        record = LevelRecord(
            from_level=self.level,
            to_level=to_level,
            trigger=trigger,
            reason=reason,
            timestamp=self._now(),
            source=source,
        )
        self.level = to_level
        self._current_trigger = trigger
        self._current_reason = reason
        self._since = record.timestamp
        self._latched = to_level in _LATCHED
        self.history.append(record)
        return record

    def trigger(
        self,
        trigger: TriggerType,
        reason: str = "",
        source: str = "system",
    ) -> LevelRecord:
        """Raise the level according to the policy for *trigger*.

        Levels only ever *escalate* through this method: a lower-severity
        trigger never silently downgrades a latched higher state.
        """
        target = _TRIGGER_LEVEL.get(trigger, BreakerLevel.CAUTION)
        reason = reason or f"trigger: {trigger.value}"
        # Never downgrade a latched/escalated state via a fresh trigger.
        if _ORDER.index(target) <= _ORDER.index(self.level) and self.latched:
            # Record the observation but keep the (more severe) latched level.
            record = LevelRecord(
                from_level=self.level,
                to_level=self.level,
                trigger=trigger,
                reason=f"observed while latched: {reason}",
                timestamp=self._now(),
                source=source,
            )
            self.history.append(record)
            return record
        if _ORDER.index(target) <= _ORDER.index(self.level):
            # No change in level; still record the trigger for audit.
            record = LevelRecord(
                from_level=self.level,
                to_level=self.level,
                trigger=trigger,
                reason=reason,
                timestamp=self._now(),
                source=source,
            )
            self.history.append(record)
            return record
        return self._set(target, trigger, reason, source)

    def escalate(self, to_level: BreakerLevel, reason: str, source: str = "system") -> LevelRecord:
        """Force a specific (higher) level. Cannot lower the level."""
        if _ORDER.index(to_level) < _ORDER.index(self.level) and self.latched:
            raise RuntimeError("Cannot lower a latched level without recovery.")
        trigger = TriggerType.MANUAL if source != "recovery" else TriggerType.RECOVERY
        return self._set(to_level, trigger, reason, source)

    def recover(
        self,
        condition_ok: bool,
        reason: str = "recovery condition satisfied",
        target: BreakerLevel = BreakerLevel.NORMAL,
    ) -> LevelRecord:
        """Attempt to clear a latched state when a recovery condition passes.

        The *caller* supplies the deterministic recovery condition (e.g. broker
        reconnected, drawdown back within limits). An LLM can never call this
        with a self-asserted truthy value — the condition is evaluated by the
        deterministic risk stack.
        """
        if not condition_ok:
            raise RuntimeError("Recovery refused — recovery condition not met.")
        if _ORDER.index(target) >= _ORDER.index(self.level) and not self.latched:
            # Nothing to recover.
            record = LevelRecord(
                from_level=self.level,
                to_level=self.level,
                trigger=TriggerType.RECOVERY,
                reason=f"no-op recovery: {reason}",
                timestamp=self._now(),
                source="recovery",
            )
            self.history.append(record)
            return record
        return self._set(target, TriggerType.RECOVERY, reason, source="recovery")

    # ------------------------------------------------------------------
    # Policy queries
    # ------------------------------------------------------------------
    def allows_new_entries(self) -> bool:
        """True only when new entries are permitted at the current level."""
        return _ORDER.index(self.level) < _ORDER.index(BreakerLevel.ENTRY_BLOCKED)

    def must_flatten(self) -> bool:
        """True when open positions must be emergency-flattened."""
        return _ORDER.index(self.level) >= _ORDER.index(BreakerLevel.EMERGENCY_FLATTEN)

    def size_multiplier(self) -> float:
        """Position-size multiplier for the current level."""
        if self.level == BreakerLevel.RISK_REDUCED:
            return self.risk_multiplier
        if _ORDER.index(self.level) >= _ORDER.index(BreakerLevel.ENTRY_BLOCKED):
            return 0.0
        return 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level.value,
            "latched": self.latched,
            "trigger": self._current_trigger.value if self._current_trigger else None,
            "reason": self._current_reason,
            "since": self._since,
            "allows_new_entries": self.allows_new_entries(),
            "must_flatten": self.must_flatten(),
            "size_multiplier": self.size_multiplier(),
            "history_count": len(self.history),
            "recent": [r.to_dict() for r in self.history[-5:]],
        }


def level_index(level: BreakerLevel) -> int:
    """Return the severity index of *level* (higher = more restrictive)."""
    return _ORDER.index(level)


# Convenience alias for callers that inject a condition callable.
RecoveryCondition = Callable[[], bool]

# Unused import guard for type checkers / backward-compat.
_ = time if False else None  # noqa: F821  (placeholder to keep imports tidy)
