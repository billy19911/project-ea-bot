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

    # Audit P1-5: reaching ACTIVE now requires evidence (validation or metrics).
    resp = client.post(
        f"/strategies/{strategy.strategy_id}/active",
        json={"active": True, "validation_passed": True},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["strategy"]["status"] == "ACTIVE"
    assert "diaktifkan" in data["message"]

    resp = client.post(
        f"/strategies/{strategy.strategy_id}/active", json={"active": False}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["strategy"]["status"] == "RETIRED"
    assert "dinonaktifkan" in data["message"]


def test_toggle_invalid_body_is_400() -> None:
    registry = get_strategy_registry()
    strategy = registry.register("breakout", "v1", {"lookback": 50}, "desc")

    resp = client.post(
        f"/strategies/{strategy.strategy_id}/active", json={"active": "yes"}
    )
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


# ---------------------------------------------------------------------------
# get_active_strategy_config helper (StrategyRegistry → TradingEngine bridge)
# ---------------------------------------------------------------------------
def test_get_active_strategy_config_returns_none_when_empty() -> None:
    """No active strategy → None (engine falls back to DEFAULT_CONFIG)."""
    assert strategy_endpoints.get_active_strategy_config() is None


def test_get_active_strategy_config_returns_parameters_when_active() -> None:
    """When a strategy is active, its parameters flow out via the helper."""
    registry = get_strategy_registry()
    registry.register("my_strat", "v1", {"fast": 9, "slow": 21}, "desc")
    registry.activate("my_strat", "v1")

    config = strategy_endpoints.get_active_strategy_config()
    assert config == {"fast": 9, "slow": 21}


def test_get_active_strategy_config_returns_none_when_retired() -> None:
    """Retiring the active strategy yields None again."""
    registry = get_strategy_registry()
    registry.register("my_strat", "v1", {"fast": 9}, "desc")
    registry.activate("my_strat", "v1")
    registry.retire("my_strat", "v1")

    assert strategy_endpoints.get_active_strategy_config() is None


# ---------------------------------------------------------------------------
# GET /strategies/active
# ---------------------------------------------------------------------------
def test_get_active_strategy_404_when_empty() -> None:
    resp = client.get("/strategies/active")
    assert resp.status_code == 404
    assert resp.json()["error"] == "no_active_strategy"


def test_get_active_strategy_returns_config() -> None:
    registry = get_strategy_registry()
    registry.register("my_strat", "v1", {"fast": 9}, "desc")
    registry.activate("my_strat", "v1")

    resp = client.get("/strategies/active")
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "live"
    assert data["config"] == {"fast": 9}
    assert data["strategy"]["name"] == "my_strat"
    assert data["strategy"]["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# POST /strategies  (create)
# ---------------------------------------------------------------------------
def test_create_strategy_201() -> None:
    resp = client.post(
        "/strategies",
        json={
            "name": "ema_cross",
            "version": "v1",
            "parameters": {"fast": 9},
            "description": "EMA cross",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["source"] == "live"
    assert data["strategy"]["name"] == "ema_cross"
    assert data["strategy"]["version"] == "v1"
    assert data["strategy"]["parameters"] == {"fast": 9}
    assert data["strategy"]["status"] == "DRAFT"


def test_create_strategy_409_on_duplicate() -> None:
    client.post("/strategies", json={"name": "dup", "version": "v1"})
    resp = client.post("/strategies", json={"name": "dup", "version": "v1"})
    assert resp.status_code == 409
    assert resp.json()["error"] == "strategy_exists"


def test_create_strategy_400_missing_name() -> None:
    resp = client.post("/strategies", json={"version": "v1"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "name is required"


def test_create_strategy_400_missing_version() -> None:
    resp = client.post("/strategies", json={"name": "x"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "version is required"


def test_create_strategy_defaults_empty_parameters() -> None:
    resp = client.post("/strategies", json={"name": "np", "version": "v1"})
    assert resp.status_code == 201
    assert resp.json()["strategy"]["parameters"] == {}


# ---------------------------------------------------------------------------
# PATCH /strategies/{id}  (edit)
# ---------------------------------------------------------------------------
def test_edit_strategy_updates_description() -> None:
    create = client.post("/strategies", json={"name": "e", "version": "v1"}).json()
    sid = create["strategy"]["strategy_id"]

    resp = client.patch(f"/strategies/{sid}", json={"description": "updated"})
    assert resp.status_code == 200
    assert resp.json()["strategy"]["description"] == "updated"


def test_edit_strategy_updates_parameters() -> None:
    create = client.post("/strategies", json={"name": "e", "version": "v1"}).json()
    sid = create["strategy"]["strategy_id"]

    resp = client.patch(f"/strategies/{sid}", json={"parameters": {"rsi": 14}})
    assert resp.status_code == 200
    assert resp.json()["strategy"]["parameters"] == {"rsi": 14}


def test_edit_strategy_404_unknown_id() -> None:
    resp = client.patch("/strategies/nope", json={"description": "x"})
    assert resp.status_code == 404
    assert resp.json()["error"] == "strategy_not_found"


def test_edit_strategy_409_parameters_frozen_when_active() -> None:
    """ACTIVE strategy parameters are frozen — PATCH returns 409."""
    registry = get_strategy_registry()
    strategy = registry.register("frozen", "v1", {"a": 1}, "desc")
    registry.activate("frozen", "v1")

    resp = client.patch(
        f"/strategies/{strategy.strategy_id}", json={"parameters": {"a": 2}}
    )
    assert resp.status_code == 409
    assert resp.json()["error"] == "parameters_frozen"
    # And no partial mutation leaked through.
    assert dict(strategy.parameters) == {"a": 1}


def test_edit_strategy_allows_non_param_fields_on_active() -> None:
    """Non-parameter fields (description, rationale) are still editable on ACTIVE."""
    registry = get_strategy_registry()
    strategy = registry.register("frozen", "v1", {"a": 1}, "desc")
    registry.activate("frozen", "v1")

    resp = client.patch(
        f"/strategies/{strategy.strategy_id}",
        json={"description": "new desc", "rationale": "because"},
    )
    assert resp.status_code == 200
    data = resp.json()["strategy"]
    assert data["description"] == "new desc"
    assert data["rationale"] == "because"
    assert data["parameters"] == {"a": 1}  # untouched


def test_edit_strategy_400_bad_types() -> None:
    create = client.post("/strategies", json={"name": "bt", "version": "v1"}).json()
    sid = create["strategy"]["strategy_id"]

    resp = client.patch(f"/strategies/{sid}", json={"parameters": "not-a-dict"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "parameters must be an object"


# ---------------------------------------------------------------------------
# DELETE /strategies/{id}  (retire)
# ---------------------------------------------------------------------------
def test_delete_strategy_retires() -> None:
    create = client.post("/strategies", json={"name": "d", "version": "v1"}).json()
    sid = create["strategy"]["strategy_id"]

    resp = client.delete(f"/strategies/{sid}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["strategy"]["status"] == "RETIRED"
    assert "dihapus" in data["message"]
    assert data["source"] == "live"


def test_delete_strategy_404_unknown_id() -> None:
    resp = client.delete("/strategies/nope")
    assert resp.status_code == 404
    assert resp.json()["error"] == "strategy_not_found"


def test_delete_strategy_retire_then_config_is_none() -> None:
    """Retiring via DELETE clears the active config (engine wiring)."""
    registry = get_strategy_registry()
    strategy = registry.register("rt", "v1", {"x": 1}, "desc")
    registry.activate("rt", "v1")

    resp = client.delete(f"/strategies/{strategy.strategy_id}")
    assert resp.status_code == 200
    assert strategy_endpoints.get_active_strategy_config() is None
