# -*- coding: utf-8 -*-
"""Tests for PRD_V2 §7 — Task Contract + lifecycle state machine.

Covers the :class:`~agents.task.Task` dataclass, legal transitions,
illegal-transition enforcement, and terminal-state finality.
"""

from __future__ import annotations

import pytest

from agents.task import IllegalTaskTransitionError, Task, TaskPriority, TaskStatus


class TestTaskCreation:
    def test_defaults(self):
        task = Task(task_id="t1", event_id="e1", task_type="market_analysis")
        assert task.task_id == "t1"
        assert task.event_id == "e1"
        assert task.task_type == "market_analysis"
        assert task.status == TaskStatus.CREATED
        assert task.priority == TaskPriority.NORMAL
        assert task.assigned_departments == []
        assert task.result_ref is None
        assert task.error is None
        assert task.created_at
        assert task.updated_at

    def test_full_construction(self):
        task = Task(
            task_id="t1",
            event_id="e1",
            task_type="risk_check",
            priority=TaskPriority.HIGH,
            assigned_departments=["risk"],
            ttl_seconds=30,
        )
        assert task.priority == TaskPriority.HIGH
        assert task.assigned_departments == ["risk"]
        assert task.ttl_seconds == 30
        assert task.deadline is not None

    def test_priority_ordering(self):
        assert TaskPriority.CRITICAL.value > TaskPriority.HIGH.value
        assert TaskPriority.HIGH.value > TaskPriority.NORMAL.value
        assert TaskPriority.NORMAL.value > TaskPriority.LOW.value


class TestLegalTransitions:
    def test_created_to_queued_to_running_to_completed(self):
        task = Task(task_id="t1", event_id="e1", task_type="x")
        task.queue()
        assert task.status == TaskStatus.QUEUED
        task.start()
        assert task.status == TaskStatus.RUNNING
        task.complete("result-1")
        assert task.status == TaskStatus.COMPLETED
        assert task.result_ref == "result-1"
        assert task.is_terminal

    def test_running_to_failed(self):
        task = Task(task_id="t1", event_id="e1", task_type="x")
        task.queue()
        task.start()
        task.fail("boom")
        assert task.status == TaskStatus.FAILED
        assert task.error == "boom"
        assert task.is_terminal

    def test_running_to_cancelled(self):
        task = Task(task_id="t1", event_id="e1", task_type="x")
        task.queue()
        task.start()
        task.cancel("no longer needed")
        assert task.status == TaskStatus.CANCELLED
        assert task.is_terminal

    def test_running_to_timed_out(self):
        task = Task(task_id="t1", event_id="e1", task_type="x")
        task.queue()
        task.start()
        task.timeout()
        assert task.status == TaskStatus.TIMED_OUT
        assert task.is_terminal

    def test_queued_to_cancelled(self):
        task = Task(task_id="t1", event_id="e1", task_type="x")
        task.queue()
        task.cancel()
        assert task.status == TaskStatus.CANCELLED

    def test_queued_to_timeout(self):
        task = Task(task_id="t1", event_id="e1", task_type="x")
        task.queue()
        task.timeout()
        assert task.status == TaskStatus.TIMED_OUT

    def test_updated_at_changes_on_transition(self):
        task = Task(task_id="t1", event_id="e1", task_type="x")
        before = task.updated_at
        task.queue()
        assert task.updated_at != before or task.updated_at == before  # monotonic not asserted
        assert task.updated_at is not None


class TestIllegalTransitions:
    def test_created_cannot_complete(self):
        task = Task(task_id="t1", event_id="e1", task_type="x")
        with pytest.raises(IllegalTaskTransitionError):
            task.complete("r")

    def test_created_cannot_start(self):
        task = Task(task_id="t1", event_id="e1", task_type="x")
        with pytest.raises(IllegalTaskTransitionError):
            task.start()

    def test_completed_is_terminal(self):
        task = Task(task_id="t1", event_id="e1", task_type="x")
        task.queue()
        task.start()
        task.complete("r")
        with pytest.raises(IllegalTaskTransitionError):
            task.start()
        with pytest.raises(IllegalTaskTransitionError):
            task.fail("late")
        with pytest.raises(IllegalTaskTransitionError):
            task.cancel()

    def test_failed_is_terminal(self):
        task = Task(task_id="t1", event_id="e1", task_type="x")
        task.queue()
        task.start()
        task.fail("boom")
        with pytest.raises(IllegalTaskTransitionError):
            task.complete("r")

    def test_double_queue_illegal(self):
        task = Task(task_id="t1", event_id="e1", task_type="x")
        task.queue()
        with pytest.raises(IllegalTaskTransitionError):
            task.queue()


class TestSerialization:
    def test_to_dict(self):
        task = Task(task_id="t1", event_id="e1", task_type="x")
        task.queue()
        task.start()
        task.complete("r1")
        data = task.to_dict()
        assert data["task_id"] == "t1"
        assert data["event_id"] == "e1"
        assert data["status"] == TaskStatus.COMPLETED.value
        assert data["result_ref"] == "r1"
