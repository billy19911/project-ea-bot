# -*- coding: utf-8 -*-
"""Department hierarchy for the AI organization.

A Department Lead is an AI orchestration role. It selects the relevant
specialists for an assigned task, aggregates their structured outputs, and
returns a department-level assessment. It cannot access MT5, Risk Gate, or
Execution Engine.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .base import AgentPriority, BaseAgent


def _record_specialist_activity(
    name: str, signal: str, confidence: float, error: bool = False
) -> None:
    """Best-effort realtime activity record for a specialist (fail-safe)."""
    try:
        from .activity import get_activity_tracker

        get_activity_tracker().record(name, signal, confidence, error=error)
    except Exception:  # noqa: BLE001 - metrics must never break analysis
        pass


@dataclass
class Department:
    """Named group of specialists owned by one department lead."""

    name: str
    display_name: str
    description: str
    specialists: list[BaseAgent] = field(default_factory=list)

    def add_specialist(self, specialist: BaseAgent) -> None:
        """Register one specialist, rejecting duplicate names."""
        if self.get_specialist(specialist.name) is not None:
            raise ValueError(f"Specialist '{specialist.name}' already belongs to '{self.name}'")
        self.specialists.append(specialist)

    def remove_specialist(self, name: str) -> None:
        """Remove a specialist by name; no-op when it is absent."""
        self.specialists = [
            specialist for specialist in self.specialists if specialist.name != name
        ]

    def get_specialist(self, name: str) -> BaseAgent | None:
        """Return a specialist by name."""
        return next(
            (specialist for specialist in self.specialists if specialist.name == name), None
        )


RoutingFunction = Callable[[dict[str, Any]], list[str]]


class DepartmentLead(BaseAgent):
    """Select, run, and synthesize only the specialists relevant to one task."""

    def __init__(
        self,
        department: Department,
        name: str,
        routing_fn: RoutingFunction | None = None,
        description: str = "",
    ) -> None:
        super().__init__(
            name=name,
            agent_type="department_lead",
            description=description or f"Lead for {department.display_name}",
            priority=AgentPriority.HIGH,
        )
        self.department = department
        self.routing_fn = routing_fn

    def select_specialists(self, context: dict[str, Any]) -> list[BaseAgent]:
        """Select the explicit or policy-routed specialists for this task."""
        if self.routing_fn is not None:
            requested_names = self.routing_fn(context)
        else:
            requested_names = context.get("required_specialists")

        if requested_names is None:
            return []

        return [
            specialist
            for name in requested_names
            if (specialist := self.department.get_specialist(name)) is not None
        ]

    def analyze(self, context: dict[str, Any]) -> dict[str, Any]:
        """Run selected specialists and return structured department evidence.

        Conflicting specialist signals never use vote count. They remain
        unresolved and require the Supervisor to request a targeted follow-up
        or choose a safe no-trade action.
        """
        selected = self.select_specialists(context)
        results: dict[str, dict[str, Any]] = {}

        for specialist in selected:
            try:
                result = specialist.analyze(context)
                results[specialist.name] = result
                _record_specialist_activity(
                    specialist.name,
                    str(result.get("signal", "NEUTRAL")),
                    float(result.get("confidence", 0.0) or 0.0),
                    error=False,
                )
            except Exception as exc:  # defensive boundary around specialist failures
                results[specialist.name] = {
                    "agent": specialist.name,
                    "status": "ERROR",
                    "signal": "NEUTRAL",
                    "confidence": 0.0,
                    "reasons": [f"Specialist failed: {exc}"],
                }
                _record_specialist_activity(specialist.name, "NEUTRAL", 0.0, error=True)

        consensus_signal, unresolved_conflict = self._resolve_consensus(results)
        return {
            "agent": self.name,
            "role": "department_lead",
            "department": self.department.name,
            "specialist_results": results,
            "consensus_signal": consensus_signal,
            "unresolved_conflict": unresolved_conflict,
            "selected_specialists": [specialist.name for specialist in selected],
        }

    @staticmethod
    def _resolve_consensus(results: dict[str, dict[str, Any]]) -> tuple[str, bool]:
        """Resolve only unanimous non-neutral findings; never majority-vote."""
        signals = {
            str(result.get("signal", "NEUTRAL"))
            for result in results.values()
            if result.get("status") != "ERROR" and result.get("signal") not in (None, "NEUTRAL")
        }
        if len(signals) == 1:
            return signals.pop(), False
        if len(signals) > 1:
            return "UNRESOLVED", True
        return "NEUTRAL", False

    def to_dict(self) -> dict[str, Any]:
        """Include department identity in standard agent metadata."""
        result = super().to_dict()
        result.update({"department": self.department.name, "role": "department_lead"})
        return result
