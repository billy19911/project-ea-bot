# -*- coding: utf-8 -*-
"""Live readiness gates — EPIC 19.

Fourteen named gates guard the transition from PAPER to LIVE trading.
A gate can only be PASSED with explicit evidence; LIVE activation
requires every gate PASSED *and* an exact confirmation phrase typed
by an operator (19.10). There is no programmatic bypass.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol, runtime_checkable

LIVE_CONFIRMATION_PHRASE = "ACTIVATE LIVE TRADING"

DEFAULT_GATE_NAMES = (
    "backtest",
    "walk_forward",
    "paper",
    "demo",
    "risk",
    "stability",
    "recovery",
    "observability",
    "security",
    "autonomous_workflow",
    "committee_consensus",
    "learning_safety",
    "telegram_control_plane",
    "provider_discovery",
)


class GateStatus(str, Enum):
    """Status of a readiness gate."""

    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"


class ActivationBlockedError(RuntimeError):
    """Raised when LIVE activation is attempted without full readiness."""


@dataclass(frozen=True)
class GateResult:
    """Immutable record of a gate evaluation."""

    name: str
    status: GateStatus
    evidence: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            object.__setattr__(
                self,
                "timestamp",
                datetime.now(timezone.utc).isoformat(),
            )


@runtime_checkable
class ReadinessGate(Protocol):
    """Protocol for pluggable readiness gates."""

    name: str

    def evaluate(self, context: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
        """Return (passed, evidence)."""
        ...  # pragma: no cover


@dataclass(frozen=True)
class ActivationRecord:
    """Immutable record of a LIVE activation or deactivation."""

    activated: bool
    activated_by: str
    reason: str
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            object.__setattr__(
                self,
                "timestamp",
                datetime.now(timezone.utc).isoformat(),
            )
