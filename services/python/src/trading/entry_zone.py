# -*- coding: utf-8 -*-
"""Entry zones — multi-timeframe OB/FVG entry planning (F2).

Implements the requested entry model:

* **Bias (M30 + H1)** — the big-picture direction. Entries only fire WITH the
  higher-timeframe bias.
* **Zone (M5)** — the minor Order Block / Fair Value Gap that price should
  retrace into for the entry.
* **Trigger (M1)** — price must actually be inside the zone (watch-and-fire).

The result is an :class:`EntryPlan` describing:
* ``direction`` — BUY / SELL (None when no valid setup),
* ``zone_top`` / ``zone_bottom`` — the OB/FVG band,
* ``entry`` — the zone price to enter at (edge toward the bias),
* ``stop_loss`` — just below/above the OB/FVG (a *valid* zone stop, not the
  widest swing),
* ``take_profit`` — derived from the operator's RR target,
* ``risk_distance`` / ``reward_distance`` — absolute price distances, so the
  fan-out can convert them per terminal.

Design rules: pure functions, no I/O, no MT5 — every read is injected via the
``bars`` args so it is trivially unit-testable. Never fabricates: a plan is
returned only when a direction, a valid zone and a sane risk distance all
exist. A ``max_risk_atr`` guard rejects stops that are too wide.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from trading.indicators import ema_series

__all__ = [
    "EntryPlan",
    "ZoneEntryGate",
    "find_order_blocks",
    "find_fair_value_gaps",
    "compute_bias",
    "build_entry_plan",
]

# Default reward/risk target for the take-profit (2R). The operator can lower
# or raise it; the ladder (TP1/TP2/TPmax) is built downstream by level_plan.
DEFAULT_RR = 2.0
# Reject stops wider than this many ATRs (protects against absurd zones).
DEFAULT_MAX_RISK_ATR = 2.5


@dataclass(frozen=True)
class EntryPlan:
    """A concrete OB/FVG entry plan (direction + zone + SL/TP)."""

    direction: str
    entry: float
    stop_loss: float
    take_profit: float
    zone_top: float
    zone_bottom: float
    risk_distance: float
    reward_distance: float
    rr: float
    source: str = "ob_fvg"
    bias: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "direction": self.direction,
            "entry": round(self.entry, 6),
            "stop_loss": round(self.stop_loss, 6),
            "take_profit": round(self.take_profit, 6),
            "zone_top": round(self.zone_top, 6),
            "zone_bottom": round(self.zone_bottom, 6),
            "risk_distance": round(self.risk_distance, 6),
            "reward_distance": round(self.reward_distance, 6),
            "rr": round(self.rr, 3),
            "source": self.source,
            "bias": dict(self.bias),
        }


def _closes(bars: Any) -> list[float]:
    return [
        _num(b.get("close") if isinstance(b, dict) else getattr(b, "close", None))
        for b in bars or []
    ]


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def compute_bias(
    htf_closes: list[float],
    *,
    fast: int = 20,
    slow: int = 50,
    min_strength: float = 0.0,
) -> dict[str, Any]:
    """Return ``{"direction": BULLISH|BEARISH|NEUTRAL, "strength": float}``.

    Bias from the (fast EMA − slow EMA) separation, normalised to ``[0,1]``.
    Too-few bars or a non-positive slow EMA → NEUTRAL (never fabricates).
    """
    closes = [c for c in (_num(x) for x in htf_closes or []) if c > 0]
    if len(closes) < max(fast, slow) + 1:
        return {"direction": "NEUTRAL", "strength": 0.0}
    fast_s = ema_series(closes, fast)
    slow_s = ema_series(closes, slow)
    f, s = fast_s[-1], slow_s[-1]
    if s <= 0:
        return {"direction": "NEUTRAL", "strength": 0.0}
    sep = (f - s) / s
    strength = min(abs(sep) / 0.02, 1.0)
    if strength <= min_strength:
        return {"direction": "NEUTRAL", "strength": round(strength, 4)}
    return {
        "direction": "BULLISH" if sep > 0 else "BEARISH",
        "strength": round(strength, 4),
    }


def find_order_blocks(
    highs: list[float], lows: list[float], lookback: int = 20
) -> list[dict[str, Any]]:
    """Return recent order-block bands: ``{type, top, bottom, mid}``.

    A bullish OB is the last down-candle before an up-move (approximated here by
    the highest high / lowest low of the recent pivot clusters). Kept simple and
    deterministic: we surface the recent swing-high band (bearish OB) and
    swing-low band (bullish OB).
    """
    obs: list[dict[str, Any]] = []
    if len(highs) < lookback or len(lows) < lookback:
        return obs
    recent_high = max(highs[-lookback:])
    recent_low = min(lows[-lookback:])
    # Bearish OB: a band just under the recent swing high (supply).
    if recent_high > 0:
        band = (recent_high - recent_low) * 0.1 or recent_high * 0.0005
        obs.append(
            {
                "type": "bearish",
                "top": recent_high,
                "bottom": recent_high - band,
                "mid": recent_high - band / 2.0,
            }
        )
    # Bullish OB: a band just above the recent swing low (demand).
    if recent_low > 0:
        band = (recent_high - recent_low) * 0.1 or recent_low * 0.0005
        obs.append(
            {
                "type": "bullish",
                "top": recent_low + band,
                "bottom": recent_low,
                "mid": recent_low + band / 2.0,
            }
        )
    return obs


def find_fair_value_gaps(
    highs: list[float], lows: list[float], lookback: int = 15
) -> list[dict[str, Any]]:
    """Return recent FVG bands: ``{type, top, bottom, mid}`` (3-candle imbalance)."""
    fvgs: list[dict[str, Any]] = []
    if len(highs) < 4 or len(lows) < 4:
        return fvgs
    start = max(1, len(highs) - lookback)
    for i in range(start, len(highs) - 1):
        # Bullish FVG: bar i-1 high < bar i+1 low.
        if lows[i + 1] > highs[i - 1]:
            fvgs.append(
                {
                    "type": "bullish",
                    "top": lows[i + 1],
                    "bottom": highs[i - 1],
                    "mid": (lows[i + 1] + highs[i - 1]) / 2.0,
                }
            )
        # Bearish FVG: bar i-1 low > bar i+1 high.
        elif highs[i + 1] < lows[i - 1]:
            fvgs.append(
                {
                    "type": "bearish",
                    "top": lows[i - 1],
                    "bottom": highs[i + 1],
                    "mid": (lows[i - 1] + highs[i + 1]) / 2.0,
                }
            )
    return fvgs[-5:]


def _pick_zone(zones: list[dict[str, Any]], want: str, price: float) -> Optional[dict[str, Any]]:
    """Pick the zone of the wanted side closest to (and on the correct side of) price."""
    candidates = [z for z in zones if z.get("type") == want]
    if not candidates:
        return None
    if want == "bullish":
        # Demand must sit BELOW the current price (price retraces down into it).
        below = [z for z in candidates if z["top"] <= price]
        pool = below or candidates
        return max(pool, key=lambda z: z["top"])
    # Bearish supply must sit ABOVE the current price (price retraces up into it).
    above = [z for z in candidates if z["bottom"] >= price]
    pool = above or candidates
    return min(pool, key=lambda z: z["bottom"])


def build_entry_plan(
    *,
    htf_closes: list[float],
    zone_highs: list[float],
    zone_lows: list[float],
    trigger_price: float,
    atr: float = 0.0,
    rr: float = DEFAULT_RR,
    max_risk_atr: float = DEFAULT_MAX_RISK_ATR,
    min_bias_strength: float = 0.0,
    require_inside_zone: bool = True,
) -> Optional[EntryPlan]:
    """Build an OB/FVG entry plan from MTF inputs (F2).

    Args:
        htf_closes: closes for the bias timeframe(s) (M30/H1).
        zone_highs/low: bars for the zone timeframe (M5).
        trigger_price: the live price (M1) checked against the zone.
        atr: ATR for the risk-width guard.
        rr: reward/risk target for the take-profit.
        max_risk_atr: reject stops wider than this many ATRs.
        min_bias_strength: minimum bias strength to allow an entry.
        require_inside_zone: when True (watch-and-fire), the trigger price must
            be inside the zone; when False the plan is returned regardless (so
            the caller can store it as a PENDING signal and wait).

    Returns:
        :class:`EntryPlan` or ``None`` when no valid setup exists.
    """
    price = _num(trigger_price)
    if price <= 0:
        return None
    bias = compute_bias(htf_closes, min_strength=min_bias_strength)
    direction = bias["direction"]
    if direction == "NEUTRAL":
        return None

    want = "bullish" if direction == "BULLISH" else "bearish"
    zones = find_fair_value_gaps(zone_highs, zone_lows) + find_order_blocks(zone_highs, zone_lows)
    zone = _pick_zone(zones, want, price)
    if zone is None:
        return None

    top = _num(zone.get("top"))
    bottom = _num(zone.get("bottom"))
    if top <= 0 or bottom <= 0 or top <= bottom:
        return None

    # Entry at the near edge of the zone (closest edge to the current price).
    if direction == "BULLISH":
        entry = top if price > top else (bottom if price < bottom else price)
        stop_loss = bottom
    else:
        entry = bottom if price < bottom else (top if price > top else price)
        stop_loss = top

    risk = abs(entry - stop_loss)
    if risk <= 0:
        return None
    # Reject absurdly wide stops (e.g. zone spans the whole range).
    if atr > 0 and max_risk_atr > 0 and risk > max_risk_atr * atr:
        return None

    sign = 1.0 if direction == "BULLISH" else -1.0
    take_profit = entry + sign * rr * risk

    inside = bottom <= price <= top
    if require_inside_zone and not inside:
        # Not yet at the zone → no immediate entry (caller stores PENDING).
        return None

    return EntryPlan(
        direction="BUY" if direction == "BULLISH" else "SELL",
        entry=round(entry, 6),
        stop_loss=round(stop_loss, 6),
        take_profit=round(take_profit, 6),
        zone_top=round(top, 6),
        zone_bottom=round(bottom, 6),
        risk_distance=round(risk, 6),
        reward_distance=round(abs(take_profit - entry), 6),
        rr=rr,
        bias=bias,
    )


class ZoneEntryGate:
    """Watch-and-fire gate: hold a signal until price reaches the OB/FVG zone.

    One gate per pipeline. When a committee signal exists but price is not yet
    inside a valid zone, the gate REMEMBERS it (pending) instead of executing.
    On a later cycle, when price enters the zone (or a fresh plan is buildable
    at the current price), the gate returns the plan so the caller can execute.

    Fail-safe and stateless-per-call: every method swallows errors and returns a
    safe verdict (``None`` = nothing to do). It never places orders itself.
    """

    def __init__(self, max_pending: int = 200) -> None:
        # symbol -> pending dict {direction, zone_top, zone_bottom, rr, atr, ts}
        self._pending: dict[str, dict[str, Any]] = {}
        self._max_pending = max(1, int(max_pending))

    def pending_for(self, symbol: str) -> Optional[dict[str, Any]]:
        return self._pending.get(symbol)

    def pending_count(self) -> int:
        return len(self._pending)

    def clear(self, symbol: str) -> None:
        self._pending.pop(symbol, None)

    def clear_all(self) -> None:
        self._pending.clear()

    def evaluate(
        self,
        *,
        symbol: str,
        htf_closes: list[float],
        zone_highs: list[float],
        zone_lows: list[float],
        trigger_price: float,
        atr: float = 0.0,
        rr: float = DEFAULT_RR,
    ) -> Optional[EntryPlan]:
        """Return a plan to execute NOW, or ``None`` while waiting at the zone.

        Logic:
        * Build the full (inside-zone) plan at the current price. If it succeeds,
          a pending entry for this symbol is cleared and the plan returned.
        * Otherwise build a plan WITHOUT requiring the price to be inside the
          zone; if that yields a valid setup, record it as PENDING (so the
          operator/agent knows we are waiting) and return ``None``.
        * If neither is possible, drop any stale pending entry and return None.
        """
        try:
            live = build_entry_plan(
                htf_closes=htf_closes,
                zone_highs=zone_highs,
                zone_lows=zone_lows,
                trigger_price=trigger_price,
                atr=atr,
                rr=rr,
                require_inside_zone=True,
            )
            if live is not None:
                self._pending.pop(symbol, None)
                return live

            waiting = build_entry_plan(
                htf_closes=htf_closes,
                zone_highs=zone_highs,
                zone_lows=zone_lows,
                trigger_price=trigger_price,
                atr=atr,
                rr=rr,
                require_inside_zone=False,
            )
            if waiting is not None:
                if symbol not in self._pending and len(self._pending) >= self._max_pending:
                    # Bounded: drop oldest insertion to stay within capacity.
                    try:
                        oldest = next(iter(self._pending))
                        self._pending.pop(oldest, None)
                    except StopIteration:
                        pass
                self._pending[symbol] = {
                    "direction": waiting.direction,
                    "zone_top": waiting.zone_top,
                    "zone_bottom": waiting.zone_bottom,
                    "rr": rr,
                    "atr": atr,
                    "ts": _now_ts(),
                }
            else:
                # No valid setup at all → do not keep a stale pending entry.
                self._pending.pop(symbol, None)
            return None
        except Exception:  # noqa: BLE001 - the gate must never break a cycle
            return None


def _now_ts() -> float:
    import time

    return time.time()
