# -*- coding: utf-8 -*-
"""Simulated Execution Engine for Paper Trading.

Phase 19: Mock execution engine that simulates order fills
without real MT5 connection. Applies configurable spread and
random slippage based on volatility.
"""

from __future__ import annotations

import logging
import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from execution import ExecutionResult, OrderRequest

from .paper_account import PaperAccount, PaperPosition, PaperTrade

__all__ = [
    "SimulatedExecutionEngine",
    "SpreadConfig",
    "SlippageModel",
]

logger = logging.getLogger(__name__)


@dataclass
class SpreadConfig:
    """Spread configuration for simulated execution.

    Attributes:
        default_spread: Default spread (in price units) for unknown symbols.
        symbol_spreads: Dict mapping symbol to spread (e.g. {"EURUSD": 0.0002}).
        spread_variation: Random variation factor (0.0-1.0) for spread.
    """

    default_spread: float = 0.0001
    symbol_spreads: dict[str, float] = field(default_factory=dict)
    spread_variation: float = 0.0  # No variation by default for deterministic tests

    def get_spread(self, symbol: str) -> float:
        """Get spread for symbol, with random variation applied."""
        base_spread = self.symbol_spreads.get(symbol, self.default_spread)
        if self.spread_variation > 0:
            variation = random.uniform(-self.spread_variation, self.spread_variation)
            return base_spread * (1.0 + variation)
        return base_spread


@dataclass
class SlippageModel:
    """Slippage model for simulated execution.

    Attributes:
        base_slippage: Base slippage as fraction of price (e.g. 0.0001 = 1 pip).
        volatility_factor: Multiplier for slippage based on volatility.
        max_slippage: Maximum slippage as fraction of price.
    """

    base_slippage: float = 0.00001  # 0.1 pip base
    volatility_factor: float = 0.5  # How much volatility affects slippage
    max_slippage: float = 0.001  # Max 10 pips

    def calculate_slippage(self, price: float, volatility: float, is_buy: bool) -> float:
        """Calculate slippage amount based on volatility.

        Slippage is always adverse to the trader:
        - BUY: positive slippage (price goes up)
        - SELL: negative slippage (price goes down)
        """
        if volatility <= 0:
            return 0.0

        # Slippage proportional to volatility
        slippage_pct = min(
            self.base_slippage + (volatility * self.volatility_factor * 0.01),
            self.max_slippage,
        )

        # Random component
        random_factor = random.uniform(0.5, 1.5)
        slippage = price * slippage_pct * random_factor

        # Apply direction: adverse to trader
        return slippage if is_buy else -slippage


