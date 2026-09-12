# -*- coding: utf-8 -*-
"""MT5 market-data retrieval helpers.

Provides lazy import of MetaTrader5 so the module can be imported even when
MT5 is not installed (import only fails at call-time).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from .models import OHLC, SymbolInfo, Tick, Timeframe

logger = logging.getLogger(__name__)

# Lazy MT5 import — falls back to None when library is absent
try:
    import MetaTrader5 as mt5  # type: ignore[import-untyped]
except Exception:  # pragma: no cover
    mt5 = None  # type: ignore[assignment]

_TIMEFRAME_MAP = {
    "M1": mt5.TIMEFRAME_M1 if mt5 else 0,
    "M5": mt5.TIMEFRAME_M5 if mt5 else 0,
    "M15": mt5.TIMEFRAME_M15 if mt5 else 0,
    "M30": mt5.TIMEFRAME_M30 if mt5 else 0,
    "H1": mt5.TIMEFRAME_H1 if mt5 else 0,
    "H4": mt5.TIMEFRAME_H4 if mt5 else 0,
    "D1": mt5.TIMEFRAME_D1 if mt5 else 0,
}


def _require_mt5() -> None:
    """Raise if MetaTrader5 is not installed."""
    if mt5 is None:
        raise RuntimeError(
            "MetaTrader5 Python package is not installed. " "Install with: pip install MetaTrader5"
        )


def get_symbol_info(symbol: str) -> Optional[SymbolInfo]:
    """Return SymbolInfo for *symbol*, or None if not found."""
    _require_mt5()
    raw = mt5.symbol_info(symbol)
    if raw is None:
        logger.warning("symbol_info returned None for %r", symbol)
        return None
    return SymbolInfo(
        symbol=raw.name,
        digits=raw.digits,
        point=raw.point,
        bid=raw.bid,
        ask=raw.ask,
        spread=raw.spread,
        contract_size=raw.trade_contract_size,
        volume_min=raw.volume_min,
        volume_max=raw.volume_max,
        tick_value=raw.trade_tick_value,
        tick_size=raw.trade_tick_size,
        name=raw.name,
        path=raw.path,
    )


def get_tick(symbol: str) -> Optional[Tick]:
    """Return the latest Tick for *symbol*, or None on failure."""
    _require_mt5()
    raw = mt5.symbol_info_tick(symbol)
    if raw is None:
        logger.warning("symbol_info_tick returned None for %r", symbol)
        return None
    return Tick(
        symbol=symbol,
        bid=raw.bid,
        ask=raw.ask,
        last=raw.last,
        volume=raw.volume,
        time=datetime.fromtimestamp(raw.time),
        flags=raw.flags,
    )


def get_ohlc(
    symbol: str,
    timeframe: Timeframe = Timeframe.M1,
    count: int = 100,
    since: Optional[datetime] = None,
) -> list[OHLC]:
    """Return *count* OHLC candles for *symbol*.

    Args:
        symbol: MT5 symbol name.
        timeframe: Candle interval (default M1).
        count: Max number of candles to retrieve (default 100).
        since: If given, fetch candles starting from this datetime.

    Returns:
        List of OHLC bars, newest first (MT5 default).  Empty list on failure.
    """
    _require_mt5()
    tf = _TIMEFRAME_MAP[timeframe.value]
    if since is not None:
        timestamp = int(since.timestamp())
        rates = mt5.copy_rates_from(symbol, tf, timestamp, count)
    else:
        rates = mt5.copy_rates_from_pos(symbol, tf, 0, count)

    if rates is None or len(rates) == 0:
        logger.warning("copy_rates returned empty for %r tf=%s", symbol, timeframe.value)
        return []

    return [
        OHLC(
            symbol=symbol,
            timeframe=timeframe,
            open=float(r["open"]),
            high=float(r["high"]),
            low=float(r["low"]),
            close=float(r["close"]),
            tick_volume=float(r["tick_volume"]),
            spread=int(r["spread"]),
            real_volume=float(r["real_volume"]),
            time=datetime.fromtimestamp(int(r["time"])),
        )
        for r in rates
    ]
