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
