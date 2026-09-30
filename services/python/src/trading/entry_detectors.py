# -*- coding: utf-8 -*-
"""Canonical OB/FVG detectors (Phase 4 §6–§10) producing :class:`Zone` objects.
These are STRICTER than the legacy positional ``entry_zone`` detectors: an OB
requires (a) an opposite-colour origin candle, (b) measurable DISPLACEMENT
after it (body/ATR), and (c) optional structural-alignment context. An FVG
requires a real 3-candle imbalance AND a minimum gap size normalised by ATR.
Pure functions over injected OHLC lists — no I/O, no MT5, no future leakage:
a candle at index ``i`` may only use data at or before ``i`` (§44).
"""
from __future__ import annotations

from typing import Optional

from .entry_config import ZoneConfig
from .entry_zones import Zone, zone_identity

__all__ = ["detect_order_blocks", "detect_fvgs"]


def _body(open_: float, close: float) -> float:
    return abs(float(close) - float(open_))


def detect_order_blocks(
    *,
    symbol: str,
    timeframe: str,
    opens: list[float],
    highs: list[float],
    lows: list[float],
    closes: list[float],
    atr: float,
    config: Optional[ZoneConfig] = None,
    invalidation_tf: str = "",
) -> list[Zone]:
    """Detect structurally-significant order blocks (§6–§8).
    An OB candidate is the LAST opposite-colour candle immediately preceding a
    displacement move: bullish OB = bearish origin candle + strong bullish
    follow candle; bearish OB = bullish origin + strong bearish follow. The
    follow candle's body must be ≥ ``ob_min_displacement_atr × ATR`` (default
    0.5) — every opposite candle is NOT an OB.
    Zone = the origin candle's high/low; invalidation = the far edge
    (bullish OB invalidated by a close below the origin low; bearish by a close
    above the origin high).
    """
    cfg = config or ZoneConfig()
    zones: list[Zone] = []
    n = min(len(opens), len(highs), len(lows), len(closes))
    if n < 3 or atr <= 0:
        return zones
    start = max(1, n - cfg.ob_lookback)
    for i in range(start, n - 1):
        origin_red = closes[i] < opens[i]  # bearish origin candle
        origin_green = closes[i] > opens[i]  # bullish origin candle
        follow_body = _body(opens[i + 1], closes[i + 1])
        if follow_body < cfg.ob_min_displacement_atr * atr:
            continue
        follow_green = closes[i + 1] > opens[i + 1]
        follow_red = closes[i + 1] < opens[i + 1]
        # Bullish OB: bearish origin → bullish displacement.
        if origin_red and follow_green:
            top, bottom = float(highs[i]), float(lows[i])
            zones.append(
                Zone(
                    zone_id=zone_identity(
                        symbol=symbol,
                        timeframe=timeframe,
                        direction="LONG",
                        zone_type="ORDER_BLOCK",
                        anchor_price=(top + bottom) / 2.0,
                        anchor_index=i,
                    ),
                    symbol=symbol,
                    direction="LONG",
                    zone_type="ORDER_BLOCK",
                    timeframe=timeframe,
                    top=top,
                    bottom=bottom,
                    invalidation_price=bottom,
                    invalidation_rule="close below OB low (bullish OB)",
                    displacement_atr=round(follow_body / atr, 4),
                    structure_break="BULLISH_DISPLACEMENT",
                    origin_index=i,
                    metadata={"follow_index": i + 1},
                )
            )
        # Bearish OB: bullish origin → bearish displacement.
        elif origin_green and follow_red:
            top, bottom = float(highs[i]), float(lows[i])
            zones.append(
                Zone(
                    zone_id=zone_identity(
                        symbol=symbol,
                        timeframe=timeframe,
                        direction="SHORT",
                        zone_type="ORDER_BLOCK",
                        anchor_price=(top + bottom) / 2.0,
                        anchor_index=i,
                    ),
                    symbol=symbol,
                    direction="SHORT",
                    zone_type="ORDER_BLOCK",
                    timeframe=timeframe,
                    top=top,
                    bottom=bottom,
                    invalidation_price=top,
                    invalidation_rule="close above OB high (bearish OB)",
                    displacement_atr=round(follow_body / atr, 4),
                    structure_break="BEARISH_DISPLACEMENT",
                    origin_index=i,
                    metadata={"follow_index": i + 1},
                )
            )
    return zones


def detect_fvgs(
    *,
    symbol: str,
    timeframe: str,
    highs: list[float],
    lows: list[float],
    atr: float,
    config: Optional[ZoneConfig] = None,
) -> list[Zone]:
    """Detect Fair Value Gaps (§9–§10) with ATR-normalized quality gate.
    Bullish FVG: ``highs[i-1] < lows[i+1]`` (gap between candle i-1 high and
    candle i+1 low). Bearish: ``lows[i-1] > highs[i+1]``. Gaps smaller than
    ``fvg_min_gap_atr × ATR`` are rejected as noise. Invalidation = full
    fill-through of the gap.
    """
    cfg = config or ZoneConfig()
    zones: list[Zone] = []
    n = min(len(highs), len(lows))
    if n < 3 or atr <= 0:
        return zones
    start = max(1, n - cfg.fvg_lookback)
    for i in range(start, n - 1):
        # Bullish FVG.
        if lows[i + 1] > highs[i - 1]:
            bottom, top = float(highs[i - 1]), float(lows[i + 1])
            gap = top - bottom
            if gap < cfg.fvg_min_gap_atr * atr:
                continue
            zones.append(
                Zone(
                    zone_id=zone_identity(
                        symbol=symbol,
                        timeframe=timeframe,
                        direction="LONG",
                        zone_type="FVG",
                        anchor_price=(top + bottom) / 2.0,
                        anchor_index=i,
                    ),
                    symbol=symbol,
                    direction="LONG",
                    zone_type="FVG",
                    timeframe=timeframe,
                    top=top,
                    bottom=bottom,
                    invalidation_price=bottom,
                    invalidation_rule="full fill below FVG (bullish)",
                    gap_atr=round(gap / atr, 4),
                    origin_index=i,
                )
            )
        # Bearish FVG.
        elif highs[i + 1] < lows[i - 1]:
            bottom, top = float(highs[i + 1]), float(lows[i - 1])
            gap = top - bottom
            if gap < cfg.fvg_min_gap_atr * atr:
                continue
            zones.append(
                Zone(
                    zone_id=zone_identity(
                        symbol=symbol,
                        timeframe=timeframe,
                        direction="SHORT",
                        zone_type="FVG",
                        anchor_price=(top + bottom) / 2.0,
                        anchor_index=i,
                    ),
                    symbol=symbol,
                    direction="SHORT",
                    zone_type="FVG",
                    timeframe=timeframe,
                    top=top,
                    bottom=bottom,
                    invalidation_price=top,
                    invalidation_rule="full fill above FVG (bearish)",
                    gap_atr=round(gap / atr, 4),
                    origin_index=i,
                )
            )
    return zones
