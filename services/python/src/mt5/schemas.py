# -*- coding: utf-8 -*-
"""Pydantic schemas for MT5 paper trading API."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Account
# ---------------------------------------------------------------------------


class AccountInfo(BaseModel):
    login: int = Field(..., description="MT5 account login")
    server: str = Field(..., description="MT5 server name")
    balance: float = Field(..., description="Account balance")
    equity: float = Field(..., description="Current equity")
    margin: float = Field(..., description="Used margin")
    free_margin: float = Field(..., description="Free margin available")
    margin_level: float = Field(..., description="Margin level percentage")
    currency: str = Field(default="USD", description="Account currency")
    leverage: int = Field(..., description="Account leverage")
    name: str = Field(..., description="Account holder name")
    trade_mode: str = Field(..., description="Trading mode")


# ---------------------------------------------------------------------------
# Market data
# ---------------------------------------------------------------------------


class Tick(BaseModel):
    symbol: str
    bid: float
    ask: float
    last: float
    volume: float
    time: datetime


class OHLC(BaseModel):
    symbol: str
    timeframe: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    time: datetime


# ---------------------------------------------------------------------------
# Positions
# ---------------------------------------------------------------------------


class Position(BaseModel):
    ticket: int
    symbol: str
    side: str  # BUY / SELL
    quantity: float
    price_open: float
    price_current: float
    swap: float
    profit: float
    unrealized_pnl: float
    margin: float
    entry: str  # POSITION_ENTRY_IN / OUT
    status: str
    time: datetime
    time_update: datetime


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------


class Order(BaseModel):
    ticket: int
    symbol: str
    side: str
    order_type: str
    price: float
    stop_price: Optional[float]
    quantity: float
    filled_qty: float
    status: str
    time_setup: datetime
    time_expiration: Optional[datetime]


class OrderExecuteRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=64)
    side: str = Field(..., pattern="^BUY|SELL$")
    order_type: str = Field(..., pattern="^MARKET|LIMIT|STOP$")
    quantity: float = Field(..., gt=0)
    price: Optional[float] = Field(None, ge=0)
    stop_price: Optional[float] = Field(None, ge=0)
    comment: str = Field(default="paper", max_length=128)


class OrderExecuteResponse(BaseModel):
    success: bool
    order_id: Optional[int] = None
    message: str
    price: Optional[float] = None
    executed_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Market overview
# ---------------------------------------------------------------------------


class SymbolInfo(BaseModel):
    symbol: str
    bid: float
    ask: float
    spread: int
    digits: int
    contract_size: float
    point: float
    trade_mode: str
    currency_profit: str
    currency_margin: str


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------


class AccountBalanceResponse(BaseModel):
    account: AccountInfo
    positions: list[Position]
    orders: list[Order]
    total_unrealized_pnl: float
    total_margin: float


class SymbolListResponse(BaseModel):
    symbols: list[SymbolInfo]


class TickResponse(BaseModel):
    data: Tick


class OHLCResponse(BaseModel):
    data: list[OHLC]


class PositionsResponse(BaseModel):
    positions: list[Position]
    count: int


class OrdersResponse(BaseModel):
    orders: list[Order]
    count: int
