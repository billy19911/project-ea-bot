# -*- coding: utf-8 -*-
"""Tests for the learning feedback loop (Phase 7).

Covers the full feedback chain:

* ``LessonFeedbackProvider.summarize_for_symbol`` — compact stats for analysis,
* ``TradingPipeline(lesson_provider=...)`` — injects ``context["lessons"]``
  (absent without a provider → backward-compatible),
* ``MarketLead`` / ``RiskLead`` — surface a "Historical lessons" reason when
  lessons are present, **without changing signal or confidence**,
* ``record_review_lesson`` — the ReviewAutoTrigger → store bridge,
* ``/learning/analytics`` — reports real lessons (available:true) instead of a
  hardcoded unavailable payload.

No network, no MT5.
"""

from __future__ import annotations

import pytest

from agents.analysts.review_agent import InMemoryLessonStore, get_lesson_store, set_lesson_store
from learning.feedback import LessonFeedbackProvider, record_review_lesson
from learning.lesson_store import JsonlLessonStore
from market.intelligence import MarketLead
from orchestration.pipeline import TradingPipeline
from review.auto_trigger import ReviewAutoTrigger
from risk.intelligence import RiskLead


# ---------------------------------------------------------------------------
# Helpers / fakes
# ---------------------------------------------------------------------------
def _store_with_lessons() -> InMemoryLessonStore:
    store = InMemoryLessonStore()
    store.add_lesson({"trade_id": "T1", "symbol": "EURUSD", "outcome": "win", "lesson": "l1"})
    store.add_lesson({"trade_id": "T2", "symbol": "EURUSD", "outcome": "loss", "lesson": "l2"})
    store.add_lesson({"trade_id": "T3", "symbol": "XAUUSD", "outcome": "win", "lesson": "l3"})
    store.add_lesson({"trade_id": "T4", "symbol": "EURUSD", "outcome": "breakeven", "lesson": "l4"})
    return store


class _CapturingSupervisor:
    """Supervisor stub that records the context it receives."""

    def __init__(self) -> None:
        self.contexts: list[dict] = []

    def analyze(self, context):
        self.contexts.append(dict(context))
        return {
            "overall_signal": "NEUTRAL",
            "overall_confidence": 0.0,
            "agent_results": {},
            "summary": "stub summary",
        }


class _NeverCalledGate:
    """Risk gate stub that must never run (no actionable proposal)."""

    def validate_proposal(self, *args):  # pragma: no cover - must not run
        raise AssertionError("risk gate should not be called for a NEUTRAL synthesis")


def _pipeline(supervisor, provider=None) -> TradingPipeline:
    return TradingPipeline(
        supervisor=supervisor,
        risk_gate=_NeverCalledGate(),
        lesson_provider=provider,
    )


# ---------------------------------------------------------------------------
# LessonFeedbackProvider.summarize_for_symbol
# ---------------------------------------------------------------------------
def test_summarize_counts_wins_and_losses() -> None:
    provider = LessonFeedbackProvider(_store_with_lessons())

    summary = provider.summarize_for_symbol("EURUSD")

    assert summary["count"] == 3  # T1, T2, T4
    assert summary["wins"] == 1
    assert summary["losses"] == 1


def test_summarize_recent_is_bounded_and_newest_first() -> None:
    provider = LessonFeedbackProvider(_store_with_lessons())

    summary = provider.summarize_for_symbol("EURUSD", max_lessons=2)

    assert len(summary["recent"]) == 2
    assert summary["recent"][0]["lesson"] == "l4"  # newest first


def test_summarize_wildcard_includes_all_symbols() -> None:
    provider = LessonFeedbackProvider(_store_with_lessons())

    summary = provider.summarize_for_symbol("*")

    assert summary["count"] == 4
    assert summary["wins"] == 2
    assert summary["losses"] == 1


