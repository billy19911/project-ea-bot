# -*- coding: utf-8 -*-
"""Tests for the PRD_V2 Phase 36‑56 HTTP surface (``/v2/*``)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.system import v2_endpoints

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_singletons() -> None:
    """Reset the module-level singletons between tests for isolation."""
    for name in (
        "_circuit_breaker",
        "_recovery_store",
        "_environment_guard",
        "_account_manager",
        "_capital_allocator",
        "_incident_manager",
        "_slo_tracker",
        "_execution_quality",
        "_llm_store",
        "_llm_governance",
        "_research_inbox",
        "_lifecycle_governor",
        "_decision_store",
    ):
        setattr(v2_endpoints, name, None)
    yield


def test_circuit_breaker_state_defaults_normal() -> None:
    r = client.get("/v2/circuit-breaker")
    assert r.status_code == 200
    body = r.json()
    assert body["value"]["level"] == "normal"
    assert body["source"] == "live"


def test_circuit_breaker_trigger_and_recover() -> None:
    r = client.post(
        "/v2/circuit-breaker/trigger",
        json={"trigger": "mt5_disconnected", "reason": "test"},
    )
    assert r.status_code == 200
    assert r.json()["value"]["to"] == "entry_blocked"

    state = client.get("/v2/circuit-breaker").json()["value"]
    assert state["level"] == "entry_blocked"
    assert state["latched"] is True

    rec = client.post("/v2/circuit-breaker/recover", json={"condition_ok": True})
    assert rec.status_code == 200
    assert client.get("/v2/circuit-breaker").json()["value"]["level"] == "normal"


def test_circuit_breaker_unknown_trigger() -> None:
    r = client.post("/v2/circuit-breaker/trigger", json={"trigger": "bogus"})
    assert r.status_code == 200
    assert "error" in r.json()


def test_recovery_run() -> None:
    r = client.post("/v2/recovery/run")
    assert r.status_code == 200
    body = r.json()
    assert body["value"]["status"] in {"ready", "degraded", "halted"}


def test_environment_state() -> None:
    r = client.get("/v2/environment")
    assert r.status_code == 200
    body = r.json()["value"]
    assert body["environment"] in {"DEV", "PAPER", "DEMO", "LIVE"}
    assert "live_allowed" in body


def test_incidents_open_list_resolve() -> None:
    assert client.get("/v2/incidents").json()["value"] == []

    r = client.post(
        "/v2/incidents",
        json={"severity": "CRITICAL", "component": "recon", "trigger": "mismatch"},
    )
    assert r.status_code == 200
    inc_id = r.json()["value"]["incident_id"]

    listing = client.get("/v2/incidents").json()
    assert listing["open_critical"] is True
    assert len(listing["value"]) == 1

    resolve = client.post(f"/v2/incidents/{inc_id}/resolve")
    assert resolve.status_code == 200
    assert client.get("/v2/incidents").json()["open_critical"] is False


def test_incident_unknown_id() -> None:
    r = client.post("/v2/incidents/NOPE/resolve")
    assert r.status_code == 200
    assert "error" in r.json()


def test_slo_report_and_sample() -> None:
    base = client.get("/v2/slo").json()["value"]
    assert "slos" in base
    assert "evaluations" in base
    # No samples yet → NO_DATA evaluations.
    assert all(e["status"] in {"NO_DATA", "OK"} for e in base["evaluations"])

    r = client.post("/v2/slo/sample", json={"sli": "market_feed_freshness", "value": 1.0})
    assert r.status_code == 200
    assert r.json()["value"]["count"] == 1


def test_execution_quality_state() -> None:
    r = client.get("/v2/execution-quality")
    assert r.status_code == 200
    body = r.json()["value"]
    assert "metrics" in body
    assert "alerts" in body


def test_llm_telemetry_and_governance() -> None:
    r = client.get("/v2/llm/telemetry")
    assert r.status_code == 200
    assert r.json()["value"] == []
    g = client.get("/v2/llm/governance")
    assert g.status_code == 200


def test_dashboard_payload() -> None:
    r = client.get("/v2/dashboard")
    assert r.status_code == 200
    body = r.json()["value"]
    assert body["count"] == 16
    # Unconfigured sections must be explicit, not fake zeros.
    statuses = {s["status"] for s in body["sections"] if not s["available"]}
    assert statuses <= {"No data", "Unavailable", "Not configured", "Insufficient sample"}


def test_certification_gate() -> None:
    r = client.get("/v2/certification/gate")
    assert r.status_code == 200
    assert r.json()["value"]["status"] in {
        "NOT_READY",
        "READY_FOR_PAPER",
        "READY_FOR_DEMO",
        "READY_FOR_SMALL_LIVE",
        "PRODUCTION",
        "HALTED",
    }


def test_certification_gate_halts_on_critical_incident() -> None:
    client.post(
        "/v2/incidents",
        json={"severity": "CRITICAL", "component": "recon", "trigger": "mismatch"},
    )
    r = client.get("/v2/certification/gate")
    assert r.json()["value"]["status"] == "HALTED"


def test_research_inbox() -> None:
    r = client.get("/v2/research/inbox")
    assert r.status_code == 200
    assert r.json()["value"] == []
    assert r.json()["count"] == 0


def test_lifecycle_unknown_version() -> None:
    r = client.get("/v2/lifecycle/STRAT/1")
    assert r.status_code == 200
    assert r.json()["status"] == "NO_DATA"


def test_decision_replay_unknown() -> None:
    r = client.get("/v2/decision/NOPE/replay")
    assert r.status_code == 200
    assert r.json()["status"] == "NO_DATA"


def test_accounts_and_capital() -> None:
    assert client.get("/v2/accounts").status_code == 200
    assert client.get("/v2/capital").status_code == 200


def test_performance_intelligence_endpoint() -> None:
    r = client.get("/v2/performance-intelligence?dimension=hour")
    assert r.status_code == 200
    assert r.json()["dimension"] == "hour"
