# -*- coding: utf-8 -*-
"""Deterministic trigger engine (Phase 4 §14–§25, §35).

Evaluates trigger types INDEPENDENTLY over injected OHLC data:

    REJECTION / DISPLACEMENT / MICRO_BOS / MOMENTUM_SHIFT / CANDLE_CLOSE

Each detector returns :class:`TriggerEvidence` or None. The engine NEVER uses
future candles (§44): for a candle at index ``t`` only data at or before ``t``
is consulted. Conditions are explicit (met/missing/blocking) — NO black-box
``trigger_score`` (§22).

Candle semantics (§19): callers pass ``is_closed`` for the last candle. When
the config requires candle close, detectors ignore forming candles.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

from .entry_config import TriggerConfig

__all__ = [
    "TriggerEvidence",
    "TriggerResult",
    "evaluate_triggers",
    "TRIGGER_REJECTION",
    "TRIGGER_DISPLACEMENT",
    "TRIGGER_MICRO_BOS",
    "TRIGGER_MOMENTUM_SHIFT",
    "TRIGGER_CANDLE_CLOSE",
    "TRIGGER_ZONE_TOUCH",
]

TRIGGER_ZONE_TOUCH = "zone_touch"
TRIGGER_REJECTION = "rejection"
TRIGGER_DISPLACEMENT = "displacement"
TRIGGER_MICRO_BOS = "micro_bos"
TRIGGER_MOMENTUM_SHIFT = "momentum_shift"
TRIGGER_CANDLE_CLOSE = "candle_close"

_ALL_TRIGGERS = (
    TRIGGER_ZONE_TOUCH,
    TRIGGER_REJECTION,
    TRIGGER_DISPLACEMENT,
    TRIGGER_MICRO_BOS,
    TRIGGER_MOMENTUM_SHIFT,
    TRIGGER_CANDLE_CLOSE,
)


@dataclass(frozen=True)
class TriggerEvidence:
    """One confirmed trigger observation (§24) with provenance."""

    type: str
    direction: str
    timeframe: str
    detected_at_ts: float
    trigger_price: float
    break_price: float = 0.0
    detail: str = ""
    source_id: str = ""
    source_type: str = "detector"
    derived_from: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "direction": self.direction,
            "timeframe": self.timeframe,
            "detected_at_ts": self.detected_at_ts,
            "trigger_price": self.trigger_price,
            "break_price": self.break_price,
            "detail": self.detail,
            "source_id": self.source_id,
            "source_type": self.source_type,
            "derived_from": self.derived_from,
        }


@dataclass
class TriggerResult:
    """Full evaluation outcome: per-trigger met/missing + blocking + evidence."""

    conditions_met: dict[str, bool] = field(default_factory=dict)
    evidence: list[TriggerEvidence] = field(default_factory=list)
    blocking: list[str] = field(default_factory=list)
    trigger_time_ts: float = 0.0
    trigger_price: float = 0.0

    @property
    def triggers_detected(self) -> list[str]:
        return [k for k, v in self.conditions_met.items() if v]

    def is_fresh(self, max_age_s: float, now_ts: Optional[float] = None) -> bool:
        """False when the trigger is older than ``max_age_s`` (§25)."""
        if not self.trigger_time_ts:
            return False
        now = float(now_ts if now_ts is not None else time.time())
        return (now - self.trigger_time_ts) <= max(0.0, float(max_age_s))

    def to_dict(self) -> dict[str, Any]:
        return {
            "conditions_met": dict(self.conditions_met),
            "triggers_detected": self.triggers_detected,
            "blocking": list(self.blocking),
            "trigger_time_ts": self.trigger_time_ts,
            "trigger_price": self.trigger_price,
            "evidence": [e.to_dict() for e in self.evidence],
        }


def _is_long(direction: str) -> bool:
    return str(direction).upper() in ("LONG", "BUY", "BULLISH")


def evaluate_triggers(
    *,
    direction: str,
    zone_top: float,
    zone_bottom: float,
    opens: list[float],
    highs: list[float],
    lows: list[float],
    closes: list[float],
    atr: float,
    timeframe: str = "M5",
    config: Optional[TriggerConfig] = None,
    is_closed: bool = True,
    spread_atr: float = 0.0,
    news_blocked: bool = False,
    structure_invalidated: bool = False,
    now_ts: Optional[float] = None,
    candle_ts: Optional[float] = None,
) -> TriggerResult:
    """Evaluate all trigger types over CLOSED-prefix data (§14–§25).

    The LAST candle is only evaluated when ``is_closed`` is True (§19).
    When False, detectors run over ``data[:-1]`` (no forming-candle trigger).

    Blocking conditions (§21): spread too wide (spread_atr > max_spread_atr),
    structure invalidated, high-impact news nearby → recorded in ``blocking``.
    """
    cfg = config or TriggerConfig()
    n = min(len(opens), len(highs), len(lows), len(closes))
    result = TriggerResult()
    if n < 3 or atr <= 0:
        # Unknown data → nothing confirmed (fail-closed §49).
        for t in _ALL_TRIGGERS:
            result.conditions_met[t] = False
        result.blocking.append("insufficient_data")
        return result

    # No-future-leakage + candle-close semantics: exclude the forming candle.
    end = n if is_closed else n - 1
    if end < 3:
        for t in _ALL_TRIGGERS:
            result.conditions_met[t] = False
        result.blocking.append("candle_not_closed")
        return result

    o, h, lo, c = opens[:end], highs[:end], lows[:end], closes[:end]
    ts = float(candle_ts if candle_ts is not None else (now_ts or time.time()))
    is_long = _is_long(direction)
    last = end - 1

    # ── zone_touch: last CLOSED candle range intersects the zone ──────────
    touched = lo[last] <= zone_top and h[last] >= zone_bottom
    result.conditions_met[TRIGGER_ZONE_TOUCH] = bool(touched)

    # ── rejection (§15): wick penetrates zone, body closes back, ratio ok ──
    rej = _detect_rejection(
        is_long,
        zone_top,
        zone_bottom,
        o[last],
        h[last],
        lo[last],
        c[last],
        cfg.rejection_min_wick_ratio,
    )
    result.conditions_met[TRIGGER_REJECTION] = rej is not None

    # ── displacement (§16): body/ATR + range/ATR thresholds ───────────────
    disp, disp_detail = _detect_displacement(
        is_long,
        o[last],
        h[last],
        lo[last],
        c[last],
        atr,
        cfg.displacement_min_body_atr,
        cfg.displacement_min_range_atr,
    )
    result.conditions_met[TRIGGER_DISPLACEMENT] = disp

    # ── micro BOS (§17): local swing break on the trigger series ──────────
    micro, break_price = _detect_micro_bos(is_long, h[:end], lo[:end], cfg.micro_bos_lookback)
    result.conditions_met[TRIGGER_MICRO_BOS] = micro

    # ── momentum shift (§18): EMA fast/slow cross in trigger direction ────
    mom = _detect_momentum_shift(is_long, c[:end], cfg.momentum_fast, cfg.momentum_slow)
    result.conditions_met[TRIGGER_MOMENTUM_SHIFT] = mom

    # ── candle close (§19): only meaningful when the evaluated candle closed.
    result.conditions_met[TRIGGER_CANDLE_CLOSE] = bool(is_closed)

    # ── blocking conditions (§21, §30–§32) ────────────────────────────────
    if spread_atr > 0 and cfg.max_spread_atr > 0 and spread_atr > cfg.max_spread_atr:
        result.blocking.append("spread_too_wide")
    if structure_invalidated:
        result.blocking.append("structure_invalidated")
    if news_blocked:
        result.blocking.append("news_high_impact")

    # Evidence records for every confirmed trigger (§24).
    price = c[last]
    for ttype, ok, detail, brk in (
        (TRIGGER_ZONE_TOUCH, touched, "candle range intersects zone", 0.0),
        (TRIGGER_REJECTION, rej is not None, rej or "", 0.0),
        (TRIGGER_DISPLACEMENT, disp, disp_detail, 0.0),
        (TRIGGER_MICRO_BOS, micro, f"micro swing break at {break_price}", break_price),
        (TRIGGER_MOMENTUM_SHIFT, mom, "EMA fast/slow aligned with direction", 0.0),
        (TRIGGER_CANDLE_CLOSE, bool(is_closed), "evaluated candle is closed", 0.0),
    ):
        if ok:
            result.evidence.append(
                TriggerEvidence(
                    type=ttype,
                    direction="LONG" if is_long else "SHORT",
                    timeframe=timeframe,
                    detected_at_ts=ts,
                    trigger_price=price,
                    break_price=brk,
                    detail=str(detail),
                    source_id=f"{timeframe}:{ttype}",
                    derived_from="ohlc",
                )
            )
    if any(result.conditions_met.get(t) for t in _ALL_TRIGGERS if t != TRIGGER_ZONE_TOUCH):
        result.trigger_time_ts = ts
        result.trigger_price = price
    return result


# ----------------------------------------------------------------------
# Individual detectors (pure, documented, no future leakage)
# ----------------------------------------------------------------------


def _detect_rejection(
    is_long: bool,
    zone_top: float,
    zone_bottom: float,
    o: float,
    h: float,
    lo: float,
    c: float,
    min_wick_ratio: float,
) -> Optional[str]:
    """Wick penetrates the zone but the body closes back with it (§15).

    LONG: low dips into/below the zone, close finishes back above the low with
    a bullish body; wick_ratio = lower_wick / range must clear the threshold.
    A random single wick without body confirmation is NOT a trigger.
    """
    rng = h - lo
    if rng <= 0:
        return None
    body = c - o
    if is_long:
        if lo > zone_top or lo < zone_bottom - rng:
            return None  # no meaningful penetration
        lower_wick = min(o, c) - lo
        if body <= 0:
            return None  # need a bullish body, not just a wick
        if (lower_wick / rng) < min_wick_ratio:
            return None
        return f"LONG rejection: wick {lower_wick:.5f} ({lower_wick/rng:.0%}), body {body:.5f}"
    else:
        if h < zone_bottom or h > zone_top + rng:
            return None
        upper_wick = h - max(o, c)
        if body >= 0:
            return None
        if (upper_wick / rng) < min_wick_ratio:
            return None
        return f"SHORT rejection: wick {upper_wick:.5f} ({upper_wick/rng:.0%}), body {body:.5f}"


def _detect_displacement(
    is_long: bool,
    o: float,
    h: float,
    lo: float,
    c: float,
    atr: float,
    min_body_atr: float,
    min_range_atr: float,
) -> tuple[bool, str]:
    """Volatility-normalized expansion (§16): body/ATR + range/ATR, directional."""
    if atr <= 0:
        return False, "no ATR"
    body = abs(c - o)
    rng = h - lo
    directional = (c > o) if is_long else (c < o)
    if not directional:
        return False, "body not directional"
    if body < min_body_atr * atr:
        return False, f"body {body/atr:.2f} ATR < {min_body_atr}"
    if rng < min_range_atr * atr:
        return False, f"range {rng/atr:.2f} ATR < {min_range_atr}"
    return True, f"body {body/atr:.2f} ATR, range {rng/atr:.2f} ATR"


def _detect_micro_bos(
    is_long: bool, highs: list[float], lows: list[float], lookback: int
) -> tuple[bool, float]:
    """Local swing break on the trigger series (§17).

    LONG: the last close-equivalent high breaks the highest high of the prior
    ``lookback`` bars (excluding the break bar itself). Returns (hit, break_price).
    Only uses data at/before the evaluated bar — no lookahead.
    """
    lookback = max(2, int(lookback))
    if len(highs) < lookback + 1 or len(lows) < lookback + 1:
        return False, 0.0
    if is_long:
        prior = max(highs[-(lookback + 1) : -1])
        if highs[-1] > prior:
            return True, float(highs[-1])
    else:
        prior = min(lows[-(lookback + 1) : -1])
        if lows[-1] < prior:
            return True, float(lows[-1])
    return False, 0.0


def _detect_momentum_shift(is_long: bool, closes: list[float], fast: int, slow: int) -> bool:
    """EMA fast/slow alignment in the trigger direction (§18).

    Supporting evidence only: True when fast EMA is on the trigger side of
    slow EMA on the last closed bar. Needs slow+1 bars minimum.
    """
    fast, slow = max(2, int(fast)), max(3, int(slow))
    if fast >= slow or len(closes) < slow + 1:
        return False
    f = _ema(closes, fast)[-1]
    s = _ema(closes, slow)[-1]
    return bool(f > s) if is_long else bool(f < s)


def _ema(values: list[float], period: int) -> list[float]:
    k = 2.0 / (period + 1)
    out: list[float] = []
    ema = values[0]
    for v in values:
        ema = v * k + ema * (1 - k)
        out.append(ema)
    return out
