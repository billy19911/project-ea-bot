# -*- coding: utf-8 -*-
"""Tests for the expanded strategy lifecycle — PRD_V2 §19 Strategy Registry.

Covers the 10 PRD statuses, the richer ``VersionedStrategy`` metadata, and the
lifecycle timestamps (created/approved/activated/retired).
"""

from __future__ import annotations

import pytest

from strategy.registry import StrategyRegistry, StrategyStatus, VersionedStrategy

# The exact status set required by PRD_V2 §19.
PRD_STATUSES = {
    "DRAFT",
    "RESEARCH",
    "BACKTESTED",
    "WALK_FORWARD",
    "PAPER",
    "DEMO",
    "APPROVED",
    "ACTIVE",
    "RETIRED",
    "REJECTED",
}


class TestStrategyStatusEnum:
    """§19 — status enum conforms to the PRD."""

    def test_contains_all_prd_statuses(self) -> None:
        values = {s.value for s in StrategyStatus}
        assert PRD_STATUSES.issubset(values)

    def test_status_lookup_by_value(self) -> None:
        assert StrategyStatus("DRAFT") is StrategyStatus.DRAFT
        assert StrategyStatus("ACTIVE") is StrategyStatus.ACTIVE

    def test_legacy_statuses_still_resolve(self) -> None:
        # Backwards-compat: older code/tests referenced TESTING.
        assert StrategyStatus("TESTING") is StrategyStatus.TESTING


class TestVersionedStrategyMetadata:
    """§19 — each version tracks the required metadata fields."""

    def test_default_metadata_present(self) -> None:
        strategy = VersionedStrategy(name="S", version="v1")
        assert strategy.strategy_id
        assert strategy.status is StrategyStatus.DRAFT
        assert strategy.created_at
        assert strategy.approved_at is None
        assert strategy.activated_at is None
        assert strategy.retired_at is None

    def test_optional_policy_fields(self) -> None:
        strategy = VersionedStrategy(
            name="S",
            version="v1",
            risk_policy={"max_dd": 0.1},
            compatible_regimes=["TRENDING", "RANGING"],
            metrics_summary={"win_rate": 55.0},
            validation_evidence={"walk_forward": True},
            rationale="candidate from research",
        )
        assert strategy.risk_policy == {"max_dd": 0.1}
        assert strategy.compatible_regimes == ["TRENDING", "RANGING"]
        assert strategy.metrics_summary["win_rate"] == 55.0
        assert strategy.validation_evidence["walk_forward"] is True
        assert strategy.rationale == "candidate from research"

    def test_status_transition_sets_timestamps(self) -> None:
        strategy = VersionedStrategy(name="S", version="v1")
        strategy.set_status(StrategyStatus.APPROVED)
        assert strategy.status is StrategyStatus.APPROVED
        assert strategy.approved_at is not None

        strategy.set_status(StrategyStatus.ACTIVE)
        assert strategy.activated_at is not None

        strategy.set_status(StrategyStatus.RETIRED)
        assert strategy.retired_at is not None

    def test_to_dict_includes_metadata(self) -> None:
        strategy = VersionedStrategy(name="S", version="v1", metrics_summary={"win_rate": 50.0})
        data = strategy.to_dict()
        assert data["strategy_id"] == strategy.strategy_id
        assert data["metrics_summary"] == {"win_rate": 50.0}
        assert "created_at" in data
        assert data["status"] == "DRAFT"


class TestRegistryRecordStatus:
    """§19 — registry can record status transitions with timestamps."""

    def test_record_status(self) -> None:
        registry = StrategyRegistry()
        registry.register("S1", "v1", {})
        registry.record_status("S1", "v1", StrategyStatus.BACKTESTED)
        s = registry.get("S1", "v1")
        assert s is not None
        assert s.status is StrategyStatus.BACKTESTED

    def test_record_status_unknown_raises(self) -> None:
        registry = StrategyRegistry()
        with pytest.raises(ValueError, match="not found"):
            registry.record_status("Nope", "v1", StrategyStatus.PAPER)
