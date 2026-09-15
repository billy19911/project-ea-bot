# -*- coding: utf-8 -*-
"""Alerting for observability — EPIC 16.10.

Rule-based threshold alerts with dedup and auto-resolve.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional


class AlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


_VALID_SEVERITIES = {s.value for s in AlertSeverity}


@dataclass
class AlertRule:
    name: str
    metric: str
    threshold: float
    comparison: str = "above"  # above | below
    severity: str = "warning"
    description: str = ""


@dataclass
class Alert:
    name: str
    metric: str
    value: float
    threshold: float
    severity: AlertSeverity
    message: str = ""
    resolved: bool = False


class AlertManager:
    """Threshold-based alerting with dedup (fire once until resolved)."""

    def __init__(self) -> None:
        self._rules: List[AlertRule] = []
        self._firing: Dict[str, Alert] = {}
        self._history: List[Alert] = []

    def add_rule(
        self,
        name: str,
        metric: str,
        threshold: float,
        comparison: str = "above",
        severity: str = "warning",
        description: str = "",
    ) -> None:
        if severity not in _VALID_SEVERITIES:
            raise ValueError(
                f"Invalid severity '{severity}'; must be one of {sorted(_VALID_SEVERITIES)}"
            )
        if comparison not in ("above", "below"):
            raise ValueError("comparison must be 'above' or 'below'")
        self._rules.append(
            AlertRule(
                name=name,
                metric=metric,
                threshold=threshold,
                comparison=comparison,
                severity=severity,
                description=description,
            )
        )

    def evaluate(self, metrics: Dict[str, float]) -> List[Alert]:
        """Evaluate all rules against current metric values.

        Returns alerts that newly fired or resolved in this evaluation.
        """
        events: List[Alert] = []
        for rule in self._rules:
            if rule.metric not in metrics:
                continue
            value = metrics[rule.metric]
            breaching = (
                value > rule.threshold if rule.comparison == "above" else value < rule.threshold
            )
            firing = rule.name in self._firing

            if breaching and not firing:
                alert = Alert(
                    name=rule.name,
                    metric=rule.metric,
                    value=value,
                    threshold=rule.threshold,
                    severity=AlertSeverity(rule.severity),
                    message=rule.description
                    or f"{rule.metric} {rule.comparison} threshold {rule.threshold}",
                )
                self._firing[rule.name] = alert
                self._history.append(alert)
                events.append(alert)
            elif not breaching and firing:
                alert = self._firing.pop(rule.name)
                alert.resolved = True
                self._history.append(alert)
                events.append(alert)
        return events

    def active_alerts(self) -> List[Alert]:
        return list(self._firing.values())

    def history(self, limit: Optional[int] = None) -> List[Alert]:
        return self._history[-limit:] if limit else list(self._history)

    def clear(self) -> None:
        self._firing.clear()
        self._history.clear()
