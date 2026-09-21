# -*- coding: utf-8 -*-
"""Tests for Autonomous Research Scheduler & Research Inbox (Phase 54)."""

import pytest

from src.research.scheduler import (
    DEFAULT_TASKS,
    InboxStatus,
    ResearchInbox,
    ResearchScheduler,
    ResearchTask,
)


def test_default_tasks_cover_cadences() -> None:
    cadences = {t.cadence for t in DEFAULT_TASKS}
    assert {"DAILY", "WEEKLY", "MONTHLY", "AFTER_N_TRADES"} <= cadences


def test_daily_trigger() -> None:
    scheduler = ResearchScheduler()
    items = scheduler.run_daily()
    assert [i.task for i in items] == ["performance_aggregation"]


def test_weekly_triggers_two_tasks() -> None:
    scheduler = ResearchScheduler()
    items = scheduler.run_weekly()
    assert set(i.task for i in items) == {"strategy_review", "robustness_research"}


def test_monthly_trigger() -> None:
    scheduler = ResearchScheduler()
    items = scheduler.run_monthly()
    assert [i.task for i in items] == ["parameter_sensitivity"]


def test_after_n_trades_trigger() -> None:
    scheduler = ResearchScheduler()
    triggered = []
    for _ in range(50):
        triggered = scheduler.record_trade()
    assert any(i.task == "learning_review" for i in triggered)


def test_scheduler_deposits_into_inbox() -> None:
    scheduler = ResearchScheduler()
    items = scheduler.run_daily()
    assert scheduler.inbox.get(items[0].item_id) is not None
    assert items[0].status == InboxStatus.NEW.value


def test_inbox_transition_workflow() -> None:
    inbox = ResearchInbox()
    item = inbox.add("robustness_research", {"metric": 1.2})
    inbox.transition(item.item_id, InboxStatus.REVIEWING.value)
    inbox.transition(item.item_id, InboxStatus.EXPERIMENT.value)
    inbox.transition(item.item_id, InboxStatus.VALIDATED.value)
    assert item.status == InboxStatus.VALIDATED.value
    assert len(item.history) == 3


def test_inbox_reject_branch() -> None:
    inbox = ResearchInbox()
    item = inbox.add("strategy_review", {})
    inbox.transition(item.item_id, InboxStatus.REVIEWING.value)
    inbox.transition(item.item_id, InboxStatus.REJECTED.value)
    assert item.status == InboxStatus.REJECTED.value
    assert inbox.by_status(InboxStatus.REJECTED.value) == [item]


def test_inbox_unknown_status_rejected() -> None:
    inbox = ResearchInbox()
    item = inbox.add("t", {})
    with pytest.raises(ValueError):
        inbox.transition(item.item_id, "BOGUS")


def test_inbox_illegal_transition_rejected() -> None:
    """Audit P3-5: skipping workflow stages must be rejected."""
    inbox = ResearchInbox()
    item = inbox.add("t", {})
    # NEW → VALIDATED skips REVIEWING/EXPERIMENT → illegal.
    with pytest.raises(ValueError):
        inbox.transition(item.item_id, InboxStatus.VALIDATED.value)
    assert item.status == InboxStatus.NEW.value


def test_inbox_terminal_state_has_no_transitions() -> None:
    """VALIDATED is terminal — no further transitions allowed."""
    inbox = ResearchInbox()
    item = inbox.add("t", {})
    inbox.transition(item.item_id, InboxStatus.REVIEWING.value)
    inbox.transition(item.item_id, InboxStatus.EXPERIMENT.value)
    inbox.transition(item.item_id, InboxStatus.VALIDATED.value)
    with pytest.raises(ValueError):
        inbox.transition(item.item_id, InboxStatus.REJECTED.value)


def test_runner_failure_does_not_break_scheduler() -> None:
    def boom(_task: ResearchTask) -> dict:
        raise RuntimeError("boom")

    scheduler = ResearchScheduler(runner=boom)
    items = scheduler.run_daily()
    assert items[0].result["error"] == "RuntimeError"


def test_scheduler_never_changes_production() -> None:
    # The scheduler exposes no production mutation API — only inbox deposits.
    scheduler = ResearchScheduler()
    assert not hasattr(scheduler, "set_production")
    assert not hasattr(scheduler, "promote")
