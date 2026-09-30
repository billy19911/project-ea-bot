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
    """Threshold-based alerting with dedup (fire once until resolved).

    Phase 8 hardening: history is BOUNDED (no long-run growth) and each rule
    has a re-fire cooldown so an alert storm (1000 identical evaluations)
    cannot exhaust resources — repeat breaches within the cooldown only
    refresh the firing alert's value, never append new history.
    """

    def __init__(self, *, max_history: int = 500, cooldown_s: float = 60.0) -> None:
        self._rules: List[AlertRule] = []
        self._firing: Dict[str, Alert] = {}
        self._history: List[Alert] = []
        self._max_history = max(16, int(max_history))
        self._cooldown_s = max(0.0, float(cooldown_s))
        self._last_fire_ts: Dict[str, float] = {}
        self._suppressed_count: Dict[str, int] = {}

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
        Storm control: a rule that fired within ``cooldown_s`` does not
        re-append history (the firing alert's value is refreshed instead).
        """
        import time

        now = time.time()
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
                last = self._last_fire_ts.get(rule.name, 0.0)
                if self._cooldown_s > 0 and (now - last) < self._cooldown_s:
                    # Storm suppression: still breaching but inside cooldown —
                    # count it, do not grow history.
                    self._suppressed_count[rule.name] = self._suppressed_count.get(rule.name, 0) + 1
                    continue
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
                self._last_fire_ts[rule.name] = now
                self._append_history(alert)
                events.append(alert)
            elif not breaching and firing:
                alert = self._firing.pop(rule.name)
                alert.resolved = True
                self._last_fire_ts[rule.name] = now
                self._append_history(alert)
                events.append(alert)
            elif breaching and firing:
                # Refresh the live value without new history (storm-safe).
                try:
                    self._firing[rule.name].value = value
                except Exception:  # noqa: BLE001 - refresh is best-effort
                    pass
        return events

    def _append_history(self, alert: "Alert") -> None:
        """Append with a hard bound (no unbounded long-run growth)."""
        self._history.append(alert)
        if len(self._history) > self._max_history:
            del self._history[: len(self._history) - self._max_history]

    def suppressed_counts(self) -> Dict[str, int]:
        """Per-rule storm-suppression counters (observability)."""
        return dict(self._suppressed_count)

    def active_alerts(self) -> List[Alert]:
        return list(self._firing.values())

    def history(self, limit: Optional[int] = None) -> List[Alert]:
        return self._history[-limit:] if limit else list(self._history)

    def clear(self) -> None:
        self._firing.clear()
        self._history.clear()
