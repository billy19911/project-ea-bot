# -*- coding: utf-8 -*-
"""Observability Dashboard 2.0 — PRD_V2 §49.

Aggregates the 16 dashboard sections into a single payload, enforcing the
*no fake zeros* principle: when a backend has no data, the dashboard must say
``No data`` / ``Unavailable`` / ``Not configured`` / ``Insufficient sample`` —
never present an empty value as ``0%`` / ``0 trades`` / ``NORMAL`` / ``HEALTHY``.

Sections (PRD §49)::

    1 Overview   2 Market    3 Positions   4 Orders
    5 Agents     6 Supervisor 7 Risk       8 Reconciliation
    9 Learning   10 Research 11 Strategies 12 Execution Quality
    13 Observability 14 System Health 15 Audit/Decision Replay 16 Settings
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

__all__ = [
    "SECTIONS",
    "SectionPayload",
    "DashboardAggregator",
    "NO_DATA",
    "UNAVAILABLE",
    "NOT_CONFIGURED",
    "INSUFFICIENT_SAMPLE",
]

NO_DATA = "No data"
UNAVAILABLE = "Unavailable"
NOT_CONFIGURED = "Not configured"
INSUFFICIENT_SAMPLE = "Insufficient sample"

# The 16 dashboard sections in order (PRD §49).
SECTIONS: tuple[str, ...] = (
    "overview",
    "market",
    "positions",
    "orders",
    "agents",
    "supervisor",
    "risk",
    "reconciliation",
    "learning",
    "research",
    "strategies",
    "execution_quality",
    "observability",
    "system_health",
    "audit_replay",
    "settings",
)


@dataclass
class SectionPayload:
    """A single dashboard section payload."""

    section: str
    available: bool
    value: Any = None
    status: str = ""
    detail: str = ""
    advisory: bool = True

    def to_dict(self) -> dict[str, Any]:
        if not self.available:
            return {
                "section": self.section,
                "available": False,
                "status": self.status or NO_DATA,
                "detail": self.detail,
            }
        return {
            "section": self.section,
            "available": True,
            "value": self.value,
            "status": self.status,
            "advisory": self.advisory,
        }


@dataclass
class DashboardAggregator:
    """Builds the full dashboard payload from injected section providers.

    Each provider is a callable returning either:
    * a value (section available), or
    * ``None`` (section unavailable → rendered as "No data"/"Not configured").
    """

    providers: dict[str, Callable[[], Any]] = field(default_factory=dict)

    def _build_section(self, section: str) -> SectionPayload:
        provider = self.providers.get(section)
        if provider is None:
            return SectionPayload(
                section=section,
                available=False,
                status=NOT_CONFIGURED,
                detail=f"{section} provider is not configured",
            )
        try:
            value = provider()
        except Exception as exc:  # noqa: BLE001 - dashboard must never crash
            return SectionPayload(
                section=section,
                available=False,
                status=UNAVAILABLE,
                detail=f"{section} failed: {type(exc).__name__}",
            )
        if value is None:
            return SectionPayload(
                section=section,
                available=False,
                status=NO_DATA,
                detail=f"{section} has no data yet",
            )
        return SectionPayload(section=section, available=True, value=value)

    def build(self) -> dict[str, Any]:
        """Return the full dashboard payload for all 16 sections."""
        sections = [self._build_section(name).to_dict() for name in SECTIONS]
        return {"sections": sections, "count": len(sections)}

    def section(self, name: str) -> Optional[dict[str, Any]]:
        if name not in SECTIONS:
            return None
        return self._build_section(name).to_dict()
