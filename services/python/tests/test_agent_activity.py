# -*- coding: utf-8 -*-
"""Tests for the agent activity tracker (realtime agent metrics)."""

from __future__ import annotations

from src.agents.activity import AgentActivity, AgentActivityTracker


def test_record_and_snapshot() -> None:
    tracker = AgentActivityTracker()
    tracker.record("technical_analyst", "BULLISH", 0.7)
    tracker.record("technical_analyst", "BEARISH", 0.3)
    snap = tracker.snapshot()
    entry = snap["technical_analyst"]
    assert entry["invocations"] == 2
    assert entry["status"] == "active"
    assert entry["signal_counts"] == {"BULLISH": 1, "BEARISH": 1}
    assert entry["avg_confidence"] == 0.5
    assert entry["last_active"] is not None


def test_idle_when_no_runs() -> None:
    tracker = AgentActivityTracker()
    tracker.snapshot()
    # untouched agent has no entry
    assert tracker.get("nobody") is None


def test_error_rate() -> None:
    tracker = AgentActivityTracker()
    tracker.record("a", "NEUTRAL", 0.0, error=True)
    tracker.record("a", "NEUTRAL", 0.0, error=False)
    entry = tracker.get("a")
    assert entry is not None
    assert entry["errors"] == 1
    assert entry["error_rate"] == 0.5


def test_activity_never_raises_on_bad_conf() -> None:
    activity = AgentActivity(name="test")
    activity.record("BULLISH", None)  # type: ignore[arg-type]
    assert activity.invocations == 1
    assert activity.avg_confidence == 0.0


def test_reset() -> None:
    tracker = AgentActivityTracker()
    tracker.record("a", "BULLISH", 0.5)
    tracker.reset()
    assert tracker.snapshot() == {}


def test_recent_bounded() -> None:
    activity = AgentActivity(name="test")
    for i in range(30):
        activity.record("BULLISH", 0.5)
    assert len(activity.recent) == 20
