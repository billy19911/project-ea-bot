# -*- coding: utf-8 -*-
"""Task Contract (§7) — task lifecycle state machine.

A :class:`Task` is the unit of work dispatched to departments/specialists.
Its lifecycle is enforced as an explicit state machine::

    CREATED → QUEUED → RUNNING → COMPLETED | FAILED | CANCELLED | TIMED_OUT

Terminal states (COMPLETED, FAILED, CANCELLED, TIMED_OUT) are final — any
attempt to transition out of them raises :class:`IllegalTaskTransitionError`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class TaskStatus(str, Enum):
    """Lifecycle states for a task."""

    CREATED = "CREATED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"


class TaskPriority(int, Enum):
    """Dispatch priority (higher = more urgent)."""

    CRITICAL = 100
    HIGH = 75
    NORMAL = 50
    LOW = 25


TERMINAL_STATUSES: frozenset[TaskStatus] = frozenset(
    {
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
        TaskStatus.TIMED_OUT,
    }
)

# Legal transitions: source -> set of allowed targets.
_LEGAL_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.CREATED: frozenset({TaskStatus.QUEUED, TaskStatus.CANCELLED}),
    TaskStatus.QUEUED: frozenset({TaskStatus.RUNNING, TaskStatus.CANCELLED, TaskStatus.TIMED_OUT}),
    TaskStatus.RUNNING: frozenset(
        {
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
            TaskStatus.TIMED_OUT,
        }
    ),
    # Terminal states have no outgoing transitions.
    TaskStatus.COMPLETED: frozenset(),
    TaskStatus.FAILED: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
    TaskStatus.TIMED_OUT: frozenset(),
}


class IllegalTaskTransitionError(RuntimeError):
    """Raised when a task is asked to make a disallowed state transition."""

    def __init__(self, frm: TaskStatus, to: TaskStatus) -> None:
        super().__init__(f"Illegal task transition: {frm.value} → {to.value}")
        self.frm = frm
        self.to = to


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Task:
    """A dispatchable unit of work with an enforced lifecycle.

    The dataclass holds only state; transitions are performed via the
    helper methods (:meth:`queue`, :meth:`start`, :meth:`complete`,
    :meth:`fail`, :meth:`cancel`, :meth:`timeout`).
    """

    task_id: str
    event_id: str
    task_type: str
    priority: TaskPriority = TaskPriority.NORMAL
    status: TaskStatus = TaskStatus.CREATED
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)
    assigned_departments: list[str] = field(default_factory=list)
    deadline: Optional[str] = None
    ttl_seconds: Optional[int] = None
    result_ref: Optional[str] = None
    error: Optional[str] = None

    def __post_init__(self) -> None:
        # Derive a deadline from the TTL when one is supplied and no explicit
        # deadline was provided.
        if self.deadline is None and self.ttl_seconds is not None:
            deadline = datetime.now(timezone.utc).timestamp() + float(self.ttl_seconds)
            self.deadline = datetime.fromtimestamp(deadline, tz=timezone.utc).isoformat()

    # ------------------------------------------------------------------
    # Introspection helpers
    # ------------------------------------------------------------------

    @property
    def is_terminal(self) -> bool:
        """True when the task has reached a final state."""
        return self.status in TERMINAL_STATUSES

    def can_transition_to(self, target: TaskStatus) -> bool:
        """Return whether the ``target`` status is reachable from current."""
        return target in _LEGAL_TRANSITIONS.get(self.status, frozenset())

    def _transition(self, target: TaskStatus) -> None:
        """Apply a transition, raising on illegal moves."""
        if not self.can_transition_to(target):
            raise IllegalTaskTransitionError(self.status, target)
        self.status = target
        self.updated_at = _now_iso()

    # ------------------------------------------------------------------
    # Lifecycle transitions
    # ------------------------------------------------------------------

    def queue(self) -> "Task":
        """CREATED → QUEUED."""
        self._transition(TaskStatus.QUEUED)
        return self

    def start(self) -> "Task":
        """QUEUED → RUNNING."""
        self._transition(TaskStatus.RUNNING)
        return self

    def complete(self, result_ref: str) -> "Task":
        """RUNNING → COMPLETED, recording the result reference."""
        self._transition(TaskStatus.COMPLETED)
        self.result_ref = result_ref
        return self

    def fail(self, error: str) -> "Task":
        """RUNNING → FAILED, recording the error."""
        self._transition(TaskStatus.FAILED)
        self.error = error
        return self

    def cancel(self, reason: Optional[str] = None) -> "Task":
        """→ CANCELLED (from CREATED, QUEUED, or RUNNING)."""
        self._transition(TaskStatus.CANCELLED)
        if reason is not None:
            self.error = reason
        return self

    def timeout(self) -> "Task":
        """→ TIMED_OUT (from QUEUED or RUNNING)."""
        self._transition(TaskStatus.TIMED_OUT)
        return self

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialize the task (enums as their string values)."""
        return {
            "task_id": self.task_id,
            "event_id": self.event_id,
            "task_type": self.task_type,
            "priority": self.priority.value,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "assigned_departments": list(self.assigned_departments),
            "deadline": self.deadline,
            "ttl_seconds": self.ttl_seconds,
            "result_ref": self.result_ref,
            "error": self.error,
        }
