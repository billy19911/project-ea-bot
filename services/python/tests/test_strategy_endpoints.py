# -*- coding: utf-8 -*-
"""Tests for the strategy-registry HTTP endpoints (EPIC 13).

These endpoints back the Node API control plane (Strategy Center). They expose
*real* :class:`StrategyRegistry` state — lifecycle/governance metadata (PRD_V2
§19) — and must never fabricate rows. A fresh registry therefore yields an
honest empty list with ``source="live"``; every success response carries
``source="live"``.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.strategy import endpoints as strategy_endpoints
from src.strategy.endpoints import get_strategy_registry, register_live_strategy
from src.strategy.registry import StrategyRegistry
from src.trading.engine import DEFAULT_CONFIG

client = TestClient(app)


@pytest.fixture(autouse=True)
def _fresh_registry():
    """Give each test a fresh registry so state does not leak between tests."""
    strategy_endpoints._registry = StrategyRegistry()
    yield
    strategy_endpoints._registry = StrategyRegistry()


# ---------------------------------------------------------------------------
# GET /strategies
# ---------------------------------------------------------------------------
def test_list_empty_registry_is_honest() -> None:
    """A fresh registry returns an empty list with source=live (no seed data)."""
    resp = client.get("/strategies")
    assert resp.status_code == 200
    data = resp.json()
    assert data["strategies"] == []
    assert data["source"] == "live"


def test_list_shows_active_and_retired_versions() -> None:
    """Activating v2 retires the previously-active v1 (13.04 lifecycle)."""
    registry = get_strategy_registry()
    registry.register("ema_cross", "v1", {"ema_fast": 9}, "first")
    registry.register("ema_cross", "v2", {"ema_fast": 12}, "second")
    registry.activate("ema_cross", "v1")
    registry.activate("ema_cross", "v2")

    resp = client.get("/strategies")
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "live"

    statuses = {(s["name"], s["version"]): s["status"] for s in data["strategies"]}
    assert statuses[("ema_cross", "v2")] == "ACTIVE"
    assert statuses[("ema_cross", "v1")] == "RETIRED"

    # Sorted by (name, version).
    versions = [s["version"] for s in data["strategies"]]
    assert versions == ["v1", "v2"]


# ---------------------------------------------------------------------------
# GET /strategies/{id}
# ---------------------------------------------------------------------------
def test_detail_by_strategy_id() -> None:
    registry = get_strategy_registry()
    strategy = registry.register("momentum", "v1", {"rsi": 14}, "desc")

    resp = client.get(f"/strategies/{strategy.strategy_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "live"
    assert data["strategy"]["strategy_id"] == strategy.strategy_id
    assert data["strategy"]["name"] == "momentum"


def test_detail_unknown_is_404() -> None:
    resp = client.get("/strategies/does_not_exist")
    assert resp.status_code == 404
    assert resp.json()["error"] == "strategy_not_found"


# ---------------------------------------------------------------------------
# POST /strategies/{id}/active
# ---------------------------------------------------------------------------
def test_activate_then_deactivate() -> None:
    registry = get_strategy_registry()
    strategy = registry.register("breakout", "v1", {"lookback": 50}, "desc")

    resp = client.post(f"/strategies/{strategy.strategy_id}/active", json={"active": True})
    assert resp.status_code == 200
    data = resp.json()
    assert data["strategy"]["status"] == "ACTIVE"
    assert "diaktifkan" in data["message"]

    resp = client.post(f"/strategies/{strategy.strategy_id}/active", json={"active": False})
    assert resp.status_code == 200
    data = resp.json()
    assert data["strategy"]["status"] == "RETIRED"
    assert "dinonaktifkan" in data["message"]


def test_toggle_invalid_body_is_400() -> None:
    registry = get_strategy_registry()
    strategy = registry.register("breakout", "v1", {"lookback": 50}, "desc")

    resp = client.post(f"/strategies/{strategy.strategy_id}/active", json={"active": "yes"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "active must be boolean"


def test_toggle_unknown_is_404() -> None:
    resp = client.post("/strategies/nope/active", json={"active": True})
    assert resp.status_code == 404
    assert resp.json()["error"] == "strategy_not_found"


# ---------------------------------------------------------------------------
# register_live_strategy
# ---------------------------------------------------------------------------
def test_register_live_strategy_registers_real_default_config() -> None:
    register_live_strategy()

    registry = get_strategy_registry()
    strategy = registry.get("technical_analysis", "v1.0.0")
    assert strategy is not None
    assert strategy.parameters == dict(DEFAULT_CONFIG)
    assert strategy.status.value == "ACTIVE"
    assert registry.get_active_version("technical_analysis") is strategy


def test_register_live_strategy_is_idempotent() -> None:
    register_live_strategy()
    first = get_strategy_registry().get("technical_analysis", "v1.0.0")

    # Calling again must not raise (duplicate register) nor replace the record.
    register_live_strategy()
    second = get_strategy_registry().get("technical_analysis", "v1.0.0")

    assert second is first
    live = [
        s
        for s in get_strategy_registry().list_all()
        if (s.name, s.version) == ("technical_analysis", "v1.0.0")
    ]
    assert len(live) == 1
