# -*- coding: utf-8 -*-
"""MT5 paper trading FastAPI router — read-only endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query, status
from fastapi.responses import JSONResponse

from . import connector
from .schemas import (
    AccountBalanceResponse,
    AccountInfo,
    OHLCResponse,
    OrderExecuteRequest,
    OrderExecuteResponse,
    OrdersResponse,
    PositionsResponse,
    SymbolListResponse,
    TickResponse,
)

router = APIRouter(prefix="/mt5", tags=["mt5-paper-trading"])


# ---------------------------------------------------------------------------
# Mode
# ---------------------------------------------------------------------------


@router.get("/mode")
async def get_mode() -> dict:
    """Report MT5 data mode."""
    return {
        "live_data": connector.is_live_mode(),
        "execution": "disabled (read-only)" if connector.is_live_mode() else "paper",
    }


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------


@router.get("/accounts/info", response_model=AccountInfo)
async def get_account_info() -> AccountInfo:
    """Get MT5 account information (read-only)."""
    try:
        return connector.get_account_info()
    except Exception as e:
        raise RuntimeError(f"Failed to get account info: {e}")


# ---------------------------------------------------------------------------
# Symbols
# ---------------------------------------------------------------------------


@router.get("/symbols", response_model=SymbolListResponse)
async def get_symbols() -> SymbolListResponse:
    """List available trading symbols (read-only)."""
    symbols = connector.get_symbols()
    return SymbolListResponse(symbols=symbols)


# ---------------------------------------------------------------------------
# Market data
# ---------------------------------------------------------------------------


@router.get("/market/tick", response_model=TickResponse)
async def get_market_tick(
    symbol: str = Query(..., min_length=1, description="Symbol name, e.g. EURUSD")
) -> TickResponse:
    """Get latest tick for a symbol (read-only)."""
    tick = connector.get_tick(symbol)
    if tick is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"error": f"Symbol '{symbol}' not found or no tick data available"},
        )
    return TickResponse(data=tick)


@router.get("/market/ohlc", response_model=OHLCResponse)
async def get_market_ohlc(
    symbol: str = Query(..., min_length=1, description="Symbol name"),
    timeframe: str = Query("H1", description="Timeframe: M1, M5, M15, M30, H1, H4, D1, W1, MN1"),
    count: int = Query(100, ge=1, le=1000, description="Number of bars to return"),
) -> OHLCResponse:
    """Get OHLC bars for a symbol (read-only)."""
    bars = connector.get_ohlc(symbol, timeframe, count)
    if not bars:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"error": f"No OHLC data for symbol '{symbol}'"},
        )
    return OHLCResponse(data=bars)


# ---------------------------------------------------------------------------
# Positions (read-only)
# ---------------------------------------------------------------------------


@router.get("/positions", response_model=PositionsResponse)
async def get_positions() -> PositionsResponse:
    """Get all open positions (read-only)."""
    positions = connector.get_positions()
    return PositionsResponse(positions=positions, count=len(positions))


# ---------------------------------------------------------------------------
# Orders (read-only)
# ---------------------------------------------------------------------------


@router.get("/orders", response_model=OrdersResponse)
async def get_orders() -> OrdersResponse:
    """Get all pending orders (read-only)."""
    orders = connector.get_orders()
    return OrdersResponse(orders=orders, count=len(orders))


# ---------------------------------------------------------------------------
# Orders execute (paper trading — simulated, no real execution)
# ---------------------------------------------------------------------------


@router.post("/orders/execute", response_model=OrderExecuteResponse)
async def execute_order(request: OrderExecuteRequest) -> OrderExecuteResponse:
    """Execute an order in paper trading mode (simulated, no real funds at risk).

    This endpoint is SAFE for testing — it never connects to a real MT5
    terminal unless use_live_mode() has been explicitly called.
    """
    result = connector.execute_order(request)
    return OrderExecuteResponse(
        success=result["success"],
        order_id=result["order_id"],
        message=result["message"],
        price=result["price"],
        executed_at=result["executed_at"],
    )


# ---------------------------------------------------------------------------
# Account balance — combined view (read-only)
# ---------------------------------------------------------------------------


@router.get("/accounts/balance", response_model=AccountBalanceResponse)
async def get_account_balance() -> AccountBalanceResponse:
    """Get full account balance overview (read-only).

    Combines account info, open positions, and pending orders with
    aggregated PnL and margin.
    """
    account = connector.get_account_info()
    positions = connector.get_positions()
    orders = connector.get_orders()

    total_unrealized = sum(p.unrealized_pnl for p in positions)
    total_margin = sum(p.margin for p in positions if p.margin)

    return AccountBalanceResponse(
        account=account,
        positions=positions,
        orders=orders,
        total_unrealized_pnl=total_unrealized,
        total_margin=total_margin,
    )
