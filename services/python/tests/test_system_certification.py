# -*- coding: utf-8 -*-
"""Tests for the Phase 31 system certification endpoint (/system/certify)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from src.main import app

client = TestClient(app)

EXPECTED_COMPONENTS = {
    "database",
    "python_service",
    "node_service",
    "web_service",
    "mt5_connector",
    "market_feed",
    "agent_registry",
    "supervisor",
    "risk_engine",
    "execution",
    "reconciliation",
    "learning",
    "telegram",
    "observability",
}

VALID_STATUSES = {"PASS", "WARN", "FAIL", "NOT_CONFIGURED", "NOT_AVAILABLE"}


def test_certify_returns_all_components() -> None:
    res = client.get("/certify")
    assert res.status_code == 200
    body = res.json()
    assert "components" in body
    names = {c["component"] for c in body["components"]}
    assert EXPECTED_COMPONENTS <= names


def test_certify_component_shape() -> None:
    res = client.get("/certify")
    for c in res.json()["components"]:
        assert set(c) == {"component", "status", "version", "verified_at", "details"}
        assert c["status"] in VALID_STATUSES
        assert isinstance(c["details"], list)


def test_certify_never_raises() -> None:
    # Calling twice must be stable (no cached crash)
    assert client.get("/certify").status_code == 200
    assert client.get("/certify").status_code == 200


# ---------------------------------------------------------------------------
# check_node_service — real probe (no hardcoded stub)
# ---------------------------------------------------------------------------


def test_node_service_probes_and_passes_when_reachable(monkeypatch) -> None:
    """A reachable Node /health URL yields PASS (not a hardcoded NOT_CONFIGURED)."""
    import io
    import urllib.request

    from src.system import certification

    class _Resp(io.BytesIO):
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setenv("NODE_API_URL", "http://127.0.0.1:9999")
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _Resp(b"{}"))

    rec = certification.check_node_service()
    assert rec["component"] == "node_service"
    assert rec["status"] == "PASS"


def test_node_service_reports_not_configured_when_unreachable(monkeypatch) -> None:
    """An unreachable Node URL is honestly NOT_CONFIGURED (never a false PASS)."""
    import urllib.request

    from src.system import certification

    def _boom(*a, **k):
        raise OSError("connection refused")

    monkeypatch.setenv("NODE_API_URL", "http://127.0.0.1:9999")
    monkeypatch.setattr(urllib.request, "urlopen", _boom)

    rec = certification.check_node_service()
    assert rec["status"] == "NOT_CONFIGURED"


# ---------------------------------------------------------------------------
# check_database — actionable message when the driver is missing
# ---------------------------------------------------------------------------


def test_database_check_is_stable_and_shaped() -> None:
    """check_database must never raise and returns the standard record shape."""
    from src.system import certification

    rec = certification.check_database()
    assert rec["component"] == "database"
    assert rec["status"] in VALID_STATUSES
    assert isinstance(rec["details"], list)
