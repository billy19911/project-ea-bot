# -*- coding: utf-8 -*-
"""Risk Engine — account, position, and portfolio risk calculations and enforcement."""

from __future__ import annotations

from typing import Any

from .base import RiskLevel, RiskMetrics, RiskThreshold

__all__ = [
    "RiskEngine",
]


class RiskEngine:
    """Risk calculation and enforcement engine.

    Provides methods for calculating account, position, and portfolio risk metrics,
    and enforcement checks for risk limits.
    """

    def __init__(
        self,
        max_drawdown: float = 0.15,
        daily_loss_limit: float = 0.05,
        max_exposure: float = 0.30,
        margin_threshold: float = 0.20,
        max_positions: int = 5,
        max_position_size: float = 0.10,
    ) -> None:
        """Initialize RiskEngine with risk thresholds.

        Args:
            max_drawdown: Maximum allowed drawdown as percentage (0.0-1.0).
            daily_loss_limit: Maximum daily loss as percentage (0.0-1.0).
            max_exposure: Maximum total portfolio exposure as percentage (0.0-1.0).
            margin_threshold: Margin call threshold as percentage (0.0-1.0).
            max_positions: Maximum concurrent open positions.
            max_position_size: Maximum single position size as percentage (0.0-1.0).
        """
        self._thresholds = {
            RiskThreshold.MAX_DRAWDOWN: max_drawdown,
            RiskThreshold.DAILY_LOSS_LIMIT: daily_loss_limit,
            RiskThreshold.MAX_EXPOSURE: max_exposure,
            RiskThreshold.MARGIN_THRESHOLD: margin_threshold,
            RiskThreshold.MAX_POSITIONS: max_positions,
            RiskThreshold.MAX_POSITION_SIZE: max_position_size,
        }

    def calculate_account_risk(self, account_state: dict[str, Any]) -> dict[str, Any]:
        """Calculate account-level risk metrics.

        Args:
            account_state: Dict with keys: equity, balance, peak_equity, daily_pnl.

        Returns:
            Dict with drawdown_pct, daily_loss_pct, equity, balance.
        """
        equity = float(account_state.get("equity", 0.0))
        balance = float(account_state.get("balance", 0.0))
        peak_equity = float(account_state.get("peak_equity", equity))
        daily_pnl = float(account_state.get("daily_pnl", 0.0))

        drawdown_pct = 0.0
        if peak_equity > 0:
            drawdown_pct = (peak_equity - equity) / peak_equity

        daily_loss_pct = 0.0
        if balance > 0:
            daily_loss_pct = abs(min(daily_pnl, 0.0)) / balance

        return {
            "drawdown_pct": drawdown_pct,
            "daily_loss_pct": daily_loss_pct,
            "equity": equity,
            "balance": balance,
        }

    def calculate_position_risk(self, position: dict[str, Any]) -> dict[str, Any]:
        """Calculate individual position risk metrics.

        Args:
            position: Dict with keys: size, entry_price, current_price, side, stop_loss.

        Returns:
            Dict with pnl, risk_per_unit, risk_reward_ratio, position_value.
        """
        size = float(position.get("size", 0.0))
        entry_price = float(position.get("entry_price", 0.0))
        current_price = float(position.get("current_price", entry_price))
        side = position.get("side", "long").lower()
        stop_loss = float(position.get("stop_loss", 0.0))

        if side == "long":
            pnl = (current_price - entry_price) * size
            risk_per_unit = entry_price - stop_loss if stop_loss > 0 else 0.0
        else:
            pnl = (entry_price - current_price) * size
            risk_per_unit = stop_loss - entry_price if stop_loss > 0 else 0.0

        risk_reward_ratio = 0.0
        if risk_per_unit > 0:
            reward_per_unit = abs(current_price - entry_price)
            risk_reward_ratio = reward_per_unit / risk_per_unit

        position_value = size * current_price

        return {
            "pnl": pnl,
            "risk_per_unit": risk_per_unit,
            "risk_reward_ratio": risk_reward_ratio,
            "position_value": position_value,
            "unrealized_pnl_pct": pnl / (size * entry_price) if size * entry_price > 0 else 0.0,
        }

    def calculate_portfolio_risk(
        self, positions: list[dict[str, Any]], account_equity: float = 0.0
    ) -> dict[str, Any]:
        """Calculate portfolio-level risk metrics.

        Args:
            positions: List of position dicts.
            account_equity: Total account equity for exposure calculation.

        Returns:
            Dict with total_exposure_pct, correlation_risk, sector_concentration, leverage_used.
        """
        if not positions:
            return {
                "total_exposure_pct": 0.0,
                "correlation_risk": 0.0,
                "sector_concentration": 0.0,
                "leverage_used": 0.0,
                "total_notional": 0.0,
            }

        total_notional = sum(
            float(p.get("size", 0.0)) * float(p.get("current_price", p.get("entry_price", 0.0)))
            for p in positions
        )

        total_exposure_pct = 0.0
        if account_equity > 0:
            total_exposure_pct = total_notional / account_equity

        leverage_used = total_exposure_pct

        symbols = [p.get("symbol", "") for p in positions]
        unique_symbols = set(symbols)
        correlation_risk = 1.0 - (len(unique_symbols) / len(symbols)) if symbols else 0.0

        sectors = [p.get("sector", "unknown") for p in positions]
        sector_counts: dict[str, int] = {}
        for sector in sectors:
            sector_counts[sector] = sector_counts.get(sector, 0) + 1
        max_sector_count = max(sector_counts.values()) if sector_counts else 0
        sector_concentration = max_sector_count / len(positions) if positions else 0.0

        return {
            "total_exposure_pct": total_exposure_pct,
            "correlation_risk": correlation_risk,
            "sector_concentration": sector_concentration,
            "leverage_used": leverage_used,
            "total_notional": total_notional,
        }

    def check_exposure(self, positions: list[dict[str, Any]], max_exposure: float = 0.3) -> bool:
        """Check if total portfolio exposure is within limits.

        Args:
            positions: List of position dicts.
            max_exposure: Maximum allowed exposure as percentage (0.0-1.0).

        Returns:
            True if exposure within limit, False otherwise.
        """
        account_equity = float(positions[0].get("account_equity", 1.0)) if positions else 1.0
        portfolio_risk = self.calculate_portfolio_risk(positions, account_equity)
        return portfolio_risk["total_exposure_pct"] <= max_exposure

    def check_margin(self, account_state: dict[str, Any], margin_threshold: float = 0.2) -> bool:
        """Check if margin usage is within safe threshold.

        Args:
            account_state: Dict with keys: equity, used_margin, margin_call_level.
            margin_threshold: Maximum allowed used margin as percentage (0.0-1.0).

        Returns:
            True if margin usage within limit, False otherwise.
        """
        equity = float(account_state.get("equity", 0.0))
        used_margin = float(account_state.get("used_margin", 0.0))
        margin_call_level = float(account_state.get("margin_call_level", 0.0))

        if equity <= 0:
            return False

        used_margin_pct = used_margin / equity

        if margin_call_level > 0 and equity <= margin_call_level:
            return False

        return used_margin_pct <= margin_threshold

    def check_max_positions(self, positions: list[dict[str, Any]], max_count: int = 5) -> bool:
        """Check if number of open positions is within limit.

        Args:
            positions: List of position dicts.
            max_count: Maximum allowed concurrent positions.

        Returns:
            True if position count within limit, False otherwise.
        """
        return len(positions) <= max_count

    def check_drawdown(self, account_state: dict[str, Any], max_drawdown: float = 0.15) -> bool:
        """Check if current drawdown is within limit.

        Args:
            account_state: Dict with keys: equity, peak_equity.
            max_drawdown: Maximum allowed drawdown as percentage (0.0-1.0).

        Returns:
            True if drawdown within limit, False otherwise.
        """
        equity = float(account_state.get("equity", 0.0))
        peak_equity = float(account_state.get("peak_equity", equity))

        if peak_equity <= 0:
            return False

        current_drawdown = (peak_equity - equity) / peak_equity
        return current_drawdown <= max_drawdown

    def check_daily_loss(
        self, account_state: dict[str, Any], daily_loss_limit: float = 0.05
    ) -> bool:
        """Check if daily loss is within limit.

        Args:
            account_state: Dict with keys: balance, daily_pnl.
            daily_loss_limit: Maximum allowed daily loss as percentage (0.0-1.0).

        Returns:
            True if daily loss within limit, False otherwise.
        """
        balance = float(account_state.get("balance", 0.0))
        daily_pnl = float(account_state.get("daily_pnl", 0.0))

        if balance <= 0:
            return False

        daily_loss_pct = abs(min(daily_pnl, 0.0)) / balance
        return daily_loss_pct <= daily_loss_limit

    def check_position_size(
        self, position: dict[str, Any], account_equity: float, max_position_size: float = 0.10
    ) -> bool:
        """Check if single position size is within limit.

        Args:
            position: Dict with keys: size, current_price, entry_price.
            account_equity: Total account equity.
            max_position_size: Maximum allowed position size as percentage (0.0-1.0).

        Returns:
            True if position size within limit, False otherwise.
        """
        if account_equity <= 0:
            return False

        size = float(position.get("size", 0.0))
        current_price = float(position.get("current_price", position.get("entry_price", 0.0)))
        position_value = size * current_price
        position_pct = position_value / account_equity

        return position_pct <= max_position_size

    def assess_risk_level(self, metrics: RiskMetrics) -> RiskLevel:
        """Assess overall risk level from metrics.

        Args:
            metrics: RiskMetrics dataclass with all risk values.

        Returns:
            RiskLevel enum (LOW, MEDIUM, HIGH, CRITICAL).
        """
        score = 0

        max_dd = self._thresholds.get(RiskThreshold.MAX_DRAWDOWN, 0.15)
        if metrics.drawdown_pct > max_dd * 0.8:
            score += 3
        elif metrics.drawdown_pct > max_dd * 0.5:
            score += 2
        elif metrics.drawdown_pct > max_dd * 0.2:
            score += 1

        daily_limit = self._thresholds.get(RiskThreshold.DAILY_LOSS_LIMIT, 0.05)
        if metrics.daily_loss_pct > daily_limit * 0.8:
            score += 3
        elif metrics.daily_loss_pct > daily_limit * 0.5:
            score += 2
        elif metrics.daily_loss_pct > daily_limit * 0.2:
            score += 1

        max_exp = self._thresholds.get(RiskThreshold.MAX_EXPOSURE, 0.30)
        if metrics.total_exposure_pct > max_exp * 0.9:
            score += 3
        elif metrics.total_exposure_pct > max_exp * 0.7:
            score += 2
        elif metrics.total_exposure_pct > max_exp * 0.5:
            score += 1

        margin_thresh = self._thresholds.get(RiskThreshold.MARGIN_THRESHOLD, 0.20)
        if metrics.used_margin_pct > margin_thresh * 0.9:
            score += 3
        elif metrics.used_margin_pct > margin_thresh * 0.7:
            score += 2
        elif metrics.used_margin_pct > margin_thresh * 0.5:
            score += 1

        max_pos = self._thresholds.get(RiskThreshold.MAX_POSITIONS, 5)
        if metrics.position_count >= max_pos:
            score += 2
        elif metrics.position_count >= max_pos * 0.8:
            score += 1

        if metrics.correlation_risk > 0.8:
            score += 2
        elif metrics.correlation_risk > 0.5:
            score += 1

        if metrics.sector_concentration > 0.8:
            score += 2
        elif metrics.sector_concentration > 0.5:
            score += 1

        if score >= 10:
            return RiskLevel.CRITICAL
        elif score >= 6:
            return RiskLevel.HIGH
        elif score >= 3:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW

    def get_threshold(self, threshold: RiskThreshold) -> float | int:
        """Get configured threshold value.

        Args:
            threshold: RiskThreshold enum value.

        Returns:
            Configured threshold value.
        """
        return self._thresholds.get(threshold, 0.0)

    def set_threshold(self, threshold: RiskThreshold, value: float | int) -> None:
        """Update a risk threshold.

        Args:
            threshold: RiskThreshold enum value.
            value: New threshold value.
        """
        self._thresholds[threshold] = value
