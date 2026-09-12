# -*- coding: utf-8 -*-
"""Data models for MT5 market data: SymbolInfo, Tick, OHLC."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class Timeframe(str, Enum):
    """MT5 candle timeframes."""

    M1 = "M1"
    M5 = "M5"
    M15 = "M15"
    M30 = "M30"
    H1 = "H1"
    H4 = "H4"
    D1 = "D1"


class SymbolInfo(BaseModel):
    """Metadata for a tradable symbol."""

    symbol: str = Field(..., description="MT5 symbol name, e.g. 'BTCUSD'")
    digits: int = Field(..., ge=0, le=5, description="Number of decimal places")
    point: float = Field(..., gt=0, description="Minimum price increment")
    bid: float = Field(..., description="Current bid price")
    ask: float = Field(..., description="Current ask price")
    spread: int = Field(..., ge=0, description="Spread in points")
    contract_size: float = Field(..., gt=0, description="Contract size / lot value")
    volume_min: float = Field(..., ge=0, description="Minimum allowed volume")
    volume_max: float = Field(..., ge=0, description="Maximum allowed volume")
    tick_value: float = Field(..., ge=0, description="Value per tick")
    tick_size: float = Field(..., ge=0, description="Minimum tick size")
    name: str = Field("", description="Human-readable symbol name")
    path: str = Field("", description="Market watch group path")


class Tick(BaseModel):
    """Real-time tick quote for a symbol."""

    symbol: str
    bid: float
    ask: float
    last: float
    volume: float = Field(..., ge=0)
    time: datetime
    flags: int = Field(0, description="MT5 tick flags bitmask")


class OHLC(BaseModel):
    """Single OHLC candle."""

    symbol: str
    timeframe: Timeframe
    open: float
    high: float
    low: float
    close: float
    tick_volume: float = Field(..., ge=0)
    spread: int = Field(..., ge=0)
    real_volume: float = Field(0, ge=0)
    time: datetime  # candle open time
