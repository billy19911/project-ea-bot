# -*- coding: utf-8 -*-
"""Incident Management — PRD_V2 §55.

Every incident records the full lifecycle the PRD requires::

    incident_id, severity, detected_at, component, trigger,
    system_state, action_taken, recovery_state, resolved_at

Severities (PRD §55)::

    INFO, WARNING, HIGH, CRITICAL, EMERGENCY
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

__all__ = [
    "Severity",
    "Incident",
    "IncidentManager",
]


class Severity(str, Enum):
    """Incident severities (PRD §55)."""

    INFO = "INFO"
    WARNING = "WARNING"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"
    EMERGENCY = "EMERGENCY"


# Ordered for escalation comparisons.
_SEVERITY_ORDER = [
    Severity.INFO,
    Severity.WARNING,
    Severity.HIGH,
    Severity.CRITICAL,
    Severity.EMERGENCY,
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Incident:
    """A single incident record (PRD §55)."""

    incident_id: str
    severity: str
    component: str
    trigger: str
    system_state: str = ""
    action_taken: str = ""
    recovery_state: str = "OPEN"
    detected_at: str = field(default_factory=_now)
    resolved_at: Optional[str] = None
    history: list[dict[str, Any]] = field(default_factory=list)

    def is_open(self) -> bool:
        return self.resolved_at is None

    def severity_index(self) -> int:
        return _SEVERITY_ORDER.index(Severity(self.severity))

    def escalate(self, new_severity: str, reason: str = "", actor: str = "system") -> None:
        """Escalate the incident's severity (never de-escalates)."""
        new = Severity(new_severity)
        if _SEVERITY_ORDER.index(new) > self.severity_index():
            self.severity = new.value
            self.history.append(
                {
                    "action": f"escalated to {new.value}: {reason}",
                    "actor": actor,
                    "timestamp": _now(),
                }
            )

    def record_action(self, action: str, actor: str = "system") -> None:
        self.action_taken = action
        self.history.append({"action": action, "actor": actor, "timestamp": _now()})

    def resolve(self, recovery_state: str = "RESOLVED", actor: str = "system") -> None:
        if self.resolved_at is None:
            self.resolved_at = _now()
        self.recovery_state = recovery_state
        self.history.append(
            {
                "action": f"resolved ({recovery_state})",
                "actor": actor,
                "timestamp": self.resolved_at,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "incident_id": self.incident_id,
            "severity": self.severity,
            "detected_at": self.detected_at,
            "component": self.component,
            "trigger": self.trigger,
            "system_state": self.system_state,
            "action_taken": self.action_taken,
            "recovery_state": self.recovery_state,
            "resolved_at": self.resolved_at,
            "open": self.is_open(),
        }


class IncidentManager:
    """Creates and tracks incidents (PRD §55)."""

    def __init__(self) -> None:
        self._incidents: dict[str, Incident] = {}
        self._order: list[str] = []
        self._counter = 0

    def open(
        self,
        severity: str,
        component: str,
        trigger: str,
        system_state: str = "",
        action_taken: str = "",
    ) -> Incident:
        """Open a new incident."""
        if severity not in {s.value for s in Severity}:
            raise ValueError(f"Unknown severity: {severity}")
        self._counter += 1
        inc = Incident(
            incident_id=f"INC-{self._counter:04d}",
            severity=severity,
            component=component,
            trigger=trigger,
            system_state=system_state,
            action_taken=action_taken,
        )
        self._incidents[inc.incident_id] = inc
        self._order.append(inc.incident_id)
        return inc

    def get(self, incident_id: str) -> Optional[Incident]:
        return self._incidents.get(incident_id)

    def all(self) -> list[Incident]:
        return [self._incidents[i] for i in self._order]

    def open_incidents(self) -> list[Incident]:
        return [i for i in self.all() if i.is_open()]

    def has_critical_open(self) -> bool:
        """True when a CRITICAL/EMERGENCY incident is unresolved.

        Used by the certification gate (Phase 50) to force HALTED.
        """
        for inc in self.open_incidents():
            if inc.severity in (Severity.CRITICAL.value, Severity.EMERGENCY.value):
                return True
        return False

    def by_severity(self, severity: str) -> list[Incident]:
        return [i for i in self.all() if i.severity == severity]
