# -*- coding: utf-8 -*-
"""Tests for the enforced strategy promotion gate (audit P1-5).

The promotion gate existed but was never called; a strategy could be flipped
ACTIVE with no evidence. These tests assert activation is now evidence-gated.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.strategy import endpoints as strategy_endpoints
from src.strategy.endpoints import get_strategy_registry
from src.strategy.registry import PromotionError, PromotionGate, StrategyRegistry, StrategyStatus

client = TestClient(app)


@pytest.fixture(autouse=True)
def _fresh_registry():
    strategy_endpoints._registry = StrategyRegistry()
    yield
    strategy_endpoints._registry = StrategyRegistry()


# ---------------------------------------------------------------------------
# PromotionGate logic
# ---------------------------------------------------------------------------
def test_gate_blocks_active_without_evidence() -> None:
    decision = PromotionGate().can_promote(StrategyStatus.DRAFT, StrategyStatus.ACTIVE)
    assert decision.allowed is False
    assert "evidence" in decision.reason.lower() or "validation" in decision.reason.lower()


def test_gate_allows_active_with_validation() -> None:
    decision = PromotionGate().can_promote(
        StrategyStatus.DRAFT, StrategyStatus.ACTIVE, validation_passed=True
    )
    assert decision.allowed is True


def test_gate_allows_active_with_metrics() -> None:
    decision = PromotionGate().can_promote(
        StrategyStatus.DRAFT, StrategyStatus.ACTIVE, metrics={"win_rate": 60.0}
    )
    assert decision.allowed is True


# ---------------------------------------------------------------------------
# Registry-level enforcement
# ---------------------------------------------------------------------------
def test_registry_activate_enforced_raises_without_evidence() -> None:
    registry = StrategyRegistry()
    registry.register("s", "v1", {"p": 1})
    with pytest.raises(PromotionError):
        registry.activate("s", "v1", enforce_evidence=True)


def test_registry_activate_enforced_ok_with_evidence() -> None:
    registry = StrategyRegistry()
    strategy = registry.register("s", "v1", {"p": 1})
    strategy.validation_evidence = {"passed": True}
    registry.activate("s", "v1", enforce_evidence=True)
    assert strategy.status is StrategyStatus.ACTIVE


def test_registry_activate_default_remains_permissive() -> None:
    """Internal/bootstrap callers are unaffected (backward compatible)."""
    registry = StrategyRegistry()
    registry.register("s", "v1", {"p": 1})
    registry.activate("s", "v1")  # no enforcement
    assert registry.get("s", "v1").status is StrategyStatus.ACTIVE


# ---------------------------------------------------------------------------
# HTTP endpoint enforcement
# ---------------------------------------------------------------------------
def test_endpoint_returns_409_without_evidence() -> None:
    registry = get_strategy_registry()
    strategy = registry.register("breakout", "v1", {"lookback": 50}, "desc")

    resp = client.post(f"/strategies/{strategy.strategy_id}/active", json={"active": True})
    assert resp.status_code == 409
    body = resp.json()
    assert body["error"] == "promotion_denied"
    assert body["reason"]


def test_endpoint_activates_with_inline_metrics() -> None:
    registry = get_strategy_registry()
    strategy = registry.register("breakout", "v2", {"lookback": 50}, "desc")

    resp = client.post(
        f"/strategies/{strategy.strategy_id}/active",
        json={"active": True, "metrics": {"win_rate": 55.0}},
    )
    assert resp.status_code == 200
    assert resp.json()["strategy"]["status"] == "ACTIVE"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
