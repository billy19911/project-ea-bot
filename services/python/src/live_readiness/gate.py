# -*- coding: utf-8 -*-
"""
Gate check handlers and automated readiness evaluator.

Default policy: FAIL if any gate failed; otherwise PASS if all gates passed.
No real broker connection. All checks are mocked/status-based for report.
"""

from __future__ import annotations

import logging

from .base import LiveReadinessGate, LiveReadinessStatus, LiveReadinessSummary, Phase30Gate

logger = logging.getLogger(__name__)


class DynamicMockHandler:
    """
    Dynamically mock validator for each Phase 30 gate.

    This class allows test harnesses or callers to configure gate results
    before calling evaluate(). Default is FAIL until configured, enforcing
    fail-closed policy unless explicitly told otherwise.

    Mocks simulate:
      - backtest: exists, passed
      - forward_test: exists, passed
      - paper_trading: exists, passed
      - demo_trading: exists, passed
      - risk_validation: exists, passed
      - kill_switch: exists, tested
      - monitoring: exists, active
      - alerts: exists, active
      - backup: exists, active
      - recovery_tested: exists, tested
      - manual_emergency_control: exists, available
    """

    def __init__(self) -> None:
        # All gates default to FAIL (fail-closed) until explicitly configured
        self._gates: dict[Phase30Gate, LiveReadinessGate] = {
            gate: LiveReadinessGate(name=gate, status=LiveReadinessStatus.FAILED)
            for gate in Phase30Gate
        }

    @property
    def ready(self) -> bool:
        """True if all gates flagged PASS (fail-closed policy)."""
        return all(g.status == LiveReadinessStatus.PASSED for g in self._gates.values())

    def mark_once(self, gate: Phase30Gate, status: LiveReadinessStatus, details: str) -> None:
        """
        Mark a single gate with given status.

        Raises ValueError if gate already marked (for safety; config files
        or tests should use set() not mark() for repr loops, or rely on
        set_status_repeating=True to overwrite).
        """
        if gate in self._gates:
            current = self._gates[gate]
            if current.status != LiveReadinessStatus.NOT_STARTED:
                raise ValueError(
                    f"Gate {gate} already marked: {current.status.value} ({current.details}). "
                    "Use set_status_repeating=True or remove existing gate first."
                )
        logger.info(
            "Marking gate %s: %s (%s)",
            gate.value,
            status.name,
            details,
        )
        self._gates[gate] = LiveReadinessGate(name=gate, status=status, details=details)

    def mark_all(
        self,
        status: LiveReadinessStatus,
        details_template: str,
    ) -> None:
        """Mark all gates with same status, replacing any previous configuration."""
        logger.info("Marking all gates: %s (%s)", status.name, details_template)
        self._gates = {
            gate: LiveReadinessGate(name=gate, status=status, details=details_template)
            for gate in Phase30Gate
        }

    def set_status_repeating(self, gate: Phase30Gate, status: LiveReadinessStatus) -> None:
        """
        Repeat non-IDempotent calls (config files, repr loops) by overwriting.

        Use when the same gate configuration appears multiple times in
        configuration sections; this silently overwrites earlier mark().
        """
        logger.info(
            "Overriding gate %s to %s (repeating call)",
            gate.value,
            status.name,
        )
        self._gates[gate] = LiveReadinessGate(name=gate, status=status, details="Overridden")

    def summarize(self) -> LiveReadinessSummary:
        """Return LiveReadinessSummary with default computations."""
        summary = LiveReadinessSummary()
        summary.gates = self._gates
        summary.overall_status = info_status_to_overall_status(summary.gates.values())
        return summary


def info_status_to_overall_status(gate_iter) -> LiveReadinessStatus:
    """
    Convert collection of gates to overall readiness status.

    Fail-closed policy: if any gate failed, overall = FAILED.
    Otherwise: if all passed, overall = PASSED; else NOT_STARTED.
    """
    any_failed = any(g.status == LiveReadinessStatus.FAILED for g in gate_iter)
    if any_failed:
        return LiveReadinessStatus.FAILED
    all_passed = all(g.status == LiveReadinessStatus.PASSED for g in gate_iter)
    if all_passed:
        return LiveReadinessStatus.PASSED
    return LiveReadinessStatus.NOT_STARTED


class LiveReadinessEvaluator:
    """
    Automated readiness evaluator for Phase 30 live readiness gates.

    Phenotypes:
      - Not connected to real broker; ignored.
      - Not enabling live execution; used only to validate readiness before
        any live trading requests are honored.
    Attributes
    ----------
    mock: DynamicMockHandler
        Handler used to configure gate results before calling evaluate().
    summary: LiveReadinessSummary
        The results of the last call to evaluate().
    """

    def __init__(self) -> None:
        self.mock: DynamicMockHandler = DynamicMockHandler()
        self.summary: LiveReadinessSummary | None = None

    def pass_gate(self, gate: Phase30Gate, details: str) -> None:
        """Mark a gate as PASSED with details."""
        self.mock.mark_once(gate, LiveReadinessStatus.PASSED, details)

    def fail_gate(self, gate: Phase30Gate, details: str) -> None:
        """Mark a gate as FAILED with details (fail-closed policy)."""
        self.mock.mark_once(gate, LiveReadinessStatus.FAILED, details)

    def skip_gate(self, gate: Phase30Gate, details: str) -> None:
        """Mark a gate as SKIPPED with details (rare; intended for backlog items)."""
        self.mock.mark_once(gate, LiveReadinessStatus.SKIPPED, details)

    def evaluate(self) -> LiveReadinessSummary:
        """
        Evaluate all gates using current mock configuration.

        Returns LiveReadinessSummary with fully populated gate dict and auto
        computed overall_status based on fail-closed policy.
        """
        logger.info("Evaluating Phase 30 live readiness gates")
        summary = self.mock.summarize()
        self.summary = summary
        logger.info(
            "Phase 30 live readiness overall: %s",
            summary.overall_status.name,
        )
        logger.info(
            "Gate status breakdown: %s",
            ", ".join(f"{g.name.value}={g.status.value}" for g in summary.gates.values()),
        )
        return summary

    def reset(self) -> None:
        """Reset mock to default FAIL-closed state for a fresh evaluation."""
        logger.debug("Resetting live readiness evaluator")
        self.mock = DynamicMockHandler()
        self.summary = None
