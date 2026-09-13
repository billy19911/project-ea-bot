# -*- coding: utf-8 -*-
"""Deterministic Phase 30 live-readiness evaluator.

Fail-closed policy:
- Missing evidence = FAILED
- Any FAILED gate = overall FAILED
- All gates PASSED = overall PASSED
- NEVER enables live execution; reporting only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .base import LiveReadinessGate, LiveReadinessStatus, Phase30Gate


@dataclass(frozen=True)
class LiveReadinessReport:
    """Complete readiness report; never enables execution.

    Attributes:
        gates: Per-gate evaluation results.
        status: Overall PASSED only if all gates PASSED.
        blocked_gates: Tuple of gates preventing live readiness.
    """

    gates: dict[Phase30Gate, LiveReadinessGate]
    status: LiveReadinessStatus
    live_execution_enabled: bool = False  # Always False; fail-closed

    @property
    def ready(self) -> bool:
        """True only when every required gate passed."""
        return self.status == LiveReadinessStatus.PASSED

    @property
    def blocked_gates(self) -> tuple[Phase30Gate, ...]:
        """Gates that are FAILED or missing evidence."""
        return tuple(g.name for g in self.gates.values() if g.status != LiveReadinessStatus.PASSED)

    def to_dict(self) -> dict[str, Any]:
        """Serialize report for logging/API without enabling execution."""
        checklist = {}
        for g in self.gates.values():
            checklist[g.name.value] = {
                "status": g.status.name.lower(),
                "details": g.details,
            }
        return {
            "status": self.status.name.lower(),
            "ready": self.ready,
            "live_execution_enabled": self.live_execution_enabled,
            "blocked_gates": [g.value for g in self.blocked_gates],
            "checklist": checklist,
        }

    def render_checklist(self) -> str:
        """Render human-readable checklist; explicitly states BLOCKED."""
        lines = ["Phase 30 Live Readiness Checklist", "=" * 40]
        for gate in Phase30Gate:
            g = self.gates[gate]
            status_str = g.status.name
            detail = f" — {g.details}" if g.details else ""
            lines.append(f"[{status_str}] {gate.value}{detail}")
        if self.ready:
            lines.append("")
            lines.append("LIVE EXECUTION: READY (gates passed)")
        else:
            lines.append("")
            lines.append("LIVE EXECUTION: BLOCKED (gates failed)")
        return "\n".join(lines)


class LiveReadinessEvaluator:
    """Evaluate explicit Phase 30 evidence with fail-closed defaults.

    This evaluator NEVER connects to a broker or enables live trading.
    It only validates that evidence exists for each required gate.
    """

    def __init__(self) -> None:
        self._results: dict[Phase30Gate, LiveReadinessGate] = {}
        self.report: LiveReadinessReport | None = None

    def set_gate(
        self,
        gate: Phase30Gate,
        passed: bool,
        details: str = "",
    ) -> None:
        """Set one gate result. No broker or execution calls occur."""
        status = LiveReadinessStatus.PASSED if passed else LiveReadinessStatus.FAILED
        self._results[gate] = LiveReadinessGate(gate, status, details)

    def evaluate(self) -> LiveReadinessReport:
        """Return a report; missing gates fail closed."""
        gates = {}
        for gate in Phase30Gate:
            if gate in self._results:
                gates[gate] = self._results[gate]
            else:
                gates[gate] = LiveReadinessGate(
                    gate, LiveReadinessStatus.FAILED, "Evidence missing"
                )
        status = (
            LiveReadinessStatus.PASSED
            if all(item.status == LiveReadinessStatus.PASSED for item in gates.values())
            else LiveReadinessStatus.FAILED
        )
        self.report = LiveReadinessReport(gates, status)
        return self.report

    def reset(self) -> None:
        """Clear evidence and return to fail-closed state."""
        self._results.clear()
        self.report = None
