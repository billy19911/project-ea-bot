# -*- coding: utf-8 -*-
"""Production Certification Gate — PRD_V2 §50.

The final gate before live. Aggregates five checklists (A–E) and derives a
**deterministic** production status from them. No LLM and no human opinion can
change the status — it is a pure function of the checklist results.

Gates (PRD §50)::

    Gate A — Engineering   (python/node tests, web build, type check, lint, security)
    Gate B — Trading Safety (risk gate, kill switch, breaker, dup prevention, spec,
                             reconciliation, recovery)
    Gate C — Research       (backtest, walk-forward, monte carlo, sensitivity, sample)
    Gate D — Operational    (mt5 restart, pc restart, mt5 disconnect, db fail, llm fail,
                             9router fail, telegram fail)
    Gate E — Forward        (paper, demo, monitoring, execution quality, no critical incident)

Status (PRD §50)::

    NOT_READY → READY_FOR_PAPER → READY_FOR_DEMO → READY_FOR_SMALL_LIVE
              → PRODUCTION            (HALTED if a critical unresolved incident)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

__all__ = [
    "ProductionStatus",
    "GateResult",
    "CertificationReport",
    "ProductionCertificationGate",
    "GATE_A_CHECKS",
    "GATE_B_CHECKS",
    "GATE_C_CHECKS",
    "GATE_D_CHECKS",
    "GATE_E_CHECKS",
]


class ProductionStatus(str, Enum):
    """Deterministic production readiness statuses (PRD §50)."""

    NOT_READY = "NOT_READY"
    READY_FOR_PAPER = "READY_FOR_PAPER"
    READY_FOR_DEMO = "READY_FOR_DEMO"
    READY_FOR_SMALL_LIVE = "READY_FOR_SMALL_LIVE"
    PRODUCTION = "PRODUCTION"
    HALTED = "HALTED"


# Checklist definitions (PRD §50).
GATE_A_CHECKS: tuple[str, ...] = (
    "python_tests",
    "node_tests",
    "web_build",
    "type_check",
    "lint",
    "security_scan",
)

GATE_B_CHECKS: tuple[str, ...] = (
    "risk_gate",
    "kill_switch",
    "circuit_breaker",
    "duplicate_prevention",
    "broker_spec",
    "reconciliation",
    "recovery",
)

GATE_C_CHECKS: tuple[str, ...] = (
    "backtest",
    "walk_forward",
    "monte_carlo",
    "parameter_sensitivity",
    "sufficient_sample",
)

GATE_D_CHECKS: tuple[str, ...] = (
    "mt5_restart",
    "pc_restart",
    "mt5_disconnect",
    "database_failure",
    "llm_failure",
    "nine_router_failure",
    "telegram_failure",
)

GATE_E_CHECKS: tuple[str, ...] = (
    "paper",
    "demo",
    "monitoring",
    "execution_quality",
    "no_critical_incident",
)


def _gate_checks(gate: str) -> tuple[str, ...]:
    return {
        "A": GATE_A_CHECKS,
        "B": GATE_B_CHECKS,
        "C": GATE_C_CHECKS,
        "D": GATE_D_CHECKS,
        "E": GATE_E_CHECKS,
    }[gate]


@dataclass
class GateResult:
    """Result of a single gate."""

    gate: str
    checks: dict[str, bool | None] = field(default_factory=dict)
    reasons: dict[str, dict[str, str]] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(value is True for value in self.checks.values())

    def failed_checks(self) -> list[str]:
        return [name for name, ok in self.checks.items() if ok is not True]

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate": self.gate,
            "passed": self.passed,
            "checks": dict(self.checks),
            "failed": self.failed_checks(),
            "reasons": dict(self.reasons),
        }


@dataclass
class CertificationReport:
    """Full certification report with a deterministic production status."""

    status: str
    gates: list[GateResult] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "gates": [g.to_dict() for g in self.gates],
            "reasons": list(self.reasons),
        }


class ProductionCertificationGate:
    """Evaluates the five certification gates and derives the status (PRD §50).

    Args:
        gate_results: Mapping ``{"A": {"python_tests": True, ...}, ...}``.
        critical_incident_open: When True the status is forced to HALTED.
    """

    def __init__(
        self,
        gate_results: dict[str, dict[str, bool]] | None = None,
        critical_incident_open: bool = False,
    ) -> None:
        self.gate_results = gate_results or {}
        self.critical_incident_open = critical_incident_open

    @staticmethod
    def _coerce(value: Any) -> bool | None:
        """Normalise a raw evidence value to ``True``/``False``/``None``.

        Only an observed ``True`` counts as passed. An explicit ``False`` is a
        recorded failure; ``None`` (or `"UNKNOWN"`/`"NOT_RUN"`) means *not run*
        — it is never silently promoted to a pass.
        """
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            token = value.strip().upper()
            if token in ("", "UNKNOWN", "NOT_RUN", "NOT RUN", "PENDING"):
                return None
            if token in ("TRUE", "PASS", "PASSED", "OK", "HEALTHY"):
                return True
            if token in ("FALSE", "FAIL", "FAILED", "DOWN", "UNHEALTHY"):
                return False
            return None
        return bool(value)

    def _evaluate_gate(self, gate: str) -> GateResult:
        provided = self.gate_results.get(gate, {})
        checks: dict[str, bool | None] = {}
        reasons: dict[str, dict[str, str]] = {}
        for name in _gate_checks(gate):
            raw = provided.get(name)
            # Support both a bare verdict and a rich ``{value, reason, source}``.
            if isinstance(raw, dict):
                value = self._coerce(raw.get("value"))
                checks[name] = value
                reason = str(raw.get("reason") or "").strip()
                source = str(raw.get("evidence_source") or raw.get("source") or "").strip()
                if reason or source:
                    reasons[name] = {"reason": reason, "evidence_source": source}
            else:
                checks[name] = self._coerce(raw)
        return GateResult(gate=gate, checks=checks, reasons=reasons)

    def evaluate(self) -> CertificationReport:
        """Return the deterministic certification report (PRD §50)."""
        gates = [self._evaluate_gate(g) for g in ("A", "B", "C", "D", "E")]
        by_gate = {g.gate: g for g in gates}
        reasons: list[str] = []

        # HALTED dominates everything.
        if self.critical_incident_open:
            reasons.append("unresolved critical incident — system HALTED")
            return CertificationReport(
                status=ProductionStatus.HALTED.value, gates=gates, reasons=reasons
            )

        a, b, c, d, e = (by_gate[k].passed for k in ("A", "B", "C", "D", "E"))

        if not (a and b):
            reasons.append("engineering/trading-safety gates not passed")
            return CertificationReport(
                status=ProductionStatus.NOT_READY.value, gates=gates, reasons=reasons
            )

        # Engineering + safety pass. Progressively unlock research → forward.
        if not c:
            reasons.append("research gate not passed — eligible for paper")
            return CertificationReport(
                status=ProductionStatus.READY_FOR_PAPER.value, gates=gates, reasons=reasons
            )

        # Research passed but forward (paper/demo) not yet complete.
        if not (d and e):
            reasons.append("operational/forward gates not passed — eligible for demo")
            return CertificationReport(
                status=ProductionStatus.READY_FOR_DEMO.value, gates=gates, reasons=reasons
            )

        # Everything passed → eligible for small live; PRODUCTION requires the
        # explicit demo completion evidence in Gate E which we already have.
        reasons.append("all gates passed — eligible for small live")
        return CertificationReport(
            status=ProductionStatus.READY_FOR_SMALL_LIVE.value, gates=gates, reasons=reasons
        )

    def promote_to_production(self) -> CertificationReport:
        """Promote to PRODUCTION only when all gates pass and no incident open.

        This is deliberately the *only* path to PRODUCTION and it re-checks the
        full checklist — it cannot be forced by a partial success.
        """
        report = self.evaluate()
        if report.status == ProductionStatus.READY_FOR_SMALL_LIVE.value:
            report.status = ProductionStatus.PRODUCTION.value
            report.reasons.append("promoted to PRODUCTION after full gate pass")
        return report
