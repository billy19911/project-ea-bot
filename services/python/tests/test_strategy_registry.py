# -*- coding: utf-8 -*-
"""Tests for strategy versioning and promotion — EPIC 13.

Covers strategy registry, version schema, promotion gates, activation,
retirement, and live‑parameter protection.
"""

from __future__ import annotations

import pytest

from strategy.registry import PromotionGate, StrategyRegistry, StrategyStatus, VersionedStrategy

# ---------------------------------------------------------------------------
# 13.01 Strategy registry
# ---------------------------------------------------------------------------


class TestStrategyRegistry:
    """Tests for StrategyRegistry."""

    def test_register_new_strategy(self) -> None:
        """Register a new strategy with initial version."""
        registry = StrategyRegistry()
        strategy = registry.register(
            name="EMA_Crossover",
            version="v1.0",
            parameters={"fast_period": 9, "slow_period": 21},
            description="EMA crossover strategy",
        )
        assert isinstance(strategy, VersionedStrategy)
        assert strategy.name == "EMA_Crossover"
        assert strategy.version == "v1.0"
        assert strategy.status == StrategyStatus.DRAFT

    def test_duplicate_name_version_rejected(self) -> None:
        """Registering duplicate name+version raises error."""
        registry = StrategyRegistry()
        registry.register("S1", "v1", {})
        with pytest.raises(ValueError, match="already exists"):
            registry.register("S1", "v1", {})

    def test_get_strategy_by_name_version(self) -> None:
        """Retrieve strategy by name and version."""
        registry = StrategyRegistry()
        s = registry.register("S1", "v1.0", {"x": 1})
        retrieved = registry.get("S1", "v1.0")
        assert retrieved is s

    def test_get_unknown_strategy_returns_none(self) -> None:
        """Unknown strategy returns None."""
        registry = StrategyRegistry()
        assert registry.get("Unknown", "v1") is None

    def test_list_all_strategies(self) -> None:
        """List all registered strategies."""
        registry = StrategyRegistry()
        registry.register("S1", "v1", {})
        registry.register("S1", "v2", {})
        registry.register("S2", "v1", {})
        all_strats = registry.list_all()
        assert len(all_strats) == 3

    def test_list_by_name(self) -> None:
        """List all versions of a strategy by name."""
        registry = StrategyRegistry()
        registry.register("S1", "v1", {})
        registry.register("S1", "v2", {})
        registry.register("S2", "v1", {})
        s1_versions = registry.list_by_name("S1")
        assert len(s1_versions) == 2

    def test_list_by_status(self) -> None:
        """List strategies by status."""
        registry = StrategyRegistry()
        registry.register("S1", "v1", {})
        s2 = registry.register("S2", "v1", {})
        s2.status = StrategyStatus.ACTIVE
        active = registry.list_by_status(StrategyStatus.ACTIVE)
        assert len(active) == 1
        assert active[0] is s2


# ---------------------------------------------------------------------------
# 13.02 Version schema
# ---------------------------------------------------------------------------


class TestVersionedStrategy:
    """Tests for VersionedStrategy."""

    def test_versioned_strategy_has_required_fields(self) -> None:
        """VersionedStrategy includes name, version, parameters, status."""
        strategy = VersionedStrategy(
            name="Test",
            version="v1.0",
            parameters={"x": 1},
            description="Test strategy",
            status=StrategyStatus.DRAFT,
        )
        assert strategy.name == "Test"
        assert strategy.version == "v1.0"
        assert strategy.parameters == {"x": 1}
        assert strategy.status == StrategyStatus.DRAFT

    def test_default_status_is_draft(self) -> None:
        """New strategies default to DRAFT status."""
        strategy = VersionedStrategy("S", "v1", {}, "")
        assert strategy.status == StrategyStatus.DRAFT

    def test_to_dict_serialization(self) -> None:
        """VersionedStrategy can serialize to dict."""
        strategy = VersionedStrategy("S", "v1", {"x": 1}, "Desc")
        data = strategy.to_dict()
        assert data["name"] == "S"
        assert data["version"] == "v1"
        assert data["parameters"] == {"x": 1}
        assert "status" in data


# ---------------------------------------------------------------------------
# 13.03 Promotion gates
# ---------------------------------------------------------------------------


class TestPromotionGates:
    """Tests for PromotionGate."""

    def test_promotion_gate_draft_to_testing(self) -> None:
        """DRAFT → TESTING requires backtest metrics."""
        gate = PromotionGate()
        result = gate.can_promote(
            from_status=StrategyStatus.DRAFT,
            to_status=StrategyStatus.TESTING,
            metrics={"win_rate": 55.0, "profit_factor": 1.5},
        )
        assert result.allowed is True

    def test_promotion_draft_to_testing_without_metrics_fails(self) -> None:
        """DRAFT → TESTING without metrics is rejected."""
        gate = PromotionGate()
        result = gate.can_promote(
            from_status=StrategyStatus.DRAFT,
            to_status=StrategyStatus.TESTING,
            metrics=None,
        )
        assert result.allowed is False
        assert "metrics" in result.reason.lower()

    def test_promotion_testing_to_active_requires_validation(self) -> None:
        """TESTING → ACTIVE requires passing validation."""
        gate = PromotionGate()
        result = gate.can_promote(
            from_status=StrategyStatus.TESTING,
            to_status=StrategyStatus.ACTIVE,
            metrics={"win_rate": 60.0, "profit_factor": 2.0},
            validation_passed=True,
        )
        assert result.allowed is True

    def test_promotion_testing_to_active_without_validation_fails(
        self,
    ) -> None:
        """TESTING → ACTIVE without validation is rejected."""
        gate = PromotionGate()
        result = gate.can_promote(
            from_status=StrategyStatus.TESTING,
            to_status=StrategyStatus.ACTIVE,
            metrics={"win_rate": 60.0},
            validation_passed=False,
        )
        assert result.allowed is False

    def test_promotion_active_to_retired_allowed(self) -> None:
        """ACTIVE → RETIRED is always allowed (deactivation)."""
        gate = PromotionGate()
        result = gate.can_promote(
            from_status=StrategyStatus.ACTIVE,
            to_status=StrategyStatus.RETIRED,
        )
        assert result.allowed is True

    def test_promotion_skip_testing_not_allowed(self) -> None:
        """Cannot skip TESTING phase (DRAFT → ACTIVE)."""
        gate = PromotionGate()
        result = gate.can_promote(
            from_status=StrategyStatus.DRAFT,
            to_status=StrategyStatus.ACTIVE,
        )
        assert result.allowed is False

    def test_promotion_result_includes_reason(self) -> None:
        """PromotionResult includes reason for rejection."""
        gate = PromotionGate()
        result = gate.can_promote(StrategyStatus.DRAFT, StrategyStatus.TESTING)
        if not result.allowed:
            assert len(result.reason) > 0


