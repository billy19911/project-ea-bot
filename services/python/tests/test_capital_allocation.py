# -*- coding: utf-8 -*-
"""Tests for Capital Allocation & Multi-Strategy Safety (Phase 52)."""

from src.risk.capital_allocation import CapitalAllocator, StrategyAllocation


def _allocator(**kwargs) -> CapitalAllocator:
    defaults = dict(
        total_equity=100_000.0,
        allocations=[
            StrategyAllocation(strategy_id="A", weight=0.5),
            StrategyAllocation(strategy_id="B", weight=0.3),
            StrategyAllocation(strategy_id="C", weight=0.2),
        ],
    )
    defaults.update(kwargs)
    return CapitalAllocator(**defaults)


def test_weights_validate() -> None:
    alloc = _allocator()
    assert alloc.validate_weights() == []
    assert alloc.total_weight() == 1.0


def test_overweight_rejected() -> None:
    alloc = CapitalAllocator(
        total_equity=100_000.0,
        allocations=[
            StrategyAllocation("A", 0.7),
            StrategyAllocation("B", 0.5),
        ],
    )
    assert alloc.validate_weights() != []
    decision = alloc.allocate("A", 10_000.0)
    assert decision.allowed is False


def test_strategy_clamped_to_its_share() -> None:
    alloc = _allocator()
    # Strategy A proposed risk far above its 50% share (50k).
    decision = alloc.allocate("A", 80_000.0)
    assert decision.allowed is True
    assert decision.allowed_risk == 50_000.0
    assert any("clamped to allocation share" in r for r in decision.reasons)


def test_strategy_cannot_assume_full_equity() -> None:
    alloc = _allocator()
    # Strategy C has only 20% (20k) — proposing the whole account is clamped.
    decision = alloc.allocate("C", 100_000.0)
    assert decision.allowed_risk == 20_000.0


def test_shared_daily_loss_limit_blocks() -> None:
    alloc = _allocator(shared_daily_loss_limit=5_000.0, realized_daily_loss=5_000.0)
    decision = alloc.allocate("A", 1_000.0)
    assert decision.allowed is False
    assert any("shared daily loss" in r for r in decision.reasons)


def test_shared_daily_loss_clamps() -> None:
    alloc = _allocator(shared_daily_loss_limit=10_000.0, realized_daily_loss=8_000.0)
    decision = alloc.allocate("A", 5_000.0)
    assert decision.allowed is True
    assert decision.allowed_risk == 2_000.0


def test_shared_drawdown_limit_blocks() -> None:
    alloc = _allocator(shared_drawdown_limit=10_000.0, current_drawdown=10_000.0)
    decision = alloc.allocate("A", 1_000.0)
    assert decision.allowed is False


def test_gross_exposure_cap() -> None:
    alloc = _allocator(
        max_gross_exposure=100_000.0,
        allocations=[
            StrategyAllocation("A", 0.5, gross_exposure=60_000.0),
            StrategyAllocation("B", 0.5, gross_exposure=40_000.0),
        ],
    )
    decision = alloc.allocate("A", 1_000.0)
    assert decision.allowed is False
    assert any("gross exposure" in r for r in decision.reasons)


def test_correlation_exposure_cap() -> None:
    alloc = _allocator(max_correlation_exposure=50_000.0, correlation_exposure=50_000.0)
    decision = alloc.allocate("A", 1_000.0)
    assert decision.allowed is False
    assert any("correlation" in r for r in decision.reasons)


def test_unknown_strategy_rejected() -> None:
    alloc = _allocator()
    decision = alloc.allocate("Z", 1_000.0)
    assert decision.allowed is False


def test_snapshot_fields() -> None:
    alloc = _allocator()
    snap = alloc.snapshot()
    for key in (
        "total_equity",
        "total_weight",
        "gross_exposure",
        "net_exposure",
        "correlation_exposure",
        "shared_daily_loss",
        "shared_drawdown",
    ):
        assert key in snap


def test_net_exposure_with_directions() -> None:
    alloc = CapitalAllocator(
        total_equity=100_000.0,
        allocations=[
            StrategyAllocation("A", 0.5, gross_exposure=10_000.0),
            StrategyAllocation("B", 0.5, gross_exposure=6_000.0),
        ],
    )
    net = alloc.net_exposure({"A": 1, "B": -1})
    assert net == 4_000.0
