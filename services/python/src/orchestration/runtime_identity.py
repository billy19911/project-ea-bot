# -*- coding: utf-8 -*-
"""Runtime identity — one identity per process + per runtime component.

TASK 05 (duplicate-worker detection). The system must have exactly ONE
production instance of the runtime, scheduler, event queue, supervisor,
pipeline, market feed loop, position monitor and reconciliation runner —
unless a component is explicitly scoped per account/terminal.

To *prove* that at runtime (and to catch a future duplicate worker that would
otherwise be invisible), every analysis log line carries a small identity
stamp::

    process_id           — OS pid of the serving process (os.getpid())
    runtime_instance_id  — id() + short uuid of the OrchestrationRuntime
    scheduler_instance_id— instance id of the AutonomousScheduler owned by it
    feed_instance_id     — instance id of the MarketFeedLoop, if the feed runs
    host / pid           — where the process lives (multi-process detection)

The identity is deterministic from the process: it is generated ONCE at
module import (``_PROCESS_ID``) and reused for every component. Two different
processes therefore report different ``process_id`` values, and two components
of the same *kind* in the same process report different ``*_instance_id``
values — which is exactly the duplicate-worker signal we want.

This module is intentionally dependency-free (stdlib only) so it can be
imported from any layer without risking a circular import or a hard failure.
Every function is fail-safe: an error never raises, it returns a placeholder
so logging can never break a trading cycle.
"""

from __future__ import annotations

import os
import socket
import uuid
from typing import Any, Optional

__all__ = [
    "process_identity",
    "new_instance_id",
    "RuntimeIdentity",
]

# Captured once at import so every import of this module in one process agrees.
_PROCESS_ID: int = os.getpid()
_HOSTNAME: str = ""
try:  # pragma: no cover - hostname lookup is trivial but must never raise
    _HOSTNAME = socket.gethostname()
except Exception:  # noqa: BLE001 - identity must never break import
    _HOSTNAME = "unknown-host"


def process_identity() -> dict[str, Any]:
    """Return the stable identity of THIS operating-system process.

    Returns a fresh dict each call (callers may mutate it) containing::

        process_id  — OS pid (int)
        host        — hostname (str)
    """
    return {"process_id": _PROCESS_ID, "host": _HOSTNAME}


def new_instance_id(component: str) -> str:
    """Return a unique instance id for one component in this process.

    Format: ``<component>-<pid>-<8 hex>``. The pid prefix makes a duplicate
    worker immediately visible (same kind, same process, different suffix);
    two processes are distinguishable by the pid segment alone.
    """
    kind = str(component or "component").strip().lower() or "component"
    try:
        return f"{kind}-{_PROCESS_ID}-{uuid.uuid4().hex[:8]}"
    except Exception:  # noqa: BLE001 - identity must never raise
        return f"{kind}-{_PROCESS_ID}-unknown"


class RuntimeIdentity:
    """Identity of one runtime instance and the components it owns.

    Constructed once by :class:`~orchestration.runtime.OrchestrationRuntime`.
    Component ids are assigned lazily (``scheduler``/``feed`` etc. are created
    after the runtime in some code paths) and are stable once set.

    This is a *diagnostic* object only: it is never read by the decision path
    and never changes trading behaviour. Every accessor is fail-safe.
    """

    def __init__(self, kind: str = "runtime") -> None:
        self.process_id: int = _PROCESS_ID
        self.host: str = _HOSTNAME
        self.runtime_instance_id: str = new_instance_id(kind)
        self.scheduler_instance_id: Optional[str] = None
        self.feed_instance_id: Optional[str] = None
        self.queue_instance_id: Optional[str] = None
        self.supervisor_instance_id: Optional[str] = None
        self.pipeline_instance_id: Optional[str] = None
        self.position_monitor_instance_id: Optional[str] = None
        self.reconciliation_instance_id: Optional[str] = None

    # ------------------------------------------------------------------
    # Component registration (idempotent: first writer wins)
    # ------------------------------------------------------------------
    def _set_once(self, attr: str, value: str) -> str:
        current = getattr(self, attr, None)
        if not current:
            setattr(self, attr, value)
            return value
        return current

    def register_scheduler(self, component: Any = None) -> str:
        """Assign (once) the scheduler instance id; return the effective id."""
        return self._set_once("scheduler_instance_id", new_instance_id("scheduler"))

    def register_feed(self, component: Any = None) -> str:
        """Assign (once) the market-feed instance id; return the effective id."""
        return self._set_once("feed_instance_id", new_instance_id("feed"))

    def register_queue(self, component: Any = None) -> str:
        return self._set_once("queue_instance_id", new_instance_id("queue"))

    def register_supervisor(self, component: Any = None) -> str:
        return self._set_once("supervisor_instance_id", new_instance_id("supervisor"))

    def register_pipeline(self, component: Any = None) -> str:
        return self._set_once("pipeline_instance_id", new_instance_id("pipeline"))

    def register_position_monitor(self, component: Any = None) -> str:
        return self._set_once("position_monitor_instance_id", new_instance_id("position_monitor"))

    def register_reconciliation(self, component: Any = None) -> str:
        return self._set_once("reconciliation_instance_id", new_instance_id("reconciliation"))

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        """Return the identity as a plain dict (for logs / API payloads)."""
        return {
            "process_id": self.process_id,
            "host": self.host,
            "runtime_instance_id": self.runtime_instance_id,
            "scheduler_instance_id": self.scheduler_instance_id,
            "feed_instance_id": self.feed_instance_id,
            "queue_instance_id": self.queue_instance_id,
            "supervisor_instance_id": self.supervisor_instance_id,
            "pipeline_instance_id": self.pipeline_instance_id,
            "position_monitor_instance_id": self.position_monitor_instance_id,
            "reconciliation_instance_id": self.reconciliation_instance_id,
        }

    def log_fields(self) -> dict[str, Any]:
        """Return the four STOP-GATE-05 identity fields for a log record.

        The task requires every analysis log to include ``process_id``,
        ``runtime_instance_id``, ``scheduler_instance_id`` and
        ``feed_instance_id``. This returns exactly those (plus host, which is
        free and useful for multi-process attribution).
        """
        return {
            "process_id": self.process_id,
            "runtime_instance_id": self.runtime_instance_id,
            "scheduler_instance_id": self.scheduler_instance_id or "",
            "feed_instance_id": self.feed_instance_id or "",
        }

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return (
            f"RuntimeIdentity(process_id={self.process_id}, "
            f"runtime_instance_id={self.runtime_instance_id!r}, "
            f"scheduler_instance_id={self.scheduler_instance_id!r}, "
            f"feed_instance_id={self.feed_instance_id!r})"
        )
