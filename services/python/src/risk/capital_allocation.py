# -*- coding: utf-8 -*-
"""Capital Allocation & Multi-Strategy Safety — PRD_V2 §52.

When more than one strategy runs on an account, they must **share** the account
risk rather than each assuming it owns the whole equity (PRD §52). This module
allocates capital across strategies and enforces shared exposure, loss and
drawdown limits at the account level.

Tracked per account (PRD §52)::

    strategy allocation, gross exposure, net exposure,
    correlation exposure, shared daily loss, shared drawdown
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

__all__ = [
    "StrategyAllocation",
    "CapitalAllocator",
    "AllocationDecision",
]


@dataclass
class StrategyAllocation:
    """A single strategy's slice of the account capital (PRD §52)."""

    strategy_id: str
    weight: float  # fraction of account equity (0..1)
    gross_exposure: float = 0.0

    def allocation_amount(self, equity: float) -> float:
        return equity * self.weight


@dataclass
class AllocationDecision:
    """Outcome of an allocation/exposure check."""

    allowed: bool
    allowed_risk: float = 0.0
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "allowed_risk": self.allowed_risk,
            "reasons": list(self.reasons),
        }


@dataclass
class CapitalAllocator:
    """Allocates account capital across strategies with shared limits (PRD §52).

    Args:
        total_equity: Account equity.
        allocations: Per-strategy allocations (weights must sum to <= 1).
        shared_daily_loss_limit: Account-wide daily loss limit (currency).
        shared_drawdown_limit: Account-wide drawdown limit (currency).
        max_gross_exposure: Account-wide gross exposure cap (currency).
        max_correlation_exposure: Exposure cap for correlated strategies.
    """

    total_equity: float
    allocations: list[StrategyAllocation] = field(default_factory=list)
    shared_daily_loss_limit: float = 0.0
    shared_drawdown_limit: float = 0.0
    max_gross_exposure: float = 0.0
    max_correlation_exposure: float = 0.0
    # Running account-level usage.
    realized_daily_loss: float = 0.0
    current_drawdown: float = 0.0
    correlation_exposure: float = 0.0

    # ------------------------------------------------------------------
    def total_weight(self) -> float:
        return sum(a.weight for a in self.allocations)

    def validate_weights(self) -> list[str]:
        """Return reasons the allocation weights are invalid (empty = ok)."""
        reasons: list[str] = []
        if self.total_weight() > 1.0 + 1e-9:
            reasons.append(f"total weight {self.total_weight():.4f} exceeds 1.0")
        for a in self.allocations:
            if a.weight < 0:
                reasons.append(f"{a.strategy_id}: negative weight")
        return reasons

    def gross_exposure(self) -> float:
        return sum(a.gross_exposure for a in self.allocations)

    def net_exposure(self, directions: Optional[dict[str, int]] = None) -> float:
        """Return net exposure given per-strategy direction (+1/-1)."""
        if directions is None:
            return self.gross_exposure()
        net = 0.0
        for a in self.allocations:
            direction = directions.get(a.strategy_id, 1)
            net += a.gross_exposure * direction
        return net

    # ------------------------------------------------------------------
    def allocate(self, strategy_id: str, proposed_risk: float) -> AllocationDecision:
        """Return the risk a strategy is *actually* allowed to take (PRD §52).

        The strategy's proposed risk is clamped to its allocation weight and to
        the remaining shared account limits. A strategy can never assume the
        whole account equity.
        """
        reasons: list[str] = []

        weight_reasons = self.validate_weights()
        if weight_reasons:
            return AllocationDecision(allowed=False, allowed_risk=0.0, reasons=weight_reasons)

        allocation = next((a for a in self.allocations if a.strategy_id == strategy_id), None)
        if allocation is None:
            return AllocationDecision(
                allowed=False, allowed_risk=0.0, reasons=[f"{strategy_id} has no allocation"]
            )

        # 1. Clamp to the strategy's own share of equity.
        strategy_cap = allocation.allocation_amount(self.total_equity)
        allowed_risk = min(proposed_risk, strategy_cap)
        if proposed_risk > strategy_cap:
            reasons.append(f"clamped to allocation share {strategy_cap:.2f}")

        # 2. Shared daily loss limit.
        if self.shared_daily_loss_limit > 0:
            remaining = self.shared_daily_loss_limit - self.realized_daily_loss
            if remaining <= 0:
                return AllocationDecision(
                    allowed=False,
                    allowed_risk=0.0,
                    reasons=["shared daily loss limit reached"],
                )
            if allowed_risk > remaining:
                allowed_risk = remaining
                reasons.append("clamped to remaining shared daily loss")

        # 3. Shared drawdown limit.
        if self.shared_drawdown_limit > 0:
            remaining_dd = self.shared_drawdown_limit - self.current_drawdown
            if remaining_dd <= 0:
                return AllocationDecision(
                    allowed=False,
                    allowed_risk=0.0,
                    reasons=["shared drawdown limit reached"],
                )
            if allowed_risk > remaining_dd:
                allowed_risk = remaining_dd
                reasons.append("clamped to remaining shared drawdown")

        # 4. Gross exposure cap.
        if self.max_gross_exposure > 0:
            remaining_gross = self.max_gross_exposure - self.gross_exposure()
            if remaining_gross <= 0:
                return AllocationDecision(
                    allowed=False,
                    allowed_risk=0.0,
                    reasons=["max gross exposure reached"],
                )

        # 5. Correlation exposure cap.
        if (
            self.max_correlation_exposure > 0
            and self.correlation_exposure >= self.max_correlation_exposure
        ):
            return AllocationDecision(
                allowed=False,
                allowed_risk=0.0,
                reasons=["correlation exposure cap reached"],
            )

        return AllocationDecision(
            allowed=True, allowed_risk=max(allowed_risk, 0.0), reasons=reasons
        )

    def snapshot(self) -> dict[str, Any]:
        """Return the account-level exposure summary (PRD §52)."""
        return {
            "total_equity": self.total_equity,
            "total_weight": self.total_weight(),
            "gross_exposure": self.gross_exposure(),
            "net_exposure": self.net_exposure(),
            "correlation_exposure": self.correlation_exposure,
            "shared_daily_loss": self.realized_daily_loss,
            "shared_drawdown": self.current_drawdown,
        }
