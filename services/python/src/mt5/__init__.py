# -*- coding: utf-8 -*-
"""MT5 paper trading package — read-only API endpoints."""

from __future__ import annotations

from ._connector_base import MT5Config, MT5Connector, MT5Error, MT5Health
from .connection_manager import ConnectionState, ConnectionStats, MT5ConnectionManager
from .connector import (
    SIMULATED_PRICES,
    SIMULATED_SYMBOLS,
    execute_order,
    get_account_info,
    get_ohlc,
    get_orders,
    get_positions,
    get_symbol_info,
    get_symbols,
    get_tick,
    is_live_mode,
    shutdown,
    use_live_mode,
)
from .models import OHLC, SymbolInfo, Tick, Timeframe
from .schemas import (
    AccountBalanceResponse,
    AccountInfo,
    Order,
    OrderExecuteRequest,
    OrderExecuteResponse,
    OrdersResponse,
    Position,
    PositionsResponse,
)
from .schemas import SymbolInfo as SymbolInfoSchema
from .schemas import Tick as TickSchema

__all__ = [
    # Simulation constants
    "SIMULATED_PRICES",
    "SIMULATED_SYMBOLS",
    # Data access functions (read-only)
    "get_account_info",
    "get_symbols",
    "get_tick",
    "get_ohlc",
    "get_positions",
    "get_orders",
    "execute_order",
    "get_symbol_info",
    # Live / simulation mode
    "use_live_mode",
    "is_live_mode",
    "shutdown",
    # Connector classes
    "MT5Config",
    "MT5Connector",
    "MT5Error",
    "MT5Health",
    # Connection manager
    "ConnectionState",
    "ConnectionStats",
    "MT5ConnectionManager",
    # Models
    "OHLC",
    "SymbolInfo",
    "Tick",
    "Timeframe",
    # Schemas
    "AccountInfo",
    "AccountBalanceResponse",
    "Order",
    "OrderExecuteRequest",
    "OrderExecuteResponse",
    "OrdersResponse",
    "Position",
    "PositionsResponse",
    "SymbolInfoSchema",
    "TickSchema",
]
