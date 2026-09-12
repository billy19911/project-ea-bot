# -*- coding: utf-8 -*-
"""Position sizing algorithms for deterministic risk control."""

from __future__ import annotations

from typing import Optional


def fixed_fractional_size(
    account_equity: float,
    risk_percent: float,
    entry_price: float,
    stop_loss_price: float,
    pip_value: float = 1.0,
) -> Optional[float]:
    """Calculate position size using fixed fractional risk.

    ``risk = account_equity * (risk_percent / 100)``
    ``qty = risk / (|entry - stop| * pip_value)``

    Args:
        account_equity: Total account equity.
        risk_percent: Risk percentage per trade (e.g. 2.0 for 2%).
        entry_price: Entry price.
        stop_loss_price: Stop-loss price.
        pip_value: Value per pip/point (default 1.0).

    Returns:
        Position size or ``None`` if inputs invalid.
    """
    if account_equity <= 0 or risk_percent <= 0 or entry_price <= 0 or stop_loss_price <= 0:
        return None
    price_risk = abs(entry_price - stop_loss_price)
    if price_risk == 0 or pip_value <= 0:
        return None
    risk_amount = account_equity * (risk_percent / 100.0)
    return risk_amount / (price_risk * pip_value)


def atr_position_size(
    account_equity: float,
    risk_percent: float,
    atr_value: float,
    atr_multiplier: float = 2.0,
    pip_value: float = 1.0,
) -> Optional[float]:
    """Calculate position size using ATR for stop distance.

    ``qty = equity * (risk% / 100) / (ATR * multiplier * pip_value)``
    """
    if account_equity <= 0 or risk_percent <= 0 or atr_value <= 0 or atr_multiplier <= 0:
        return None
    risk_amount = account_equity * (risk_percent / 100.0)
    stop_distance = atr_value * atr_multiplier
    return risk_amount / (stop_distance * pip_value)


def normalize_lot_size(
    size: float,
    min_lot: float = 0.01,
    max_lot: float = 100.0,
    lot_step: float = 0.01,
) -> float:
    """Normalize position to valid lot size steps.

    Args:
        size: Raw calculated position size.
        min_lot: Minimum lot size.
        max_lot: Maximum lot size.
        lot_step: Lot size increment.

    Returns:
        Normalized lot size.
    """
    if size <= 0:
        return min_lot
    bounded = max(min_lot, min(size, max_lot))
    steps = round(bounded / lot_step)
    return round(steps * lot_step, 8)


def max_position_by_margin(
    free_margin: float,
    leverage: int,
    price: float,
    contract_size: float = 100000.0,
) -> Optional[float]:
    """Maximum position size based on free margin and leverage."""
    if free_margin <= 0 or leverage <= 0 or price <= 0 or contract_size <= 0:
        return None
    notional_capacity = free_margin * leverage
    return notional_capacity / (price * contract_size)


def calculate_stop_loss(
    entry_price: float, side: str, atr_value: float, atr_multiplier: float = 2.0
) -> Optional[float]:
    """Calculate stop-loss price based on ATR.

    Args:
        entry_price: Entry price.
        side: ``"BUY"`` or ``"SELL"``.
        atr_value: Current ATR value.
        atr_multiplier: ATR multiplier for stop distance (default 2.0).

    Returns:
        Stop-loss price or ``None``.
    """
    if entry_price <= 0 or atr_value <= 0 or atr_multiplier <= 0:
        return None
    distance = atr_value * atr_multiplier
    side_upper = side.upper()
    if side_upper == "BUY":
        return entry_price - distance
    if side_upper == "SELL":
        return entry_price + distance
    return None


def calculate_take_profit(
    entry_price: float,
    stop_loss_price: float,
    side: str,
    reward_risk_ratio: float = 2.0,
) -> Optional[float]:
    """Calculate take-profit price based on reward:risk ratio.

    Args:
        entry_price: Entry price.
        stop_loss_price: Stop-loss price.
        side: ``"BUY"`` or ``"SELL"``.
        reward_risk_ratio: Target R:R ratio (default 2.0).

    Returns:
        Take-profit price or ``None``.
    """
    if entry_price <= 0 or stop_loss_price <= 0 or reward_risk_ratio <= 0:
        return None
    risk = abs(entry_price - stop_loss_price)
    side_upper = side.upper()
    if side_upper == "BUY":
        return entry_price + risk * reward_risk_ratio
    if side_upper == "SELL":
        return entry_price - risk * reward_risk_ratio
    return None
