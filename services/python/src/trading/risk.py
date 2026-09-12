# -*- coding: utf-8 -*-
"""Risk metrics for deterministic portfolio and trade evaluation."""

from __future__ import annotations

from typing import Optional


def max_drawdown(equity_curve: list[float]) -> float:
    """Maximum drawdown as a percentage (0–100).

    Args:
        equity_curve: Sequence of equity values (oldest → newest).

    Returns:
        Largest peak-to-trough decline percentage, or 0.0.
    """
    if not equity_curve:
        return 0.0
    peak = equity_curve[0]
    max_dd = 0.0
    for equity in equity_curve:
        peak = max(peak, equity)
        if peak > 0:
            dd = (peak - equity) / peak * 100.0
            max_dd = max(max_dd, dd)
    return max_dd


def sharpe_ratio(
    returns: list[float], risk_free_rate: float = 0.0, periods_per_year: int = 252
) -> Optional[float]:
    """Annualised Sharpe ratio.

    Args:
        returns: Return series (e.g. daily returns as fractions).
        risk_free_rate: Annual risk-free rate (default 0.0).
        periods_per_year: Number of periods per year (default 252 for daily).

    Returns:
        Annualised Sharpe ratio or ``None``.
    """
    if len(returns) < 2:
        return None
    per_period_rf = risk_free_rate / periods_per_year
    excess = [r - per_period_rf for r in returns]
    mean_excess = sum(excess) / len(excess)
    variance = sum((r - mean_excess) ** 2 for r in excess) / (len(excess) - 1)
    std = variance**0.5
    if std == 0:
        return None
    return (mean_excess / std) * (periods_per_year**0.5)


def sortino_ratio(
    returns: list[float], target_return: float = 0.0, periods_per_year: int = 252
) -> Optional[float]:
    """Annualised Sortino ratio (downside deviation only).

    Args:
        returns: Return series.
        target_return: Target return (default 0.0).
        periods_per_year: Periods per year (default 252).

    Returns:
        Annualised Sortino ratio or ``None``.
    """
    if len(returns) < 2:
        return None
    per_period_target = target_return / periods_per_year
    excess = [r - per_period_target for r in returns]
    mean_excess = sum(excess) / len(excess)
    downside = [min(0.0, r) for r in excess]
    if not downside:
        return None
    downside_variance = sum(d * d for d in downside) / len(downside)
    downside_dev = downside_variance**0.5
    if downside_dev == 0:
        return None
    return (mean_excess / downside_dev) * (periods_per_year**0.5)


def profit_factor(profits: list[float]) -> Optional[float]:
    """Profit factor = gross profits / gross losses.

    Args:
        profits: List of individual trade P&L values.

    Returns:
        Profit factor (> 1.0 is profitable) or ``None`` if undefined.
    """
    gross_profit = sum(p for p in profits if p > 0)
    gross_loss = abs(sum(p for p in profits if p < 0))
    if gross_loss == 0:
        return None if gross_profit == 0 else float("inf")
    return gross_profit / gross_loss


def win_rate(profits: list[float]) -> Optional[float]:
    """Percentage of winning trades.

    Args:
        profits: List of individual trade P&L values.

    Returns:
        Win rate as a percentage (0–100) or ``None``.
    """
    if not profits:
        return None
    wins = sum(1 for p in profits if p > 0)
    return wins / len(profits) * 100.0


def risk_reward_ratio(entry: float, stop_loss: float, take_profit: float) -> Optional[float]:
    """Reward-to-risk ratio.

    Args:
        entry: Entry price.
        stop_loss: Stop-loss price.
        take_profit: Take-profit price.

    Returns:
        R:R ratio or ``None``.
    """
    if entry <= 0:
        return None
    risk = abs(entry - stop_loss)
    if risk == 0:
        return None
    reward = abs(take_profit - entry)
    return reward / risk


def exposure_percent(position_value: float, account_equity: float) -> Optional[float]:
    """Position exposure as a percentage of equity.

    Args:
        position_value: Current position market value.
        account_equity: Total account equity.

    Returns:
        Exposure percentage or ``None``.
    """
    if account_equity <= 0:
        return None
    return position_value / account_equity * 100.0


def value_at_risk(returns: list[float], confidence: float = 0.95) -> Optional[float]:
    """Historical Value at Risk (VaR).

    Args:
        returns: Return series.
        confidence: Confidence level (default 0.95 = 95%).

    Returns:
        Maximum expected loss at the given confidence level.
    """
    if not returns or confidence <= 0 or confidence >= 1:
        return None
    sorted_returns = sorted(returns)
    index = int((1.0 - confidence) * len(sorted_returns))
    index = max(0, min(index, len(sorted_returns) - 1))
    return abs(sorted_returns[index])
