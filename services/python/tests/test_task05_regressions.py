# -*- coding: utf-8 -*-
"""Regression tests found during TASK 05 verification.

1. Supervisor must not crash when the market feed passes a ``DetectedEvent``
   object (dataclass) instead of a dict in ``context["event"]``.
2. The full suite must not leak the process-wide review store between tests
   (``/v2/r-performance`` returned NO_DATA when another test had wired a store).
"""

from __future__ import annotations

from trading.events import DetectedEvent, EventTypes


def test_supervisor_handles_detected_event_object() -> None:
    """A DetectedEvent in context['event'] must not raise AttributeError."""
    from agents.supervisor import SupervisorAgent

    supervisor = SupervisorAgent()
    event = DetectedEvent(
        event_type=EventTypes.BREAKOUT,
        severity=0.8,
        description="range break",
        timestamp="2026-01-01T00:00:00Z",
        symbol="EURUSD",
    )
    context = {
        "event": event,
        "symbol": "EURUSD",
        "market_snapshot": {"close": [1.10, 1.11]},
    }
    # Must complete without raising (result shape is checked elsewhere).
    result = supervisor.analyze(context)
    assert isinstance(result, dict)


def test_r_performance_falls_back_to_in_process_history() -> None:
    """With NO durable store wired, seeded auto-trigger records are aggregated."""
    from fastapi.testclient import TestClient

    import src.main as main
    from src.review.advanced_review import RootCauseClassification
    from src.review.auto_trigger import ReviewRecord, set_auto_trigger
    from src.review.trade_review import TradeReviewResult

    class _Trigger:
        def recent(self, limit: int = 50):
            return [
                ReviewRecord(
                    trade_id="T-1",
                    review=TradeReviewResult(
                        trade_id="T-1",
                        outcome="WIN",
                        pnl=200.0,
                        mae=0.0,
                        mfe=2.0,
                        timing_score=50.0,
                        decision_quality_score=50.0,
                        execution_quality_score=100.0,
                        summary="x",
                    ),
                    root_cause=RootCauseClassification(
                        primary_cause="none", secondary_causes=[], confidence=1.0
                    ),
                    trade_result={
                        "direction": "BUY",
                        "entry_price": 2000.0,
                        "exit_price": 2020.0,
                        "stop_loss": 1990.0,
                    },
                    r_multiple=2.0,
                    closed_at="2025-01-01T00:00:00+00:00",
                )
            ]

    set_auto_trigger(_Trigger())  # type: ignore[arg-type]
    try:
        # Boot the app WITHOUT entering the lifespan context (the lifespan
        # wires its own ReviewAutoTrigger and would overwrite the seed).
        client = TestClient(main.app)
        set_auto_trigger(_Trigger())  # type: ignore[arg-type]
        r = client.get("/v2/r-performance?period=day")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "OK"
        assert body["overall"]["avg_r"] == 2.0
    finally:
        set_auto_trigger(None)


def test_entry_context_registry_is_isolated_between_tests() -> None:
    """The entry-context registry must never read the operator's real JSONL.

    Regression: a leaked ticket->SL record in ``logs/entry_context.jsonl`` made
    ``TradeManager`` skip a position whose ticket collided with the stale one.
    With the conftest isolation fixture the registry starts empty in every test.
    """
    from review.entry_context import get_entry_context, remember_entry_context

    # Ticket 1 with a stale SL is exactly the collision that broke
    # test_manage_handles_multiple_positions_independently.
    assert get_entry_context("1") == {}
    remember_entry_context("1", {"symbol": "XAUUSD", "stop_loss": 2495.0})
    assert get_entry_context("1")["stop_loss"] == 2495.0
    # Next test starts clean because the fixture clears both cache and store.