class SimulatedExecutionEngine:
    """Simulated execution engine for paper trading.

    Mimics real MT5 execution behavior without actual broker connection.
    Applies spread and slippage to orders and updates paper account state.

    Args:
        spread_config: SpreadConfig instance for spread calculation.
        slippage_model: SlippageModel instance for slippage calculation.
        min_volume: Minimum lot size.
        max_volume: Maximum lot size.
    """

    def __init__(
        self,
        spread_config: Optional[SpreadConfig | dict[str, float]] = None,
        slippage_model: Optional[SlippageModel] = None,
        min_volume: float = 0.01,
        max_volume: float = 100.0,
        auto_review: bool = True,
    ) -> None:
        """Initialize simulated execution engine.

        Args:
            spread_config: SpreadConfig instance or plain dict mapping
                symbol to spread (e.g. {"EURUSD": 0.0002}). Dict form
                uses zero variation for deterministic tests.
            slippage_model: SlippageModel instance.
            min_volume: Minimum lot size.
            max_volume: Maximum lot size.
            auto_review: When True (default), a closed position triggers a
                post-trade review via ``review.auto_trigger`` (PRD §18.1).
                The hook is fail-safe and never breaks the close path.
        """
        if isinstance(spread_config, dict):
            spread_config = SpreadConfig(
                symbol_spreads=spread_config,
                spread_variation=0.0,
            )
        self.spread_config = spread_config or SpreadConfig()
        self.slippage_model = slippage_model or SlippageModel()
        self.min_volume = min_volume
        self.max_volume = max_volume
        self.auto_review = auto_review

        # In-memory tracking (similar to real ExecutionEngine)
        self._pending_orders: dict[str, float] = {}
        self._completed_orders: dict[str, ExecutionResult] = {}
        self._ticket_counter: int = 10000

    def _generate_ticket(self) -> int:
        """Generate a unique simulated ticket number."""
        self._ticket_counter += 1
        return self._ticket_counter

    def apply_spread(self, symbol: str, base_price: float, is_buy: bool) -> float:
        """Apply spread to base price.

        BUY orders: use ask (base + spread/2)
        SELL orders: use bid (base - spread/2)

        Args:
            symbol: Instrument symbol.
            base_price: Mid-price before spread.
            is_buy: True for BUY orders, False for SELL.

        Returns:
            Price with spread applied.
        """
        spread = self.spread_config.get_spread(symbol)
        half_spread = spread / 2.0

        if is_buy:
            return base_price + half_spread
        else:
            return base_price - half_spread

    def apply_slippage(self, price: float, volatility: float, is_buy: bool = True) -> float:
        """Apply random slippage to price based on volatility.

        Args:
            price: Price before slippage.
            volatility: Current volatility (e.g. ATR or std dev).
            is_buy: True for BUY orders.

        Returns:
            Price with slippage applied.
        """
        return price + self.slippage_model.calculate_slippage(price, volatility, is_buy)

    def validate_order(self, request: OrderRequest) -> tuple[bool, list[str]]:
        """Validate order request (mirrors real execution engine).

        Args:
            request: OrderRequest to validate.

        Returns:
            Tuple of (is_valid, list of error messages).
        """
        errors: list[str] = []

        # Symbol validation
        if not request.symbol or not request.symbol.strip():
            errors.append("Symbol cannot be empty")

        # Volume validation
        if request.volume <= 0:
            errors.append(f"Volume must be > 0, got {request.volume}")
        elif request.volume < self.min_volume:
            errors.append(f"Volume {request.volume} below minimum {self.min_volume}")
        elif request.volume > self.max_volume:
            errors.append(f"Volume {request.volume} exceeds maximum {self.max_volume}")

        # Order type validation
        valid_types = {
            "BUY",
            "SELL",
            "BUY_LIMIT",
            "SELL_LIMIT",
            "BUY_STOP",
            "SELL_STOP",
        }
        if request.order_type.upper() not in valid_types:
            errors.append(
                f"Invalid order_type '{request.order_type}'. "
                f"Must be one of: {', '.join(sorted(valid_types))}"
            )

        return (len(errors) == 0, errors)

    def simulate_order(
        self,
        request: OrderRequest,
        base_price: float,
        volatility: float = 0.01,
    ) -> ExecutionResult:
        """Simulate order execution without real MT5 connection.

        Args:
            request: OrderRequest to execute.
            base_price: Current market mid-price.
            volatility: Current market volatility for slippage calc.

        Returns:
            ExecutionResult with simulated fill details.
        """
        # Ensure idempotency key
        if not request.idempotency_key:
            request.idempotency_key = str(uuid.uuid4())

        # Check for duplicate
        if request.idempotency_key in self._completed_orders:
            return self._completed_orders[request.idempotency_key]

        # Validate order
        is_valid, errors = self.validate_order(request)
        if not is_valid:
            logger.warning("Simulated order validation failed: %s", errors)
            return ExecutionResult(
                success=False,
                error_code=400,
                error_message="; ".join(errors),
                retries=0,
            )

        # Determine execution side
        is_buy = "BUY" in request.order_type.upper()

        # Apply spread
        price_with_spread = self.apply_spread(request.symbol, base_price, is_buy)
        spread_applied = abs(price_with_spread - base_price)

        # Apply slippage
        final_price = self.apply_slippage(price_with_spread, volatility, is_buy)
        slippage_applied = abs(final_price - price_with_spread)

        # Generate ticket
        ticket = self._generate_ticket()

        # Create position details
        position_opened: dict[str, Any] = {
            "symbol": request.symbol,
            "entry_price": final_price,
            "size": request.volume,
            "side": "BUY" if is_buy else "SELL",
            "stop_loss": request.sl,
            "take_profit": request.tp,
            "ticket": ticket,
            "spread_applied": spread_applied,
            "slippage_applied": slippage_applied,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        result = ExecutionResult(
            success=True,
            ticket=ticket,
            error_code=0,
            error_message="",
            retries=0,
            position_opened=position_opened,
        )

        # Record completion
        self._completed_orders[request.idempotency_key] = result

        logger.info(
            "Simulated order executed: ticket=%s, symbol=%s, "
            "price=%.5f, spread=%.6f, slippage=%.6f",
            ticket,
            request.symbol,
            final_price,
            spread_applied,
            slippage_applied,
        )

        return result

    def update_account(
        self,
        account: PaperAccount,
        result: ExecutionResult,
        equity_change: float = 0.0,
    ) -> None:
        """Update paper account state after simulated execution.

        Args:
            account: PaperAccount to update.
            result: ExecutionResult from simulate_order.
            equity_change: Change in equity from closed position (if any).
        """
        if not result.success or not result.position_opened:
            logger.debug("No account update: execution failed or no position")
            return

        pos_data = result.position_opened

        # Create PaperPosition
        position = PaperPosition(
            symbol=pos_data["symbol"],
            entry_price=pos_data["entry_price"],
            size=pos_data["size"],
            side=pos_data["side"],
            entry_time=datetime.now(timezone.utc),
            current_price=pos_data["entry_price"],
            stop_loss=pos_data.get("stop_loss", 0.0),
            take_profit=pos_data.get("take_profit", 0.0),
        )

        account.add_position(position)

        # Create PaperTrade record
        trade = PaperTrade(
            symbol=pos_data["symbol"],
            order_type=pos_data["side"],
            volume=pos_data["size"],
            execution_price=pos_data["entry_price"],
            spread_applied=pos_data.get("spread_applied", 0.0),
            slippage_applied=pos_data.get("slippage_applied", 0.0),
            timestamp=datetime.now(timezone.utc),
            ticket=result.ticket or 0,
            pnl=equity_change if equity_change != 0.0 else None,
        )

        account.add_trade(trade)

        # Update balance if closing a position (equity_change != 0)
        if equity_change != 0.0:
            account.balance += equity_change
            account.daily_pnl += equity_change

        account.update_equity()

        logger.debug(
            "Account updated: positions=%d, equity=%.2f, balance=%.2f",
            len(account.positions),
            account.equity,
            account.balance,
        )

    def close_position(
        self,
        account: PaperAccount,
        symbol: str,
        side: str,
        close_price: float,
    ) -> Optional[PaperTrade]:
        """Close an open position in paper account.

        Args:
            account: PaperAccount containing the position.
            symbol: Symbol of position to close.
            side: Side of position ("BUY" or "SELL").
            close_price: Price at which to close.

        Returns:
            PaperTrade record of the close, or None if position not found.
        """
        position = account.remove_position(symbol, side)
        if not position:
            logger.warning("Position not found for close: %s %s", symbol, side)
            return None

        # Calculate realized P&L
        if position.side.upper() == "BUY":
            pnl = (close_price - position.entry_price) * position.size * 100000
        else:
            pnl = (position.entry_price - close_price) * position.size * 100000

        # Create close trade record
        close_trade = PaperTrade(
            symbol=symbol,
            order_type="SELL" if side.upper() == "BUY" else "BUY",
            volume=position.size,
            execution_price=close_price,
            spread_applied=self.spread_config.get_spread(symbol) / 2.0,
            slippage_applied=0.0,
            timestamp=datetime.now(timezone.utc),
            pnl=pnl,
        )

        account.add_trade(close_trade)
        account.balance += pnl
        account.daily_pnl += pnl
        account.update_equity()

        logger.info(
            "Position closed: %s %s, P&L=%.2f, close_price=%.5f",
            symbol,
            side,
            pnl,
            close_price,
        )

        # PRD §18.1: auto-trigger post-trade review for the closed position.
        # Fail-safe: any review error is logged inside the hook, never raised.
        if self.auto_review:
            self._trigger_review(
                trade_id=str(getattr(position, "ticket", 0) or symbol),
                symbol=symbol,
                side=side,
                position=position,
                close_price=close_price,
                pnl=pnl,
                close_trade=close_trade,
            )

        return close_trade

    def _trigger_review(
        self,
        trade_id: str,
        symbol: str,
        side: str,
        position: Any,
        close_price: float,
        pnl: float,
        close_trade: PaperTrade,
    ) -> None:
        """Invoke the review auto-trigger for a just-closed position (fail-safe)."""
        try:
            from review.auto_trigger import on_position_closed

            on_position_closed(
                {
                    "trade_id": trade_id,
                    "symbol": symbol,
                    "direction": position.side,
                    "entry_price": position.entry_price,
                    "close_price": close_price,
                    "pnl": pnl,
                    "slippage": close_trade.slippage_applied,
                    "status": "CLOSED",
                }
            )
        except Exception as exc:  # pragma: no cover - defensive, never break close
            logger.warning("Auto-review trigger failed for %s: %s", symbol, exc)

    def get_account_summary(self, account: PaperAccount) -> dict[str, Any]:
        """Get summary of paper account state.

        Args:
            account: PaperAccount to summarize.

        Returns:
            Dict with balance, equity, margin, positions, P&L, drawdown.
        """
        return {
            "account_id": account.account_id,
            "balance": account.balance,
            "equity": account.equity,
            "used_margin": account.used_margin,
            "free_margin": account.free_margin,
            "peak_equity": account.peak_equity,
            "drawdown_pct": account.get_drawdown_pct(),
            "daily_pnl": account.daily_pnl,
            "daily_loss_pct": account.get_daily_loss_pct(),
            "open_positions": len(account.positions),
            "total_trades": len(account.history),
            "unrealized_pnl": account.get_total_pnl(),
        }
