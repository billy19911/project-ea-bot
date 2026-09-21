# -*- coding: utf-8 -*-
"""Agent Activity Tracker — realtime per-agent runtime metrics.

The dashboard previously showed a `priority` that is the same enum value (75)
for every analyst, which reads like a dummy column. This tracker records *real*
runtime activity so the AI Control page can show meaningful, live numbers:

* ``invocations`` — how many times the agent has run this session,
* ``last_active`` — ISO timestamp of the last run,
* ``signals`` — counts per signal direction (BULLISH/BEARISH/NEUTRAL/...),
* ``avg_confidence`` — mean confidence of its recent outputs,
* ``errors`` — how many runs raised.

Design: a bounded ring per agent, thread-safe, fail-safe (never raises into the
analyst path). Advisory/observability only — it never influences a signal.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

__all__ = ["AgentActivity", "AgentActivityTracker", "get_activity_tracker"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AgentActivity:
    """Rolling runtime activity for one agent."""

    name: str
    invocations: int = 0
    errors: int = 0
    last_active: Optional[str] = None
    signal_counts: dict[str, int] = field(default_factory=dict)
    _confidence_sum: float = 0.0
    _confidence_n: int = 0
    recent: deque = field(default_factory=lambda: deque(maxlen=20))

    def record(self, signal: str, confidence: float, error: bool = False) -> None:
        self.invocations += 1
        self.last_active = _now()
        if error:
            self.errors += 1
        key = (signal or "UNKNOWN").upper()
        self.signal_counts[key] = self.signal_counts.get(key, 0) + 1
        try:
            conf = float(confidence)
        except (TypeError, ValueError):
            conf = 0.0
        self._confidence_sum += conf
        self._confidence_n += 1
        self.recent.append({"signal": key, "confidence": round(conf, 3), "at": self.last_active})

    @property
    def avg_confidence(self) -> Optional[float]:
        if self._confidence_n == 0:
            return None
        return round(self._confidence_sum / self._confidence_n, 4)

    @property
    def error_rate(self) -> float:
        if self.invocations == 0:
            return 0.0
        return round(self.errors / self.invocations, 4)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "invocations": self.invocations,
            "errors": self.errors,
            "error_rate": self.error_rate,
            "last_active": self.last_active,
            "signal_counts": dict(self.signal_counts),
            "avg_confidence": self.avg_confidence,
            "recent": list(self.recent),
            # `status` is derived from real activity, not a fixed string.
            "status": "active" if self.invocations > 0 else "idle",
        }


class AgentActivityTracker:
    """Thread-safe, bounded registry of per-agent runtime activity."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._agents: dict[str, AgentActivity] = {}

    def _get_or_create(self, name: str) -> AgentActivity:
        activity = self._agents.get(name)
        if activity is None:
            activity = AgentActivity(name=name)
            self._agents[name] = activity
        return activity

    def record(
        self,
        name: str,
        signal: str = "NEUTRAL",
        confidence: float = 0.0,
        error: bool = False,
    ) -> None:
        """Record one agent run (fail-safe: never raises)."""
        try:
            with self._lock:
                self._get_or_create(name).record(signal, confidence, error=error)
        except Exception:  # noqa: BLE001 - observability must never break analysis
            pass

    def snapshot(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {name: a.to_dict() for name, a in self._agents.items()}

    def get(self, name: str) -> Optional[dict[str, Any]]:
        with self._lock:
            activity = self._agents.get(name)
            return activity.to_dict() if activity else None

    def reset(self) -> None:
        with self._lock:
            self._agents.clear()


_INSTANCE: Optional[AgentActivityTracker] = None
_SHARED_KEY = "_ea_shared_activity_tracker"


def get_activity_tracker() -> AgentActivityTracker:
    """Return the process-wide activity tracker (lazy singleton).

    Stored on a process-global slot so the ``src.agents.activity`` and
    ``agents.activity`` import identities share ONE tracker.
    """
    global _INSTANCE
    if _INSTANCE is None:
        import builtins

        shared = getattr(builtins, _SHARED_KEY, None)
        if shared is not None:
            _INSTANCE = shared
        else:
            _INSTANCE = AgentActivityTracker()
            setattr(builtins, _SHARED_KEY, _INSTANCE)
    return _INSTANCE
