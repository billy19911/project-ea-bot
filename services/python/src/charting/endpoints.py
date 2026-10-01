# -*- coding: utf-8 -*-
"""Charting FastAPI router — real OHLC candles + indicator series (Fase 1).

Read-only: pulls bars through ``mt5.connector.get_ohlc`` and computes series
with the project's own indicator functions. Never sends orders, never re-binds
the terminal. When data is unavailable the payload says ``ok: false`` with a
reason — no fake candles, no fake zeros.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

from ..strategy.endpoints import get_active_strategy_config
from ..trading.engine import TradingEngine
from ..trading.entry_zone import detect_entry_zones
from ..trading.indicators import atr_series
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
    before: Optional[str] = Query(
        None,
        description=(
            "ISO timestamp — return the `bars` candles immediately BEFORE this "
            "time (chart lazy-loads older history when panned left)."
        ),
    ),
) -> dict[str, Any]:
    """Candles + indicator series for one symbol/timeframe (read-only).

    Returns ``ok: false`` with a human-readable reason when MT5 is not in live
    mode or the symbol has no bars — never a chart of fabricated data. When
    ``before`` is supplied only a window of older history is returned and
    ``has_more`` reports whether even older bars exist.
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

    before_dt: Optional[datetime] = None
    if before:
        try:
            before_dt = datetime.fromisoformat(before.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            raise HTTPException(status_code=400, detail="`before` harus format ISO-8601.")

    from ..mt5 import connector

    if not connector.is_live_mode():
        return {
            "ok": False,
            "reason": (
                "MT5 tidak dalam mode data live — chart hanya menggambar bar nyata "
                "dari terminal. Aktifkan mode data live pada terminal yang terhubung."
            ),
        }

    bars_data = connector.get_ohlc(symbol, timeframe, bars, before=before_dt)
    if not bars_data:
        return {
            "ok": False,
            "reason": (
                f"Tidak ada bar untuk {symbol} {timeframe}. Periksa nama simbol "
                "di Market Watch terminal MT5."
            ),
        }
    # The minimum-bars guard only applies to the initial (latest) window; a
    # history page legitimately returns fewer bars when history runs out.
    if before_dt is None and len(bars_data) < _MIN_BARS:
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

    # Tell the client whether even older history exists, so paging can stop.
    oldest = bars_data[0].time
    has_more = False
    if len(bars_data) >= bars:
        older_probe = connector.get_ohlc(symbol, timeframe, 1, before=oldest)
        has_more = len(older_probe) > 0

    return {
        "ok": True,
        "symbol": symbol,
        "timeframe": timeframe,
        "bars": payload["bars"],
        "overlays": payload["overlays"],
        "panels": payload["panels"],
        "has_more": has_more,
        "before": before_dt.isoformat() if before_dt else None,
        "provenance": {
            "source": "mt5",
            "mode": "live-read-only",
            "bar_count": len(bars_data),
        },
    }


def _symbol_matches(chart_symbol: str, position_symbol: str) -> bool:
    """True when a position belongs to the charted symbol.

    MT5 brokers often suffix symbols (``XAUUSD`` vs ``XAUUSDc``), so an exact
    match or one-sided prefix both count — nothing looser.
    """
    a, b = chart_symbol.upper(), position_symbol.upper()
    return a == b or a.startswith(b) or b.startswith(a)


def _zones_for_bars(symbol: str, timeframe: str, bars: list[Any]) -> list[dict[str, Any]]:
    """Use the live entry detector to build chart zones from real OHLC bars."""

    def values(key: str) -> list[float]:
        result = []
        for bar in bars:
            value = bar.get(key, 0.0) if isinstance(bar, dict) else getattr(bar, key, 0.0)
            try:
                result.append(float(value))
            except (TypeError, ValueError):
                result.append(0.0)
        return result

    opens, highs, lows, closes = (values(key) for key in ("open", "high", "low", "close"))
    if len(closes) < 16:
        return []
    atr_values = atr_series(highs[:-1], lows[:-1], closes[:-1], 14)
    atr = float(atr_values[-1]) if atr_values and atr_values[-1] is not None else 0.0
    zones = detect_entry_zones(
        symbol=symbol,
        timeframe=timeframe,
        opens=opens,
        highs=highs,
        lows=lows,
        closes=closes,
        atr=atr,
    )
    reference_price = closes[-2]
    counts: dict[tuple[str, str], int] = {}
    selected: list[dict[str, Any]] = []
    for zone in sorted(zones, key=lambda item: abs(float(item["mid"]) - reference_price)):
        group = (str(zone["zone_type"]), str(zone["direction"]))
        if counts.get(group, 0) >= 2:
            continue
        counts[group] = counts.get(group, 0) + 1
        selected.append(zone)
    return selected


@router.get("/analysis")
async def get_chart_analysis(
    symbol: str = Query(..., min_length=1, max_length=32, description="Symbol, e.g. XAUUSD"),
    timeframe: str = Query("H1", description="M1..MN1"),
    bars: int = Query(300, ge=50, le=_MAX_BARS, description="Bars used for analysis"),
) -> dict[str, Any]:
    """Latest trading-engine analysis (entry/SL/TP) + open levels for the chart.

    Read-only. The analysis comes from the project's own :class:`TradingEngine`
    run on real MT5 bars (2x ATR stop, 4x ATR target by default). Open positions
    of the same symbol are returned so the chart can draw their real SL/TP
    levels — a level that is not placed stays ``null``.
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

    from ..mt5 import connector

    if not connector.is_live_mode():
        return {
            "ok": False,
            "reason": (
                "MT5 tidak dalam mode data live — analisa hanya dijalankan pada bar "
                "nyata dari terminal."
            ),
        }

    bars_data = connector.get_ohlc(symbol, timeframe, bars)
    if not bars_data or len(bars_data) < 50:
        return {
            "ok": False,
            "reason": (
                f"Bar tidak cukup untuk analisa {symbol} {timeframe}: "
                f"{0 if not bars_data else len(bars_data)} terbaca (minimum 50)."
            ),
        }

    # TASK 11: resolve the REAL account equity for position sizing. When it is
    # unavailable we do NOT substitute a fabricated 10000 — we mark the sizing
    # as unbound so the response never implies a real lot size.
    equity: Optional[float] = None
    try:
        equity = float(connector.get_account_info().equity)
    except Exception:
        equity = None  # sizing equity unknown — flagged in provenance below
    sizing_equity = equity if equity is not None else 0.0

    engine = TradingEngine(config=get_active_strategy_config())
    result = engine.analyze(
        bars_data, symbol=symbol, timeframe=timeframe, account_equity=sizing_equity
    )
    signal = result.signal

    import os

    scan_timeframe = (os.getenv("ZONE_TF") or "M5").strip().upper()
    if scan_timeframe not in SUPPORTED_TIMEFRAMES:
        scan_timeframe = "M5"
    chart_zones = _zones_for_bars(symbol, timeframe, bars_data)
    if scan_timeframe == timeframe:
        scan_zones = chart_zones
    else:
        scan_bars = connector.get_ohlc(symbol, scan_timeframe, 60) or []
        scan_zones = _zones_for_bars(symbol, scan_timeframe, scan_bars)

    open_positions = []
    try:
        for pos in connector.get_positions():
            if not _symbol_matches(symbol, pos.symbol):
                continue
            open_positions.append(
                {
                    "ticket": pos.ticket,
                    "symbol": pos.symbol,
                    "side": pos.side,
                    "volume": pos.quantity,
                    "entry": pos.price_open,
                    "current": pos.price_current,
                    "sl": pos.sl,
                    "tp": pos.tp,
                    "profit": pos.profit,
                }
            )
    except Exception:
        open_positions = []  # chart levels for live positions are best-effort

    snap = signal.indicators
    return {
        "ok": True,
        "symbol": symbol,
        "timeframe": timeframe,
        "bar_count": len(bars_data),
        "analysis": {
            "signal": signal.signal_type.value,
            "confidence": signal.confidence,
            "entry": signal.entry_price,
            "stop_loss": signal.stop_loss,
            "take_profit": signal.take_profit,
            "atr": signal.atr_value,
            # TASK 11: no fabricated sizing — None when equity is unknown.
            "position_size": signal.position_size if equity is not None else None,
            "reason": signal.reason,
            "close": result.close,
            "timestamp": result.timestamp,
        },
        "indicators": {
            "ema_fast": snap.ema_fast,
            "ema_slow": snap.ema_slow,
            "rsi": snap.rsi,
            "macd_line": snap.macd_line,
            "macd_signal": snap.macd_signal,
            "macd_histogram": snap.macd_histogram,
            "atr": snap.atr,
        },
        "positions": open_positions,
        "zones": {
            "scan_timeframe": scan_timeframe,
            "scan": scan_zones,
            "chart_timeframe": timeframe,
            "chart": chart_zones,
        },
        "provenance": {
            "source": "mt5",
            "mode": "live-read-only",
            "engine": "trading.TradingEngine",
            "stop_multiplier": engine.config["atr_stop_multiplier"],
            "reward_risk_ratio": engine.config["reward_risk_ratio"],
            # Risiko per trade (%) — angka yang benar-benar dipakai engine untuk
            # sizing. ``position_size`` mentah TIDAK ditampilkan sebagai lot:
            # satuannya belum dinormalisasi ke lot broker (butuh contract size).
            "risk_percent": engine.config["risk_percent"],
            # TASK 11: whether position sizing used the real account equity.
            "sizing_equity_bound": equity is not None,
        },
    }
