# -*- coding: utf-8 -*-
"""Paper Trading Account dataclasses.

Phase 19: Simulated account state tracking for paper trading mode.
Tracks virtual balance, equity, margin, positions, and trade history.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

__all__ = [
    "PaperAccount",
    "PaperPosition",
    "PaperTrade",
]


@dataclass
class PaperPosition:
    """Virtual open position in paper trading account.

    Attributes:
        symbol: Instrument symbol (e.g. "EURUSD").
        entry_price: Price at which position was opened.
        size: Position size in lots.
        side: "BUY" or "SELL".
        entry_time: Timestamp when position opened.
        current_price: Current market price (for P&L calc).
        stop_loss: Stop-loss price level.
        take_profit: Take-profit price level.
        pnl: Unrealized profit/loss (updated on price change).
        pnl_pct: Unrealized P&L as percentage.
    """

    symbol: str
    entry_price: float
    size: float
    side: str  # "BUY" or "SELL"
    entry_time: datetime
    current_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    pnl: float = 0.0
    pnl_pct: float = 0.0

    def __post_init__(self) -> None:
        """Calculate P&L if current_price is set."""
        if self.current_price > 0:
            self._update_pnl()

    def _update_pnl(self) -> None:
        """Update unrealized P&L based on current price."""
        if self.side.upper() == "BUY":
            price_diff = self.current_price - self.entry_price
        else:
            price_diff = self.entry_price - self.current_price

        # Assuming standard contract size 100,000 for forex
        contract_size = 100000
        self.pnl = price_diff * self.size * contract_size

        if self.entry_price > 0:
            self.pnl_pct = (price_diff / self.entry_price) * 100.0

    def update_price(self, new_price: float) -> None:
        """Update current price and recalculate P&L."""
        self.current_price = new_price
        self._update_pnl()


@dataclass
class PaperTrade:
    """Record of a single executed trade in paper account history.

    Attributes:
        symbol: Instrument symbol.
        order_type: Order type ("BUY", "SELL", etc.).
        volume: Trade volume in lots.
        execution_price: Price at which order was executed.
        spread_applied: Spread cost applied (in price units).
        slippage_applied: Slippage cost applied (in price units).
        timestamp: When the trade was executed.
        ticket: Unique trade identifier.
        pnl: Realized P&L if trade closed; None if still open.
    """

    symbol: str
    order_type: str
    volume: float
    execution_price: float
    spread_applied: float
    slippage_applied: float
    timestamp: datetime
    ticket: int = 0
    pnl: Optional[float] = None

    def total_cost(self) -> float:
        """Total execution cost (spread + slippage) in price units."""
        return self.spread_applied + self.slippage_applied


@dataclass
class PaperAccount:
    """Virtual trading account for paper trading (simulated mode).

    Tracks balance, equity, margin usage, open positions, and trade history.

    Attributes:
        account_id: Unique account identifier.
        balance: Account balance (cash).
        equity: Account equity (balance + unrealized P&L).
        peak_equity: Highest equity reached (for drawdown calc).
        used_margin: Margin currently in use.
        free_margin: Available margin (equity - used_margin).
        positions: List of open PaperPosition objects.
        history: List of PaperTrade objects (trade history).
    """

    account_id: str
    initial_balance: float
    balance: float = 0.0
    equity: float = 0.0
    peak_equity: float = 0.0
    used_margin: float = 0.0
    free_margin: float = 0.0
    positions: list[PaperPosition] = field(default_factory=list)
    history: list[PaperTrade] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    daily_pnl: float = 0.0
    daily_trades: int = 0

    def __post_init__(self) -> None:
        """Initialize balance and equity."""
        if self.balance == 0.0:
            self.balance = self.initial_balance
        if self.equity == 0.0:
            self.equity = self.initial_balance
        if self.peak_equity == 0.0:
            self.peak_equity = self.initial_balance
        if self.free_margin == 0.0:
            self.free_margin = self.initial_balance

    def get_total_pnl(self) -> float:
        """Calculate total unrealized P&L from all open positions."""
        return sum(pos.pnl for pos in self.positions)

    def update_equity(self) -> None:
        """Update equity = balance + total unrealized P&L."""
        total_unrealized = self.get_total_pnl()
        self.equity = self.balance + total_unrealized

        # Update peak equity for drawdown tracking
        if self.equity > self.peak_equity:
            self.peak_equity = self.equity

    def update_margin(self, used: float) -> None:
        """Update margin usage and recalculate free margin."""
        self.used_margin = used
        self.free_margin = max(0.0, self.equity - used)

    def add_position(self, position: PaperPosition) -> None:
        """Add an open position to the account."""
        self.positions.append(position)
        self.update_equity()

    def remove_position(self, symbol: str, side: str) -> Optional[PaperPosition]:
        """Remove a position by symbol and side. Returns removed position."""
        for i, pos in enumerate(self.positions):
            if pos.symbol == symbol and pos.side.upper() == side.upper():
                removed = self.positions.pop(i)
                self.update_equity()
                return removed
        return None

    def add_trade(self, trade: PaperTrade) -> None:
        """Record a trade in history."""
        self.history.append(trade)
        self.daily_trades += 1

    def get_drawdown_pct(self) -> float:
        """Calculate current drawdown as percentage."""
        if self.peak_equity <= 0:
            return 0.0
        return ((self.peak_equity - self.equity) / self.peak_equity) * 100.0

    def get_daily_loss_pct(self) -> float:
        """Calculate daily loss as percentage of balance."""
        if self.balance <= 0:
            return 0.0
        return (abs(min(self.daily_pnl, 0.0)) / self.balance) * 100.0

    def reset_daily_stats(self) -> None:
        """Reset daily P&L and trade count (call at midnight)."""
        self.daily_pnl = 0.0
        self.daily_trades = 0
