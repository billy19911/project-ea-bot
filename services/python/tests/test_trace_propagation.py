# -*- coding: utf-8 -*-
"""Tests for PRD §26/§27 trace id propagation and the traces endpoint."""

from __future__ import annotations

from fastapi.testclient import TestClient

from src.main import app
from src.observability.traces import TraceCollector
from src.orchestration.runtime import OrchestrationRuntime, set_runtime

client = TestClient(app)


def _reset_runtime() -> OrchestrationRuntime:
    runtime = OrchestrationRuntime()
    set_runtime(runtime)
    return runtime


# ---------------------------------------------------------------------------
# POST /pipeline/run trace id echo
# ---------------------------------------------------------------------------


def test_pipeline_run_generates_trace_id_when_absent():
    _reset_runtime()
    resp = client.post("/pipeline/run", json={"event": {"event_type": "BREAKOUT"}})
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("trace_id")
    assert isinstance(data["trace_id"], str)


def test_pipeline_run_echoes_provided_trace_id():
    _reset_runtime()
    headers = {"X-Trace-Id": "abc123trace"}
    resp = client.post(
        "/pipeline/run",
        json={"event": {"event_type": "BREAKOUT"}},
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["trace_id"] == "abc123trace"


def test_pipeline_run_accepts_flat_payload_as_event():
    """Dashboard-style flat payloads become the event (not UNKNOWN)."""
    _reset_runtime()
    resp = client.post(
        "/pipeline/run",
        json={"event_type": "MARKET_SCAN", "symbol": "XAUUSD", "timeframe": "M15"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["event_type"] == "MARKET_SCAN"
    assert data["symbol"] == "XAUUSD"


# ---------------------------------------------------------------------------
# GET /observability/traces
# ---------------------------------------------------------------------------


def test_traces_endpoint_returns_recorded_traces():
    _reset_runtime()
    client.post(
        "/pipeline/run",
        json={"event": {"event_type": "BREAKOUT"}},
        headers={"X-Trace-Id": "trace-one"},
    )
    client.post(
        "/pipeline/run",
        json={"event": {"event_type": "DRAWDOWN_WARNING"}},
        headers={"X-Trace-Id": "trace-two"},
    )

    resp = client.get("/observability/traces")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] >= 2
    ids = {t["trace_id"] for t in body["traces"]}
    assert "trace-one" in ids
    assert "trace-two" in ids
    # Real data: traces carry spans with names from the pipeline.
    first = next(t for t in body["traces"] if t["trace_id"] == "trace-one")
    assert first["span_count"] >= 1
    assert all("trace_id" in s for s in first["spans"])


def test_traces_endpoint_respects_limit_and_is_newest_first():
    _reset_runtime()
    for i in range(5):
        client.post(
            "/pipeline/run",
            json={"event": {"event_type": "BREAKOUT"}},
            headers={"X-Trace-Id": f"t-{i}"},
        )
    resp = client.get("/observability/traces?limit=2")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 2
    assert [t["trace_id"] for t in body["traces"]] == ["t-4", "t-3"]


def test_traces_endpoint_empty_when_none_recorded():
    _reset_runtime()
    resp = client.get("/observability/traces")
    assert resp.status_code == 200
    assert resp.json() == {"traces": [], "count": 0}


# ---------------------------------------------------------------------------
# TraceCollector bounded history + recording
# ---------------------------------------------------------------------------


def test_trace_collector_record_pipeline_result():
    tc = TraceCollector(max_traces=10)
    result = {
        "event_id": "evt-1",
        "trace": [
            {"stage": "supervisor", "status": "ok", "detail": "done"},
            {"stage": "risk", "status": "blocked", "detail": "too big"},
        ],
    }
    trace = tc.record_pipeline_result(result, trace_id="from-header")
    assert trace.task_id == "from-header"
    assert trace.status == "error"  # blocked span → error status
    assert len(trace.spans) == 2
    assert trace.spans[0].name == "supervisor"


def test_trace_collector_bounded_history():
    tc = TraceCollector(max_traces=3)
    for i in range(6):
        tc.record_pipeline_result({"event_id": f"e{i}", "trace": []})
    assert len(tc.list_traces()) == 3
    recent = tc.recent_traces(limit=10)
    assert [t.task_id for t in recent] == ["e5", "e4", "e3"]


def test_trace_collector_empty_trace_records_span():
    tc = TraceCollector()
    trace = tc.record_pipeline_result({"event_id": "e", "trace": []})
    assert len(trace.spans) == 1
    assert trace.spans[0].name == "pipeline"
