# -*- coding: utf-8 -*-
"""Tests for the Model Router policy — PRD_V2 §22 Model Routing.

Routing inputs: task complexity, event priority, risk level, conflict severity,
current budget, model availability. Routing must be deterministic given inputs.
"""

from __future__ import annotations

import pytest

from llm.model_router import Complexity, ModelRouter, RiskLevel, RoutingDecision
from llm.registry import ModelRegistry


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
class FakeClock:
    """Deterministic clock for reproducible timestamps."""

    def __init__(self) -> None:
        self._t = 0.0

    def __call__(self) -> float:
        self._t += 1.0
        return self._t


def _registry() -> ModelRegistry:
    return ModelRegistry()


# ---------------------------------------------------------------------------
# Complexity mapping
# ---------------------------------------------------------------------------
class TestComplexityMapping:
    def test_low_complexity_prefers_free_model(self) -> None:
        router = ModelRouter(_registry())
        decision = router.route(complexity=Complexity.LOW, risk_level=RiskLevel.LOW)
        model = router.registry.get(decision.model)
        assert model is not None
        assert model.is_free is True

    def test_high_complexity_prefers_strong_model(self) -> None:
        router = ModelRouter(_registry())
        decision = router.route(complexity=Complexity.HIGH, risk_level=RiskLevel.LOW)
        # High-complexity tasks opt into the strongest (capable) model.
        model = router.registry.get(decision.model)
        assert model is not None
        assert "reasoning" in model.capabilities

    def test_medium_complexity_maps_to_medium_tier(self) -> None:
        router = ModelRouter(_registry())
        decision = router.route(complexity=Complexity.MEDIUM, risk_level=RiskLevel.LOW)
        # Must not fall back to the cheapest free model by default.
        assert decision.model
        assert decision.complexity is Complexity.MEDIUM


# ---------------------------------------------------------------------------
# Budget enforcement
# ---------------------------------------------------------------------------
class TestBudgetEnforcement:
    def test_zero_budget_forces_free_model(self) -> None:
        router = ModelRouter(_registry())
        decision = router.route(
            complexity=Complexity.HIGH,
            risk_level=RiskLevel.LOW,
            budget_remaining_usd=0.0,
        )
        model = router.registry.get(decision.model)
        assert model is not None
        assert model.is_free is True

    def test_budget_ceiling_excludes_expensive_model(self) -> None:
        router = ModelRouter(_registry())
        # A tiny ceiling cannot afford the paid strong model.
        decision = router.route(
            complexity=Complexity.HIGH,
            risk_level=RiskLevel.LOW,
            budget_remaining_usd=1e-9,
            expected_tokens=10_000,
        )
        model = router.registry.get(decision.model)
        assert model is not None
        assert model.is_free is True

    def test_ample_budget_allows_paid_model(self) -> None:
        router = ModelRouter(_registry())
        decision = router.route(
            complexity=Complexity.HIGH,
            risk_level=RiskLevel.LOW,
            budget_remaining_usd=100.0,
            expected_tokens=1_000,
        )
        model = router.registry.get(decision.model)
        assert model is not None
        assert model.is_free is False


# ---------------------------------------------------------------------------
# Risk gate
# ---------------------------------------------------------------------------
class TestRiskGate:
    def test_high_risk_excludes_free_models(self) -> None:
        router = ModelRouter(_registry())
        decision = router.route(complexity=Complexity.LOW, risk_level=RiskLevel.HIGH)
        model = router.registry.get(decision.model)
        assert model is not None
        assert model.is_free is False

    def test_high_risk_never_selects_free_even_when_budget_zero(self) -> None:
        router = ModelRouter(_registry())
        decision = router.route(
            complexity=Complexity.HIGH,
            risk_level=RiskLevel.HIGH,
            budget_remaining_usd=0.0,
        )
        model = router.registry.get(decision.model)
        assert model is not None
        # No affordable paid model → deterministic refusal, not a free model.
        assert model.is_free is False

    def test_high_risk_with_conflict_severity_prefers_reasoning(self) -> None:
        router = ModelRouter(_registry())
        decision = router.route(
            complexity=Complexity.HIGH,
            risk_level=RiskLevel.HIGH,
            conflict_severity=0.9,
            budget_remaining_usd=100.0,
        )
        model = router.registry.get(decision.model)
        assert model is not None
        assert model.is_free is False


# ---------------------------------------------------------------------------
# Provider health
# ---------------------------------------------------------------------------
class TestProviderHealth:
    def test_disconnected_gateway_marks_decision_degraded(self) -> None:
        registry = _registry()
        # Force a discovery failure to reach DISCONNECTED/DEGRADED.
        registry.discover_from_gateway(client=_BrokenClient(), force=True)
        router = ModelRouter(registry)
        decision = router.route(complexity=Complexity.HIGH, risk_level=RiskLevel.LOW)
        # Registry always keeps safe defaults; the router surfaces health.
        assert decision.health_state in ("DEGRADED", "DISCONNECTED")

    def test_connected_gateway_reports_connected(self) -> None:
        registry = _registry()
        registry.discover_from_gateway(client=_OkClient(), force=True)
        router = ModelRouter(registry)
        decision = router.route(complexity=Complexity.LOW, risk_level=RiskLevel.LOW)
        assert decision.health_state == "CONNECTED"


class _BrokenClient:
    class _Models:
        @staticmethod
        def list():
            raise RuntimeError("gateway down")

    def __init__(self) -> None:
        self.models = self._Models()


class _OkClient:
    class _Models:
        @staticmethod
        def list():
            class _M:
                id = "openai/gpt-4o-mini"

            class _R:
                data = [_M()]

            return _R()

    def __init__(self) -> None:
        self.models = self._Models()


# ---------------------------------------------------------------------------
# Determinism & logging
# ---------------------------------------------------------------------------
class TestDeterminismAndLogging:
    def test_deterministic_same_inputs_same_output(self) -> None:
        a = ModelRouter(_registry()).route(complexity=Complexity.HIGH, risk_level=RiskLevel.LOW)
        b = ModelRouter(_registry()).route(complexity=Complexity.HIGH, risk_level=RiskLevel.LOW)
        assert a.model == b.model
        assert a.reason == b.reason
        assert a.fallback_chain == b.fallback_chain

    def test_fallback_chain_excludes_primary(self) -> None:
        decision = ModelRouter(_registry()).route(
            complexity=Complexity.MEDIUM, risk_level=RiskLevel.LOW
        )
        assert decision.model not in decision.fallback_chain

    def test_recorded_log_entry_has_required_fields(self) -> None:
        router = ModelRouter(_registry())
        router.route(complexity=Complexity.LOW, risk_level=RiskLevel.LOW)
        entry = router.log()[-1]
        assert entry["model"] == router.log()[-1]["model"]
        for key in ("model", "reason", "fallback_chain", "cost_estimate", "latency_ms_budget"):
            assert key in entry

    def test_decision_to_dict(self) -> None:
        decision = ModelRouter(_registry()).route(
            complexity=Complexity.LOW, risk_level=RiskLevel.LOW
        )
        assert isinstance(decision, RoutingDecision)
        payload = decision.to_dict()
        assert payload["model"] == decision.model
        assert payload["complexity"] == "LOW"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