def test_summarize_is_fail_safe_on_broken_store() -> None:
    class _BrokenStore:
        def all_lessons(self):
            raise RuntimeError("store down")

    provider = LessonFeedbackProvider(_BrokenStore())

    summary = provider.summarize_for_symbol("EURUSD")

    assert summary["count"] == 0
    assert summary["recent"] == []


# ---------------------------------------------------------------------------
# Pipeline injection (backward-compatible)
# ---------------------------------------------------------------------------
def test_pipeline_injects_lessons_when_provider_present() -> None:
    supervisor = _CapturingSupervisor()
    provider = LessonFeedbackProvider(_store_with_lessons())
    pipeline = _pipeline(supervisor, provider=provider)

    pipeline.run({"event_type": "BREAKOUT", "symbol": "EURUSD"})

    assert "lessons" in supervisor.contexts[0]
    assert supervisor.contexts[0]["lessons"]["count"] == 3


def test_pipeline_without_provider_has_no_lessons_key() -> None:
    supervisor = _CapturingSupervisor()
    pipeline = _pipeline(supervisor)

    pipeline.run({"event_type": "BREAKOUT", "symbol": "EURUSD"})

    assert "lessons" not in supervisor.contexts[0]


def test_pipeline_survives_broken_lesson_provider() -> None:
    class _BrokenProvider:
        def summarize_for_symbol(self, symbol, max_lessons=5):
            raise RuntimeError("provider down")

    supervisor = _CapturingSupervisor()
    pipeline = _pipeline(supervisor, provider=_BrokenProvider())

    result = pipeline.run({"event_type": "BREAKOUT", "symbol": "EURUSD"})

    assert result.decision == "WAIT"  # cycle unaffected


# ---------------------------------------------------------------------------
# Lead reasons (advisory only — signal/confidence unchanged)
# ---------------------------------------------------------------------------
_LESSONS = {
    "count": 3,
    "wins": 2,
    "losses": 1,
    "recent": [{"category": "win_followed", "lesson": "EURUSD win: keep it", "outcome": "win"}],
}


def test_market_lead_reasons_include_historical_lessons() -> None:
    lead = MarketLead()

    result = lead.analyze({"event_type": "TREND_BULLISH", "symbol": "EURUSD", "lessons": _LESSONS})

    assert any("Historical lessons" in reason for reason in result["reasons"])


def test_market_lead_signal_unchanged_by_lessons() -> None:
    lead = MarketLead()
    context = {"event_type": "TREND_BULLISH", "symbol": "EURUSD"}

    without = lead.analyze(dict(context))
    with_lessons = lead.analyze({**context, "lessons": _LESSONS})

    assert with_lessons["signal"] == without["signal"]
    assert with_lessons["confidence"] == without["confidence"]


def test_risk_lead_reasons_include_historical_lessons() -> None:
    lead = RiskLead()
    context = {
        "risk_data": {
            "balance": 10000.0,
            "equity": 10000.0,
            "positions": [],
            "total_open_lots": 0.0,
        },
        "lessons": _LESSONS,
    }

    result = lead.analyze(context)

    assert any("Historical lessons" in reason for reason in result["reasons"])


def test_risk_lead_signal_unchanged_by_lessons() -> None:
    lead = RiskLead()
    context = {
        "risk_data": {
            "balance": 10000.0,
            "equity": 10000.0,
            "positions": [],
            "total_open_lots": 0.0,
        }
    }

    without = lead.analyze(dict(context))
    with_lessons = lead.analyze({**context, "lessons": _LESSONS})

    assert with_lessons["signal"] == without["signal"]
    assert with_lessons["confidence"] == without["confidence"]


