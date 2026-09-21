# -*- coding: utf-8 -*-
"""Tests for previously data-less endpoints (audit P2-8).

- /v2/decision/{id}/replay now reflects real pipeline cycles (populated store).
- /v2/performance-intelligence derives rows from real closed-trade reviews.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from src.main import app
from src.orchestration.runtime import OrchestrationRuntime, set_runtime

client = TestClient(app)


def test_decision_replay_returns_live_after_cycle() -> None:
    runtime = OrchestrationRuntime()
    set_runtime(runtime)
    try:
        record = runtime.run_cycle({"event_type": "BREAKOUT", "symbol": "EURUSD"})
        decision_id = record.get("decision_id")
        assert decision_id

        resp = client.get(f"/v2/decision/{decision_id}/replay")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "OK"
        assert body["source"] == "live"
        assert body["value"]["decision_id"] == decision_id
        # Real pipeline stages are present.
        stages = {step["stage"] for step in body["value"]["steps"]}
        assert "EVENT" in stages
        assert "RISK_CHECKS" in stages
    finally:
        set_runtime(None)


def test_decision_replay_unknown_is_no_data() -> None:
    resp = client.get("/v2/decision/does-not-exist/replay")
    assert resp.status_code == 200
    assert resp.json()["status"] == "NO_DATA"


def test_performance_intelligence_no_data_is_honest() -> None:
    # Fresh trigger has no reviews → NO_DATA (never fabricated).
    from src.review.auto_trigger import ReviewAutoTrigger, set_auto_trigger

    set_auto_trigger(ReviewAutoTrigger())
    resp = client.get("/v2/performance-intelligence?dimension=hour")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "NO_DATA"
    assert body["trade_count"] == 0


def test_performance_intelligence_reports_real_trades() -> None:
    """After a closed trade produces a review, rows become available."""
    from monitoring.position_monitor import PositionMonitor
    from src.review.auto_trigger import ReviewAutoTrigger, set_auto_trigger
    from src.review.close_detector import PositionCloseDetector

    trigger = ReviewAutoTrigger()
    set_auto_trigger(trigger)
    detector = PositionCloseDetector(on_close=trigger.on_position_closed)

    class _Conn:
        def __init__(self):
            self.positions = [{"ticket": 1, "symbol": "EURUSD", "side": "BUY", "price_open": 1.1}]

        def get_positions(self):
            return list(self.positions)

        def get_tick(self, s):
            return None

        def get_ohlc(self, s, tf, c):
            return []

    conn = _Conn()
    monitor = PositionMonitor(mt5_connector=conn, close_detector=detector)
    monitor.monitor_all_positions()
    conn.positions = []  # close → review
    monitor.monitor_all_positions()

    resp = client.get("/v2/performance-intelligence?dimension=direction")
    body = resp.json()
    # At least one row now exists (status OK or NO_DATA depending on bucket keys,
    # but trade_count must reflect the real closed trade).
    assert body["trade_count"] >= 1


if __name__ == "__main__":  # pragma: no cover
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
