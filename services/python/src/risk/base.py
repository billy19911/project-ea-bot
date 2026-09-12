# -*- coding: utf-8 -*-
"""Risk Engine Base — dataclasses and enums for risk metrics."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

__all__ = [
    "RiskMetrics",
    "RiskThreshold",
    "RiskLevel",
]


class RiskLevel(str, Enum):
    """Risk severity classification."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RiskThreshold(str, Enum):
    """Risk threshold types for configuration."""

    MAX_DRAWDOWN = "max_drawdown"
    DAILY_LOSS_LIMIT = "daily_loss_limit"
    MAX_EXPOSURE = "max_exposure"
    MARGIN_THRESHOLD = "margin_threshold"
    MAX_POSITIONS = "max_positions"
    MAX_POSITION_SIZE = "max_position_size"


@dataclass(frozen=True)
class RiskMetrics:
    """Comprehensive risk metrics data container.

    Attributes:
        drawdown_pct: Current drawdown as percentage (0.0-1.0).
        daily_loss_pct: Daily loss as percentage (0.0-1.0).
        equity: Current account equity.
        balance: Current account balance.
        total_exposure_pct: Total exposure as percentage (0.0-1.0).
        used_margin_pct: Used margin as percentage (0.0-1.0).
        position_count: Number of open positions.
        peak_equity: Highest equity recorded.
        max_drawdown_pct: Maximum drawdown from peak.
        correlation_risk: Portfolio correlation risk score (0.0-1.0).
        sector_concentration: Sector concentration score (0.0-1.0).
        leverage_used: Current leverage ratio.
        available_margin: Available margin for new positions.
        spread_cost: Estimated spread cost per trade.
    """

    drawdown_pct: float = 0.0
    daily_loss_pct: float = 0.0
    equity: float = 0.0
    balance: float = 0.0
    total_exposure_pct: float = 0.0
    used_margin_pct: float = 0.0
    position_count: int = 0
    peak_equity: float = 0.0
    max_drawdown_pct: float = 0.0
    correlation_risk: float = 0.0
    sector_concentration: float = 0.0
    leverage_used: float = 0.0
    available_margin: float = 0.0
    spread_cost: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert metrics to dictionary."""
        return {
            "drawdown_pct": self.drawdown_pct,
            "daily_loss_pct": self.daily_loss_pct,
            "equity": self.equity,
            "balance": self.balance,
            "total_exposure_pct": self.total_exposure_pct,
            "used_margin_pct": self.used_margin_pct,
            "position_count": self.position_count,
            "peak_equity": self.peak_equity,
            "max_drawdown_pct": self.max_drawdown_pct,
            "correlation_risk": self.correlation_risk,
            "sector_concentration": self.sector_concentration,
            "leverage_used": self.leverage_used,
            "available_margin": self.available_margin,
            "spread_cost": self.spread_cost,
        }
