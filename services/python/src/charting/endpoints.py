# -*- coding: utf-8 -*-
"""Charting FastAPI router — real OHLC candles + indicator series (Fase 1).

Read-only: pulls bars through ``mt5.connector.get_ohlc`` and computes series
with the project's own indicator functions. Never sends orders, never re-binds
the terminal. When data is unavailable the payload says ``ok: false`` with a
reason — no fake candles, no fake zeros.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from .series import SUPPORTED_TIMEFRAMES, build_chart_payload

router = APIRouter(prefix="/chart", tags=["chart"])

_SYMBOL_RE = re.compile(r"^[A-Z0-9._#+-]{1,32}$")

_MIN_BARS = 30
_MAX_BARS = 1000


@router.get("/candles")
async def get_chart_candles(
    symbol: str = Query(..., min_length=1, max_length=32, description="Symbol, e.g. XAUUSD"),
    timeframe: str = Query("H1", description="M1..MN1"),
    bars: int = Query(300, ge=_MIN_BARS, le=_MAX_BARS, description="Number of candles"),
    ema_fast: int = Query(20, ge=1, le=400, description="Fast EMA period (overlay)"),
    ema_slow: int = Query(50, ge=2, le=400, description="Slow EMA period (overlay)"),
) -> dict[str, Any]:
    """Candles + indicator series for one symbol/timeframe (read-only).

    Returns ``ok: false`` with a human-readable reason when MT5 is not in live
    mode or the symbol has no bars — never a chart of fabricated data.
    """
    symbol = symbol.strip().upper()
    timeframe = timeframe.strip().upper()

    if not _SYMBOL_RE.match(symbol):
        raise HTTPException(status_code=400, detail="Simbol tidak valid.")
    if timeframe not in SUPPORTED_TIMEFRAMES:
        raise HTTPException(
            status_code=400,
            detail=f"Timeframe tidak dikenal: {timeframe}. "
            f"Pilihan: {', '.join(SUPPORTED_TIMEFRAMES)}",
        )
    if ema_slow <= ema_fast:
        raise HTTPException(status_code=400, detail="ema_slow harus lebih besar dari ema_fast.")

    from ..mt5 import connector

    if not connector.is_live_mode():
        return {
            "ok": False,
            "reason": (
                "MT5 tidak dalam mode data live — chart hanya menggambar bar nyata "
                "dari terminal. Aktifkan mode data live pada terminal yang terhubung."
            ),
        }

    bars_data = connector.get_ohlc(symbol, timeframe, bars)
    if not bars_data:
        return {
            "ok": False,
            "reason": (
                f"Tidak ada bar untuk {symbol} {timeframe}. Periksa nama simbol "
                "di Market Watch terminal MT5."
            ),
        }
    if len(bars_data) < _MIN_BARS:
        return {
            "ok": False,
            "reason": (
                f"Bar tidak cukup untuk {symbol} {timeframe}: {len(bars_data)} terbaca "
                f"(minimum {_MIN_BARS})."
            ),
        }

    payload = build_chart_payload(
        bars_data,
        ema_fast=ema_fast,
        ema_slow=ema_slow,
    )

    return {
        "ok": True,
        "symbol": symbol,
        "timeframe": timeframe,
        "bars": payload["bars"],
        "overlays": payload["overlays"],
        "panels": payload["panels"],
        "provenance": {
            "source": "mt5",
            "mode": "live-read-only",
            "bar_count": len(bars_data),
        },
    }
