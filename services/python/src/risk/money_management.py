# -*- coding: utf-8 -*-
"""Money Management — position sizing, SL/TP, R:R validation, and exposure capping.

Phase 11: risk-percentage position sizing, dynamic lot calculation based on
stop-loss distance and contract size, SL/TP price derivation from ATR or fixed
pips, risk-to-reward validation, and lot exposure capping.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "MoneyManager",
    "PositionSizeResult",
]


@dataclass(frozen=True)
class PositionSizeResult:
    """Result of a position sizing calculation.

    Attributes:
        lot_size: Computed (and optionally capped) lot size.
        risk_amount: Monetary amount at risk in account currency.
        sl_pips: Stop-loss distance in pips.
        tp_pips: Take-profit distance in pips.
        rr_ratio: Risk-to-reward ratio (reward / risk).
        sl_price: Stop-loss price level.
        tp_price: Take-profit price level.
        capped: True if the lot was reduced by an exposure cap.
    """

    lot_size: float = 0.0
    risk_amount: float = 0.0
    sl_pips: float = 0.0
    tp_pips: float = 0.0
    rr_ratio: float = 0.0
    sl_price: float = 0.0
    tp_price: float = 0.0
    capped: bool = False


class MoneyManager:
    """Money management calculations: sizing, SL/TP, R:R, and exposure caps."""

    def calculate_lot_size(
        self,
        balance: float,
        risk_pct: float,
        sl_pips: float,
        point_value: float,
        contract_size: float = 100000,
        equity: float | None = None,
    ) -> PositionSizeResult:
        """Calculate lot size from a fixed risk percentage of account funds.

        Formula: ``lot = (base * risk_pct) / (sl_pips * point_value * contract_size)``
        where ``base`` is ``equity`` when provided, else ``balance``.

        Args:
            balance: Account balance in account currency.
            risk_pct: Fraction of base to risk on the trade (e.g. 0.01 = 1%).
            sl_pips: Stop-loss distance in pips. Must be positive.
            point_value: Value of one point/pip in account currency per unit.
            contract_size: Units of the base asset per 1.0 lot (default 100,000).
            equity: Optional account equity; overrides balance when provided.

        Returns:
            PositionSizeResult with lot_size, risk_amount, sl_pips.

        Raises:
            ValueError: If sl_pips is not positive.
        """
        if sl_pips <= 0:
            raise ValueError(f"sl_pips must be positive, got {sl_pips}")

        base = float(equity) if equity is not None else float(balance)
        risk_amount = base * float(risk_pct)

        if risk_amount <= 0:
            return PositionSizeResult(lot_size=0.0, risk_amount=0.0, sl_pips=sl_pips)

        loss_per_lot = sl_pips * point_value * contract_size
        lot_size = risk_amount / loss_per_lot

        return PositionSizeResult(
            lot_size=lot_size,
            risk_amount=risk_amount,
            sl_pips=sl_pips,
        )

    def calculate_sl_tp(
        self,
        entry_price: float,
        direction: str,
        atr_value: float | None = None,
        sl_multiplier: float = 1.5,
        tp_multiplier: float = 3.0,
        pips: float | None = None,
        point_value: float | None = None,
    ) -> tuple[float, float]:
        """Calculate stop-loss and take-profit prices for a trade.

        SL/TP distance comes from ATR (``atr_value * multiplier``) when
        ``atr_value`` is given, otherwise from ``pips * point_value``.
        For longs the SL is below and TP above the entry; for shorts the reverse.

        Args:
            entry_price: Entry price.
            direction: 'long' or 'short'.
            atr_value: ATR value used as the base distance.
            sl_multiplier: ATR multiplier for the stop-loss distance.
            tp_multiplier: ATR multiplier for the take-profit distance; when
                using pips the TP distance is ``pips * tp_multiplier``.
            pips: Fixed pip distance for the stop-loss (TP derived via multiplier).
            point_value: Price value of one pip; required when pips is given.

        Returns:
            Tuple of (sl_price, tp_price).

        Raises:
            ValueError: On invalid direction, or when neither an ATR value
                nor pips are supplied.
        """
        direction = str(direction).lower()
        if direction not in ("long", "short"):
            raise ValueError(f"direction must be 'long' or 'short', got {direction!r}")

        if atr_value is None and pips is None:
            raise ValueError("either atr_value or pips must be provided")

        if atr_value is not None:
            risk_distance = atr_value * sl_multiplier
            reward_distance = atr_value * tp_multiplier
        else:
            if point_value is None:
                raise ValueError("point_value is required when pips is provided")
            risk_distance = pips * point_value
            reward_distance = pips * tp_multiplier * point_value

        if direction == "long":
            sl_price = entry_price - risk_distance
            tp_price = entry_price + reward_distance
        else:
            sl_price = entry_price + risk_distance
            tp_price = entry_price - reward_distance

        return sl_price, tp_price

    def validate_rr_ratio(
        self,
        entry_price: float,
        sl_price: float,
        tp_price: float,
        min_rr: float = 1.5,
    ) -> tuple[bool, float]:
        """Validate a trade setup's risk-to-reward ratio.

        The actual R:R is computed as ``abs(tp - entry) / abs(entry - sl)``
        — this is direction-agnostic.

        Args:
            entry_price: Entry price.
            sl_price: Stop-loss price.
            tp_price: Take-profit price.
            min_rr: Minimum acceptable risk-to-reward ratio.

        Returns:
            Tuple of (is_valid, actual_rr).

        Raises:
            ValueError: If the stop-loss equals the entry price.
        """
        risk = abs(float(entry_price) - float(sl_price))
        if risk <= 0:
            raise ValueError("stop loss cannot equal entry price")

        reward = abs(float(tp_price) - float(entry_price))
        actual_rr = reward / risk

        return actual_rr >= min_rr, actual_rr

    def cap_lot_size(
        self,
        calculated_lot: float,
        max_lot_per_trade: float = 1.0,
        current_total_lots: float = 0.0,
        max_total_lots: float = 5.0,
    ) -> float:
        """Cap a calculated lot size by per-trade and portfolio limits.

        Args:
            calculated_lot: Lot size computed by the sizing logic.
            max_lot_per_trade: Maximum lot per single trade.
            current_total_lots: Sum of lots across open positions.
            max_total_lots: Maximum aggregate lots across all positions.

        Returns:
            The capped lot size, never exceeding either limit; zero when the
            portfolio cap is already exhausted.
        """
        if calculated_lot <= 0:
            return 0.0

        remaining_total = max(0.0, max_total_lots - current_total_lots)
        return min(calculated_lot, max_lot_per_trade, remaining_total)
