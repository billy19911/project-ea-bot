# -*- coding: utf-8 -*-
"""Tests for the in-process metrics endpoint (P2-20).

``GET /observability/metrics`` exposes the real :class:`MetricsRegistry`
snapshot so the Node API control plane can surface genuine Python metrics
instead of only its own Node-side summary. The snapshot must be deterministic
and honest: an empty registry returns a valid empty snapshot, never fabricated
values.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.observability.metrics import MetricsRegistry
from src.system import endpoints as system_endpoints
from src.system.endpoints import get_metrics_registry

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_registry():
    """Give each test a fresh, empty metrics registry (no state leakage)."""
    system_endpoints._metrics_registry = MetricsRegistry()
    yield
    system_endpoints._metrics_registry = MetricsRegistry()


def test_metrics_endpoint_empty_registry_is_valid_snapshot() -> None:
    """An empty registry yields a valid, empty snapshot with source=live."""
    resp = client.get("/observability/metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "live"
    assert data["metrics"] == {"counters": {}, "gauges": {}, "histograms": {}}


def test_metrics_endpoint_returns_recorded_counter() -> None:
    """A counter stored via the registry is present in the HTTP snapshot."""
    registry = get_metrics_registry()
    registry.increment("pipeline.cycles", 2.0, labels={"symbol": "EURUSD"})
    registry.increment("pipeline.cycles", labels={"symbol": "EURUSD"})

    resp = client.get("/observability/metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "live"
    counters = data["metrics"]["counters"]
    assert counters["pipeline.cycles"]["symbol=EURUSD"] == 3.0


def test_metrics_endpoint_returns_gauges_and_histograms() -> None:
    """Gauges and histograms round-trip through the endpoint deterministically."""
    registry = get_metrics_registry()
    registry.set_gauge("supervisor.win_rate", 0.61)
    registry.observe("execution.latency_ms", 12.0, labels={"symbol": "GBPUSD"})
    registry.observe("execution.latency_ms", 18.0, labels={"symbol": "GBPUSD"})

    resp = client.get("/observability/metrics")
    data = resp.json()
    assert data["metrics"]["gauges"]["supervisor.win_rate"]["total"] == 0.61
    histogram = data["metrics"]["histograms"]["execution.latency_ms"]["symbol=GBPUSD"]
    assert histogram["count"] == 2
    assert histogram["sum"] == 30.0
    assert histogram["avg"] == 15.0
