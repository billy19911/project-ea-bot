# -*- coding: utf-8 -*-
"""Tests for the read-only system status endpoints (P0-3).

These endpoints back the Node API control plane and must report *real*
in-process state honestly — never fabricated demo data. The model discovery
path is exercised with a stub gateway client so no network is used.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.system import endpoints as system_endpoints
from src.system.endpoints import get_audit_log, get_model_registry

client = TestClient(app)


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------
class _StubModel:
    def __init__(self, model_id: str) -> None:
        self.id = model_id


@pytest.fixture(autouse=True)
def _reset_registry():
    """Give each test a fresh registry so discovery state does not leak."""
    system_endpoints._model_registry = system_endpoints.ModelRegistry()
    yield
    system_endpoints._model_registry = system_endpoints.ModelRegistry()


# ---------------------------------------------------------------------------
# /ai/models
# ---------------------------------------------------------------------------
def test_ai_models_defaults_when_gateway_unreachable(monkeypatch) -> None:
    """A failed discovery falls back to defaults with source=defaults."""
    registry = get_model_registry()
    monkeypatch.setattr(
        registry,
        "_fetch_gateway_models",
        lambda client: (_ for _ in ()).throw(RuntimeError("down")),
    )

    resp = client.get("/ai/models")
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "defaults"
    assert len(data["models"]) >= 6
    assert data["health"]["state"] == "DISCONNECTED"
    # Shape is stable for the frontend.
    first = data["models"][0]
    assert {"id", "provider", "context", "is_free"} <= set(first)


def test_ai_models_from_gateway(monkeypatch) -> None:
    """A reachable gateway yields source=gateway and normalized models."""
    registry = get_model_registry()
    monkeypatch.setattr(
        registry,
        "_fetch_gateway_models",
        lambda client: [_StubModel("openai/gpt-4o-mini"), _StubModel("custom/only:free")],
    )

    resp = client.get("/ai/models")
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "gateway"
    names = {m["id"] for m in data["models"]}
    assert names == {"openai/gpt-4o-mini", "custom/only:free"}
    assert data["health"]["state"] == "CONNECTED"


def test_ai_models_discovery_never_raises(monkeypatch) -> None:
    """Even if discovery raises, the endpoint still returns 200."""
    registry = get_model_registry()
    monkeypatch.setattr(
        registry,
        "discover_from_gateway",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("exploded")),
    )

    resp = client.get("/ai/models")
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "defaults"


# ---------------------------------------------------------------------------
# /telegram/status
# ---------------------------------------------------------------------------
@pytest.fixture
def _fresh_telegram_gateway():
    """Force the shared gateway singleton to rebuild from the test's env."""
    from src.telegram.notifier import set_gateway

    set_gateway(None)
    yield
    set_gateway(None)


def test_telegram_status_unconfigured(monkeypatch, _fresh_telegram_gateway) -> None:
    """Without a token/allowlist the gateway reports not connected."""
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_ALLOWED_CHAT_IDS", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_IDS", raising=False)

    resp = client.get("/telegram/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["connected"] is False
    assert data["configured"] is False
    assert data["enabled"] is False
    assert data["source"] == "live"


def test_telegram_status_configured_connected(monkeypatch, _fresh_telegram_gateway) -> None:
    """Token + allowlist present → a real transport is configured → connected."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:ABC")
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "111,222")

    resp = client.get("/telegram/status")
    data = resp.json()
    assert data["configured"] is True
    assert data["enabled"] is True
    assert data["has_token"] is True
    assert data["allowlist_size"] == 2
    # A real HTTP transport was built from the token → honest connected=true.
    assert data["connected"] is True


# ---------------------------------------------------------------------------
# /audit/events
# ---------------------------------------------------------------------------
def test_audit_events_empty_is_honest() -> None:
    resp = client.get("/audit/events")
    assert resp.status_code == 200
    data = resp.json()
    assert data["events"] == []
    assert data["count"] == 0
    assert data["source"] == "live"


def test_audit_events_returns_recorded() -> None:
    get_audit_log().append("supervisor", "DECISION_APPROVED", "DEC-77", {"ok": True})

    resp = client.get("/audit/events")
    data = resp.json()
    assert data["count"] == 1
    assert data["events"][0]["actor"] == "supervisor"
    assert data["events"][0]["action"] == "DECISION_APPROVED"
    assert data["source"] == "live"


# ---------------------------------------------------------------------------
# /decisions
# ---------------------------------------------------------------------------
def test_decisions_empty_is_honest() -> None:
    resp = client.get("/decisions")
    assert resp.status_code == 200
    data = resp.json()
    assert data["decisions"] == []
    assert data["count"] == 0
    assert data["source"] == "live"


def test_decisions_returns_recorded(monkeypatch) -> None:
    """A recorded run_cycle result shows up in /decisions (newest first)."""
    from src.orchestration.runtime import get_runtime

    runtime = get_runtime()
    runtime._decisions.clear()
    runtime._record_decision({"event_id": "evt_1", "decision": "BUY", "status": "EXECUTED"})
    runtime._record_decision({"event_id": "evt_2", "decision": "WAIT", "status": "WAIT"})

    resp = client.get("/decisions")
    data = resp.json()
    assert data["count"] == 2
    assert data["decisions"][0]["event_id"] == "evt_2"  # newest first
    assert data["decisions"][1]["event_id"] == "evt_1"
    assert data["source"] == "live"
    runtime._decisions.clear()


# ---------------------------------------------------------------------------
# /tasks
# ---------------------------------------------------------------------------
def test_tasks_empty_is_honest() -> None:
    resp = client.get("/tasks")
    assert resp.status_code == 200
    data = resp.json()
    assert data["tasks"] == []
    assert data["source"] == "live"
    assert data["counts"]["running"] == 0


# ---------------------------------------------------------------------------
# /learning/analytics
# ---------------------------------------------------------------------------
def test_learning_analytics_unavailable() -> None:
    resp = client.get("/learning/analytics")
    assert resp.status_code == 200
    data = resp.json()
    assert data["available"] is False
    assert data["source"] == "unavailable"
    assert data["by_hour"] == []
    assert data["supervisor_kpis"] is None