# ---------------------------------------------------------------------------
# ReviewAutoTrigger → store bridge
# ---------------------------------------------------------------------------
def test_record_review_lesson_persists_compact_lesson() -> None:
    store = InMemoryLessonStore()
    trigger = ReviewAutoTrigger(on_review=lambda record: record_review_lesson(store, record))

    trigger.on_position_closed(
        {
            "trade_id": "T-7",
            "symbol": "EURUSD",
            "direction": "BUY",
            "entry_price": 1.1000,
            "close_price": 1.1050,
            "pnl": 100.0,
            "status": "CLOSED",
        }
    )

    lessons = store.all_lessons()
    assert len(lessons) == 1
    assert lessons[0]["trade_id"] == "T-7"
    assert lessons[0]["source"] == "review_auto_trigger"
    assert lessons[0]["outcome"]  # non-empty outcome


def test_record_review_lesson_is_fail_safe_on_broken_store() -> None:
    class _BrokenStore:
        def add_lesson(self, lesson):
            raise RuntimeError("store down")

    record_review_lesson(_BrokenStore(), {"trade_id": "T", "outcome": "WIN"})  # must not raise


# ---------------------------------------------------------------------------
# /learning/analytics — real data
# ---------------------------------------------------------------------------
@pytest.fixture
def _restore_lesson_store():
    """Restore the process-wide lesson store after the test."""
    original = get_lesson_store()
    yield
    set_lesson_store(original)


def test_learning_analytics_reports_real_lessons(_restore_lesson_store) -> None:
    from fastapi.testclient import TestClient

    from src.main import app

    store = InMemoryLessonStore()
    store.add_lesson({"symbol": "EURUSD", "outcome": "win", "category": "win_followed"})
    store.add_lesson({"symbol": "XAUUSD", "outcome": "loss", "category": "loss_deviated"})
    set_lesson_store(store)

    client = TestClient(app)
    resp = client.get("/learning/analytics")

    assert resp.status_code == 200
    data = resp.json()
    assert data["available"] is True
    assert data["source"] == "lesson_store"
    assert data["total"] == 2
    assert data["by_outcome"] == {"win": 1, "loss": 1}
    assert len(data["lessons"]) == 2


def test_learning_analytics_empty_is_honest(_restore_lesson_store) -> None:
    from fastapi.testclient import TestClient

    from src.main import app

    set_lesson_store(InMemoryLessonStore())

    client = TestClient(app)
    data = client.get("/learning/analytics").json()

    assert data["available"] is False
    assert data["lessons"] == []


# ---------------------------------------------------------------------------
# Lifespan wiring — persistent store + paper-close review bridge
# ---------------------------------------------------------------------------
def test_lifespan_wires_persistent_store_and_review_bridge(
    _restore_lesson_store, monkeypatch, tmp_path
) -> None:
    """Startup swaps in the JSONL store and bridges the paper-close path.

    After lifespan: (1) the process-wide store persists to
    ``LESSON_STORE_PATH``, and (2) a closed position routed through the
    default ``ReviewAutoTrigger`` writes into that *same* store — both review
    paths converge.
    """
    from fastapi.testclient import TestClient

    import src.main as main_module
    from review.auto_trigger import get_auto_trigger, set_auto_trigger

    monkeypatch.setenv("LESSON_STORE_PATH", str(tmp_path / "lessons.jsonl"))
    monkeypatch.setattr(main_module.settings, "scheduler_enabled", False)
    monkeypatch.setattr(main_module.settings, "market_feed_enabled", False)
    monkeypatch.setattr(main_module.settings, "mt5_live_data", False)

    original_trigger = get_auto_trigger()
    try:
        with TestClient(main_module.app):
            pass

        assert isinstance(get_lesson_store(), JsonlLessonStore)

        get_auto_trigger().on_position_closed(
            {
                "trade_id": "T-BRIDGE",
                "symbol": "EURUSD",
                "direction": "BUY",
                "entry_price": 1.1000,
                "close_price": 1.1050,
                "pnl": 100.0,
                "status": "CLOSED",
            }
        )

        stored = get_lesson_store().all_lessons()
        assert stored, "paper-close review must persist into the shared store"
        assert stored[0]["trade_id"] == "T-BRIDGE"
        assert stored[0]["source"] == "review_auto_trigger"
    finally:
        set_auto_trigger(original_trigger)
