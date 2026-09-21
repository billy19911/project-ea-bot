# -*- coding: utf-8 -*-
"""Autonomous Research Scheduler — PRD_V2 §54.

The supervisor can schedule research automatically. The scheduler **never**
changes production directly — every result is deposited into a *Research Inbox*
where it must be triaged (NEW → REVIEWING → EXPERIMENT → VALIDATED / REJECTED).

Cadences (PRD §54)::

    DAILY    → performance aggregation
    WEEKLY   → strategy review
    WEEKLY   → robustness research
    MONTHLY  → parameter sensitivity
    AFTER N TRADES → learning review
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Optional

__all__ = [
    "ResearchTask",
    "InboxStatus",
    "ResearchItem",
    "ResearchInbox",
    "ResearchScheduler",
]


class InboxStatus(str, Enum):
    """Research Inbox item statuses (PRD §54)."""

    NEW = "NEW"
    REVIEWING = "REVIEWING"
    EXPERIMENT = "EXPERIMENT"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"


# Allowed workflow transitions (audit P3-5). VALIDATED/REJECTED are terminal.
_ALLOWED_TRANSITIONS: dict[str, tuple[str, ...]] = {
    InboxStatus.NEW.value: (InboxStatus.REVIEWING.value, InboxStatus.REJECTED.value),
    InboxStatus.REVIEWING.value: (
        InboxStatus.EXPERIMENT.value,
        InboxStatus.REJECTED.value,
    ),
    InboxStatus.EXPERIMENT.value: (
        InboxStatus.VALIDATED.value,
        InboxStatus.REJECTED.value,
    ),
    InboxStatus.VALIDATED.value: (),
    InboxStatus.REJECTED.value: (),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ResearchTask:
    """A scheduled research task (PRD §54)."""

    name: str
    cadence: str  # DAILY | WEEKLY | MONTHLY | AFTER_N_TRADES
    action: str
    n_trades: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "cadence": self.cadence,
            "action": self.action,
            "n_trades": self.n_trades,
        }


# The default weekly/monthly task set (PRD §54).
DEFAULT_TASKS: tuple[ResearchTask, ...] = (
    ResearchTask("performance_aggregation", "DAILY", "aggregate performance"),
    ResearchTask("strategy_review", "WEEKLY", "review strategies"),
    ResearchTask("robustness_research", "WEEKLY", "robustness research"),
    ResearchTask("parameter_sensitivity", "MONTHLY", "parameter sensitivity"),
    ResearchTask("learning_review", "AFTER_N_TRADES", "learning review", n_trades=50),
)


@dataclass
class ResearchItem:
    """An item in the Research Inbox (PRD §54)."""

    item_id: str
    task: str
    result: dict[str, Any] = field(default_factory=dict)
    status: str = InboxStatus.NEW.value
    created_at: str = field(default_factory=_now)
    history: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "task": self.task,
            "result": dict(self.result),
            "status": self.status,
            "created_at": self.created_at,
        }


class ResearchInbox:
    """A queue of research results awaiting triage (PRD §54)."""

    def __init__(self) -> None:
        self._items: dict[str, ResearchItem] = {}
        self._order: list[str] = []
        self._counter = 0

    def add(self, task: str, result: dict[str, Any]) -> ResearchItem:
        self._counter += 1
        item = ResearchItem(item_id=f"RI-{self._counter}", task=task, result=dict(result))
        self._items[item.item_id] = item
        self._order.append(item.item_id)
        return item

    def get(self, item_id: str) -> Optional[ResearchItem]:
        return self._items.get(item_id)

    def all(self) -> list[ResearchItem]:
        return [self._items[i] for i in self._order]

    def by_status(self, status: str) -> list[ResearchItem]:
        return [i for i in self.all() if i.status == status]

    def transition(self, item_id: str, new_status: str, actor: str = "system") -> ResearchItem:
        """Move an item through the inbox workflow (validated transitions only).

        Audit P3-5: only transitions defined in the workflow graph are allowed
        (NEW → REVIEWING/REJECTED → … → VALIDATED/REJECTED). An illegal jump
        raises ``ValueError`` so the workflow can no longer skip stages.
        """
        item = self._items.get(item_id)
        if item is None:
            raise ValueError(f"Unknown research item: {item_id}")
        if new_status not in {s.value for s in InboxStatus}:
            raise ValueError(f"Unknown inbox status: {new_status}")
        allowed = _ALLOWED_TRANSITIONS.get(item.status, ())
        if new_status not in allowed:
            raise ValueError(
                f"Invalid inbox transition: {item.status} → {new_status} "
                f"(allowed: {', '.join(allowed) or 'none'})"
            )
        item.status = new_status
        item.history.append({"status": new_status, "actor": actor, "timestamp": _now()})
        return item


class ResearchScheduler:
    """Auto-schedules research on cadence and deposits results (PRD §54).

    Args:
        inbox: The research inbox to deposit results into.
        tasks: The task set (defaults to :data:`DEFAULT_TASKS`).
        runner: Callable ``(task) -> dict`` executing a research task.
    """

    def __init__(
        self,
        inbox: Optional[ResearchInbox] = None,
        tasks: Optional[tuple[ResearchTask, ...]] = None,
        runner: Optional[Callable[[ResearchTask], dict[str, Any]]] = None,
    ) -> None:
        self.inbox = inbox or ResearchInbox()
        self.tasks = tuple(tasks) if tasks is not None else DEFAULT_TASKS
        self.runner = runner or (lambda task: {"task": task.name, "status": "ok"})
        self.trades_since_last_learning_review = 0

    # ------------------------------------------------------------------
    def run_daily(self) -> list[ResearchItem]:
        return self._run_cadence("DAILY")

    def run_weekly(self) -> list[ResearchItem]:
        return self._run_cadence("WEEKLY")

    def run_monthly(self) -> list[ResearchItem]:
        return self._run_cadence("MONTHLY")

    def record_trade(self) -> list[ResearchItem]:
        """Record a trade; trigger AFTER_N_TRADES tasks when the threshold hits."""
        self.trades_since_last_learning_review += 1
        triggered: list[ResearchItem] = []
        for task in self.tasks:
            if task.cadence != "AFTER_N_TRADES":
                continue
            if self.trades_since_last_learning_review >= max(1, task.n_trades):
                triggered.append(self._deposit(task))
        if triggered:
            self.trades_since_last_learning_review = 0
        return triggered

    # ------------------------------------------------------------------
    def _run_cadence(self, cadence: str) -> list[ResearchItem]:
        return [self._deposit(task) for task in self.tasks if task.cadence == cadence]

    def _deposit(self, task: ResearchTask) -> ResearchItem:
        try:
            result = self.runner(task)
        except Exception as exc:  # noqa: BLE001 - research must never break the loop
            result = {"task": task.name, "error": type(exc).__name__}
        return self.inbox.add(task.name, result)
