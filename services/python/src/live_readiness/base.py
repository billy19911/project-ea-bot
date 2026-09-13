# -*- coding: utf-8 -*-
"""Data models and enums for live readiness evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto


class LiveReadinessStatus(Enum):
    """Status of a single gate or overall readiness."""

    NOT_STARTED = auto()
    PASSED = auto()
    FAILED = auto()
    SKIPPED = auto()


class Phase30Gate(Enum):
    """All gates required for Phase 30 live readiness."""

    BACKTEST = "backtest"
    FORWARD_TEST = "forward_test"
    PAPER_TRADING = "paper_trading"
    DEMO_TRADING = "demo_trading"
    RISK_VALIDATION = "risk_validation"
    KILL_SWITCH = "kill_switch"
    MONITORING = "monitoring"
    ALERTS = "alerts"
    BACKUP = "backup"
    RECOVERY_TESTED = "recovery_tested"
    MANUAL_EMERGENCY_CONTROL = "manual_emergency_control"


@dataclass
class LiveReadinessGate:
    """Result of evaluating a single gate."""

    name: Phase30Gate
    status: LiveReadinessStatus = LiveReadinessStatus.NOT_STARTED
    details: str = field(default_factory=str)


@dataclass
class LiveReadinessSummary:
    """Summary of all gate evaluations."""

    gates: dict[Phase30Gate, LiveReadinessGate] = field(default_factory=dict)
    overall_status: LiveReadinessStatus = LiveReadinessStatus.NOT_STARTED

    def __post_init__(self) -> None:
        """Initialize all gates to NOT_STARTED if not provided."""
        for gate in Phase30Gate:
            if gate not in self.gates:
                self.gates[gate] = LiveReadinessGate(name=gate)

    def evaluate_overall(self) -> LiveReadinessStatus:
        """Compute overall status with fail-closed policy."""
        any_failed = any(g.status == LiveReadinessStatus.FAILED for g in self.gates.values())
        if any_failed:
            return LiveReadinessStatus.FAILED
        all_passed = all(g.status == LiveReadinessStatus.PASSED for g in self.gates.values())
        if all_passed:
            return LiveReadinessStatus.PASSED
        return LiveReadinessStatus.NOT_STARTED