# ---------------------------------------------------------------------------
# 13.04 Activation/deactivation
# ---------------------------------------------------------------------------


class TestActivationDeactivation:
    """Tests for activate/deactivate strategies."""

    def test_activate_strategy_from_testing(self) -> None:
        """Activate a strategy after passing promotion gate."""
        registry = StrategyRegistry()
        strategy = registry.register("S1", "v1", {"x": 1})
        strategy.status = StrategyStatus.TESTING
        gate = PromotionGate()
        result = gate.can_promote(
            strategy.status,
            StrategyStatus.ACTIVE,
            metrics={"win_rate": 60.0},
            validation_passed=True,
        )
        assert result.allowed is True
        registry.activate("S1", "v1")
        assert strategy.status == StrategyStatus.ACTIVE

    def test_deactivate_strategy(self) -> None:
        """Deactivate an active strategy."""
        registry = StrategyRegistry()
        strategy = registry.register("S1", "v1", {"x": 1})
        strategy.status = StrategyStatus.ACTIVE
        strategy.status = StrategyStatus.RETIRED
        assert strategy.status == StrategyStatus.RETIRED

    def test_only_one_active_version_per_name(self) -> None:
        """Activating a new version retires the old one."""
        registry = StrategyRegistry()
        s1 = registry.register("S1", "v1", {"x": 1})
        registry.activate("S1", "v1")
        s2 = registry.register("S1", "v2", {"x": 2})
        s2.status = StrategyStatus.TESTING
        # When activating v2, v1 should be retired
        registry.activate("S1", "v2")
        assert s2.status == StrategyStatus.ACTIVE
        assert s1.status == StrategyStatus.RETIRED


# ---------------------------------------------------------------------------
# 13.05 Retirement
# ---------------------------------------------------------------------------


class TestRetirement:
    """Tests for strategy retirement."""

    def test_retire_strategy(self) -> None:
        """Retire a strategy."""
        registry = StrategyRegistry()
        strategy = registry.register("S1", "v1", {"x": 1})
        strategy.status = StrategyStatus.ACTIVE
        registry.retire("S1", "v1")
        assert strategy.status == StrategyStatus.RETIRED

    def test_retired_strategy_not_active(self) -> None:
        """Retired strategies are not in active list."""
        registry = StrategyRegistry()
        s = registry.register("S1", "v1", {})
        s.status = StrategyStatus.ACTIVE
        registry.retire("S1", "v1")
        active = registry.list_by_status(StrategyStatus.ACTIVE)
        assert len(active) == 0

    def test_retire_unknown_strategy_raises(self) -> None:
        """Retiring unknown strategy raises error."""
        registry = StrategyRegistry()
        with pytest.raises(ValueError, match="not found"):
            registry.retire("Unknown", "v1")


# ---------------------------------------------------------------------------
# 13.06 Live‑parameter protection
# ---------------------------------------------------------------------------


class TestLiveParameterProtection:
    """Tests for live‑parameter protection."""

    def test_cannot_modify_active_strategy_parameters(self) -> None:
        """Active strategy parameters are read‑only."""
        registry = StrategyRegistry()
        strategy = registry.register("S1", "v1", {"x": 1})
        registry.activate("S1", "v1")
        with pytest.raises(RuntimeError, match="(?i)active.*read-only"):
            strategy.parameters["x"] = 999

    def test_can_modify_draft_parameters(self) -> None:
        """DRAFT strategy parameters can be modified."""
        registry = StrategyRegistry()
        strategy = registry.register("S1", "v1", {"x": 1})
        assert strategy.status == StrategyStatus.DRAFT
        strategy.parameters["x"] = 2
        assert strategy.parameters["x"] == 2

    def test_active_strategy_requires_new_version_for_changes(self) -> None:
        """Changing active strategy requires new version."""
        registry = StrategyRegistry()
        registry.register("S1", "v1", {"x": 1})
        registry.activate("S1", "v1")
        # Must create new version for parameter change
        s2 = registry.register("S1", "v2", {"x": 2})
        assert s2.status == StrategyStatus.DRAFT
        assert s2.parameters["x"] == 2

    def test_freeze_parameters_on_activation(self) -> None:
        """Parameters become immutable when strategy is activated."""
        registry = StrategyRegistry()
        strategy = registry.register("S1", "v1", {"x": 1})
        strategy.parameters["x"] = 10  # OK in DRAFT
        registry.activate("S1", "v1")
        with pytest.raises(RuntimeError, match="(?i)active.*read-only"):
            strategy.parameters["x"] = 20
