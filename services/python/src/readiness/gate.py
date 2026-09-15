# -*- coding: utf-8 -*-
"""Live readiness gate orchestration — EPIC 19.

The :class:`LiveReadinessGate` tracks the status of every readiness
gate, blocks LIVE activation until all gates pass, and requires an
exact operator confirmation phrase for activation (19.10).
"""

from __future__ import annotations

from typing import Any, Optional

from .gates import (
    DEFAULT_GATE_NAMES,
    LIVE_CONFIRMATION_PHRASE,
    ActivationBlockedError,
    ActivationRecord,
    GateResult,
    GateStatus,
    ReadinessGate,
)


class LiveReadinessGate:
    """Tracks readiness gates and controls PAPER → LIVE activation.

    Modes:
      * ``PAPER`` — default; trading is simulated.
      * ``LIVE`` — only reachable via :meth:`activate_live` with every
        gate PASSED and the exact confirmation phrase.
    """

    def __init__(self, gate_names: Optional[tuple[str, ...]] = None) -> None:
        self._names: list[str] = list(gate_names or DEFAULT_GATE_NAMES)
        self._results: dict[str, GateResult] = {
            name: GateResult(name=name, status=GateStatus.PENDING) for name in self._names
        }
        self._custom_gates: dict[str, ReadinessGate] = {}
        self._mode: str = "PAPER"
        self._history: list[ActivationRecord] = []

    # ------------------------------------------------------------------
    # Gate management
    # ------------------------------------------------------------------

    def gate_names(self) -> list[str]:
        """Return all gate names (built-in + custom), in registration order."""
        return list(self._results.keys())

    def register(self, gate: ReadinessGate) -> None:
        """Register a custom readiness gate."""
        self._custom_gates[gate.name] = gate
        if gate.name not in self._results:
            self._results[gate.name] = GateResult(name=gate.name, status=GateStatus.PENDING)

    def status(self, name: str) -> GateStatus:
        """Return the current status of a gate."""
        if name not in self._results:
            raise KeyError(f"Unknown gate: {name}")
        return self._results[name].status

    def submit(
        self,
        name: str,
        passed: bool,
        evidence: Optional[dict[str, Any]] = None,
        reason: str = "",
    ) -> GateResult:
        """Submit gate evidence and record PASSED or FAILED.

        Raises:
            KeyError: unknown gate name.
            ValueError: failing submission without evidence or reason.
        """
        if name not in self._results:
            raise KeyError(f"Unknown gate: {name}")
        if not passed and not evidence and not reason:
            raise ValueError("A failing gate submission requires evidence or a reason.")

        result = GateResult(
            name=name,
            status=GateStatus.PASSED if passed else GateStatus.FAILED,
            evidence=evidence or {},
            reason=reason,
        )
        self._results[name] = result
        if not passed:
            self._fail_closed(f"Gate failed while live: {name}")
        return result

    def revoke(self, name: str, reason: str = "") -> GateResult:
        """Revoke a previously passed gate — back to PENDING."""
        if name not in self._results:
            raise KeyError(f"Unknown gate: {name}")
        result = GateResult(name=name, status=GateStatus.PENDING, reason=reason)
        self._results[name] = result
        self._fail_closed(f"Gate revoked while live: {name}")
        return result

    def _fail_closed(self, reason: str) -> None:
        """Drop LIVE back to PAPER when a gate regresses (fail-closed)."""
        if self._mode != "LIVE":
            return
        self._mode = "PAPER"
        self._history.append(
            ActivationRecord(activated=False, activated_by="system", reason=reason)
        )

    # ------------------------------------------------------------------
    # Readiness & activation
    # ------------------------------------------------------------------

    @property
    def mode(self) -> str:
        """Current operating mode: PAPER or LIVE."""
        return self._mode

    @property
    def is_live(self) -> bool:
        """True only when LIVE has been explicitly activated."""
        return self._mode == "LIVE"

    def blockers(self) -> list[str]:
        """Names of gates that are not PASSED."""
        return [
            name for name, result in self._results.items() if result.status != GateStatus.PASSED
        ]

    def is_ready(self) -> bool:
        """True when every gate has PASSED."""
        return not self.blockers()

    def report(self) -> dict[str, Any]:
        """Return a readiness summary (does not activate anything)."""
        passed = sum(1 for r in self._results.values() if r.status == GateStatus.PASSED)
        return {
            "ready": self.is_ready(),
            "passed": passed,
            "total": len(self._results),
            "blockers": self.blockers(),
            "mode": self._mode,
            "gates": {name: r.status.value for name, r in self._results.items()},
        }

    def activate_live(
        self,
        confirmation: str,
        activated_by: str = "operator",
    ) -> ActivationRecord:
        """Activate LIVE trading — requires all gates passed + exact phrase.

        Raises:
            ActivationBlockedError: gates not all passed, or the
                confirmation phrase does not match exactly.
        """
        blockers = self.blockers()
        if blockers:
            raise ActivationBlockedError(
                "LIVE activation blocked — gates not passed: " + ", ".join(blockers)
            )
        if confirmation != LIVE_CONFIRMATION_PHRASE:
            raise ActivationBlockedError(
                "LIVE activation blocked — confirmation phrase mismatch. "
                f"Expected exactly: {LIVE_CONFIRMATION_PHRASE!r}"
            )

        record = ActivationRecord(
            activated=True,
            activated_by=activated_by,
            reason="All gates passed; confirmation phrase verified.",
        )
        self._mode = "LIVE"
        self._history.append(record)
        return record

    def deactivate_live(self, reason: str = "operator stop") -> ActivationRecord:
        """Return to PAPER mode."""
        record = ActivationRecord(
            activated=False,
            activated_by="operator",
            reason=reason,
        )
        self._mode = "PAPER"
        self._history.append(record)
        return record

    def history(self) -> list[ActivationRecord]:
        """Return activation/deactivation history."""
        return list(self._history)
