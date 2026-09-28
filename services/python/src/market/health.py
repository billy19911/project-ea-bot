# -*- coding: utf-8 -*-
"""Market data health utilities – compute freshness and status for a symbol.

Provides a simple health object matching PRD V2 §32:
{
    "symbol": str,
    "tick_age_ms": int,
    "bar_age_ms": int,
    "spread_age_ms": int,
    "feed_connected": bool,
    "last_successful_update": str,  # ISO8601
    "status": "HEALTHY" | "STALE" | "DISCONNECTED" | "INVALID",
}

The logic is lightweight and fail‑safe: any exception results in
`feed_connected=False` and status `DISCONNECTED`.
"""

from __future__ import annotations

import datetime
from typing import Any, Dict

from ..mt5.connector import get_ohlc, get_tick

# Thresholds (ms) – configurable via env if needed, but constants fine for now.
_TICK_STALE_MS = 1500
_BAR_STALE_MS = 3000
_SPREAD_STALE_MS = 2000


def _now_naive_local() -> datetime.datetime:
    """Return current time as a *naive local* datetime.

    The MT5 connector builds tick/bar timestamps with
    ``datetime.fromtimestamp(...)`` (see ``mt5/connector.py``), i.e. **naive
    local** datetimes — not UTC. Comparing them against a UTC "now" produced a
    constant negative age (the WIB-vs-UTC bug that forced every symbol to
    DISCONNECTED). We therefore compare like-for-like: naive local vs naive
    local.
    """
    return datetime.datetime.now()


def compute_market_data_health(symbol: str) -> Dict[str, Any]:
    """Return a health dict for *symbol*.

    - ``tick_age_ms``: age of latest tick.
    - ``bar_age_ms``: age of latest OHLC bar.
    - ``spread_age_ms``: age of latest spread (here we reuse tick age).
    - ``feed_connected``: True only if both tick and bar fetched.
    - ``last_successful_update``: ISO‑8601 of newest timestamp.
    - ``status``: ``HEALTHY`` if all ages < thresholds, ``STALE`` if any exceed,
      ``DISCONNECTED`` if data missing, ``INVALID`` on unexpected errors.
    """
    try:
        tick = get_tick(symbol)
        ohlc = get_ohlc(symbol)
        now = _now_naive_local()
        if not tick or not ohlc:
            return {
                "symbol": symbol,
                "tick_age_ms": 0,
                "bar_age_ms": 0,
                "spread_age_ms": 0,
                "feed_connected": False,
                "last_successful_update": "",
                "status": "DISCONNECTED",
            }
        # ``get_ohlc`` returns a LIST of bars (oldest → newest); the freshest
        # bar is the LAST element. Treating the list itself as an OHLC object
        # (``ohlc.time``) was the original typing bug that made every symbol
        # report DISCONNECTED.
        last_bar = ohlc[-1] if isinstance(ohlc, (list, tuple)) else ohlc
        tick_time = getattr(tick, "time", None)
        bar_time = getattr(last_bar, "time", None)
        # Guard against None
        if not isinstance(tick_time, datetime.datetime) or not isinstance(
            bar_time, datetime.datetime
        ):
            raise ValueError("Invalid time fields")
        # Connector times are naive LOCAL datetimes → compare like-for-like.
        if tick_time.tzinfo is not None:
            tick_time = tick_time.astimezone().replace(tzinfo=None)
        if bar_time.tzinfo is not None:
            bar_time = bar_time.astimezone().replace(tzinfo=None)
        tick_age = int((now - tick_time).total_seconds() * 1000)
        bar_age = int((now - bar_time).total_seconds() * 1000)
        spread_age = tick_age  # spread derived from tick spread; reuse tick age
        # Negative age means the data clock is ahead of us (clock skew) — clamp
        # to 0 rather than reporting a nonsensical negative freshness.
        tick_age = max(0, tick_age)
        bar_age = max(0, bar_age)
        spread_age = max(0, spread_age)
        # Determine status
        if tick_age > _TICK_STALE_MS or bar_age > _BAR_STALE_MS or spread_age > _SPREAD_STALE_MS:
            status = "STALE"
        else:
            status = "HEALTHY"
        latest_ts = max(tick_time, bar_time).isoformat()
        return {
            "symbol": symbol,
            "tick_age_ms": tick_age,
            "bar_age_ms": bar_age,
            "spread_age_ms": spread_age,
            "feed_connected": True,
            "last_successful_update": latest_ts,
            "status": status,
        }
    except Exception:
        # Fail‑closed – report disconnected
        return {
            "symbol": symbol,
            "tick_age_ms": 0,
            "bar_age_ms": 0,
            "spread_age_ms": 0,
            "feed_connected": False,
            "last_successful_update": "",
            "status": "DISCONNECTED",
        }
