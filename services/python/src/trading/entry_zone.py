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

from trading.entry_config import ZoneConfig
from trading.entry_detectors import detect_fvgs, detect_order_blocks
from trading.indicators import ema_series

__all__ = [
    "EntryPlan",
    "ZoneEntryGate",
    "find_order_blocks",
    "find_fair_value_gaps",
    "detect_entry_zones",
    "compute_bias",
    "build_entry_plan",
    "pick_zone",
    "zone_distance",
]

# Default reward/risk target for the take-profit (2R). The operator can lower
# or raise it; the ladder (TP1/TP2/TPmax) is built downstream by level_plan.
DEFAULT_RR = 2.0
# Reject stops wider than this many ATRs (protects against absurd zones).
DEFAULT_MAX_RISK_ATR = 2.5
# Treat price within this many ATRs of a zone band as "at the zone" (avoids the
# too-strict exact-band requirement that produced no entries).
DEFAULT_ZONE_TOLERANCE_ATR = 0.25
# Reject a zone farther than this many ATRs from price (unreachable in practice).
DEFAULT_ZONE_PROXIMITY_ATR = 4.0
# Practical firing distance: price within this many ATRs of the band fires the
# entry (a normal retracement), so signals actually execute in a trend.
DEFAULT_ENTRY_TRIGGER_ATR = 2.0


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
    highs: list[float],
    lows: list[float],
    opens: list[float] | None = None,
    lookback: int = 20,
) -> list[dict[str, Any]]:
    """Return recent order-block bands: ``{type, top, bottom, mid}``.

    When candle **opens** are provided we use the classic SMC definition: the
    last opposite-colour candle before the impulse (a down-candle below price ⇒
    bullish OB / demand; an up-candle above price ⇒ bearish OB / supply). The
    band is that candle's high/low — anchored near price, so an entry is
    achievable in a trend.

    Without opens we fall back to the recent swing-low / swing-high bands (the
    older behaviour), kept tight so the derived stop is not absurdly wide.
    """
    obs: list[dict[str, Any]] = []
    n = len(highs)
    if n < max(5, lookback // 2) or len(lows) < max(5, lookback // 2):
        return obs

    window = min(lookback, n)
    recent_high = max(highs[-window:])
    recent_low = min(lows[-window:])
    rng = (recent_high - recent_low) or (recent_low * 0.001 if recent_low else 1.0)
    band = max(rng * 0.1, 1e-9)

    opens = opens or []
    used_body = False
    if len(opens) == n:
        price = highs[-1]
        bullish_band = None
        bearish_band = None
        for i in range(n - 2, max(-1, n - window - 1), -1):
            o = _num(opens[i])
            h = _num(highs[i])
            low = _num(lows[i])
            # Approximate this candle's close with the NEXT candle's open.
            close = _num(opens[i + 1]) if i + 1 < n else o
            if o > close and h <= price and bullish_band is None:
                bullish_band = (low, h)  # down-candle = demand
            if o < close and low >= price and bearish_band is None:
                bearish_band = (low, h)  # up-candle = supply
            if bullish_band and bearish_band:
                break
        if bullish_band:
            lo, hi = bullish_band
            obs.append({"type": "bullish", "top": hi, "bottom": lo, "mid": (hi + lo) / 2.0})
            used_body = True
        if bearish_band:
            lo, hi = bearish_band
            obs.append({"type": "bearish", "top": hi, "bottom": lo, "mid": (hi + lo) / 2.0})
            used_body = True

    if not used_body:
        if recent_high > 0:
            obs.append(
                {
                    "type": "bearish",
                    "top": recent_high,
                    "bottom": recent_high - band,
                    "mid": recent_high - band / 2.0,
                }
            )
        if recent_low > 0:
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


def detect_entry_zones(
    *,
    symbol: str,
    timeframe: str,
    opens: list[float],
    highs: list[float],
    lows: list[float],
    closes: list[float],
    atr: float,
    config: ZoneConfig | None = None,
    exclude_forming_bar: bool = True,
) -> list[dict[str, Any]]:
    """Return quality-gated, unconsumed zones from closed OHLC bars.

    OB and FVG detection is shared by the live entry gate and chart endpoint.
    The newest candle is excluded by default because MT5 includes the forming
    bar in its OHLC response; later closed candles still determine whether a
    zone has already been invalidated or fully filled.
    """
    size = min(len(opens), len(highs), len(lows), len(closes))
    if exclude_forming_bar:
        size -= 1
    if size < 3 or atr <= 0:
        return []

    o = [float(value) for value in opens[:size]]
    h = [float(value) for value in highs[:size]]
    lo = [float(value) for value in lows[:size]]
    c = [float(value) for value in closes[:size]]
    cfg = config or ZoneConfig()
    zones = detect_order_blocks(
        symbol=symbol,
        timeframe=timeframe,
        opens=o,
        highs=h,
        lows=lo,
        closes=c,
        atr=atr,
        config=cfg,
    ) + detect_fvgs(
        symbol=symbol,
        timeframe=timeframe,
        highs=h,
        lows=lo,
        atr=atr,
        config=cfg,
    )

    result: list[dict[str, Any]] = []
    for zone in zones:
        follow_index = int(zone.metadata.get("follow_index", zone.origin_index + 1))
        later = range(follow_index + 1, size)
        touch_count = 0
        was_touched = False
        if zone.zone_type == "ORDER_BLOCK":
            for index in later:
                touched = lo[index] <= zone.top and h[index] >= zone.bottom
                if touched and not was_touched:
                    touch_count += 1
                was_touched = touched
            if touch_count > cfg.max_retests:
                continue
        if zone.zone_type == "FVG":
            fully_filled = any(
                lo[index] <= zone.bottom if zone.direction == "LONG" else h[index] >= zone.top
                for index in later
            )
            if fully_filled:
                continue
        elif any(
            (
                c[index] < zone.invalidation_price
                if zone.direction == "LONG"
                else c[index] > zone.invalidation_price
            )
            for index in later
        ):
            continue

        item = zone.to_dict()
        item["type"] = "bullish" if zone.direction == "LONG" else "bearish"
        item["mitigation"] = "FRESH"
        item["touch_count"] = touch_count
        if zone.zone_type == "FVG":
            item["mitigation"] = (
                "PARTIALLY_MITIGATED"
                if any(
                    lo[index] < zone.top if zone.direction == "LONG" else h[index] > zone.bottom
                    for index in later
                )
                else "FRESH"
            )
        elif touch_count:
            item["mitigation"] = "TOUCHED"
        result.append(item)
    return result


def _zone_distance(zone: dict[str, Any], price: float) -> float:
    """Distance from ``price`` to the zone band (0 when inside the band)."""
    top = _num(zone.get("top"))
    bottom = _num(zone.get("bottom"))
    if bottom <= price <= top:
        return 0.0
    if price > top:
        return price - top
    return bottom - price


def _pick_zone(zones: list[dict[str, Any]], want: str, price: float) -> Optional[dict[str, Any]]:
    """Pick the wanted-side zone CLOSEST to price.

    Previously a bullish demand zone had to sit strictly BELOW price, so in an
    uptrend (price above every demand zone) no zone was ever accepted and no
    entry fired. Now we pick the nearest wanted-side zone regardless of side and
    let the caller's proximity/tolerance guards decide — this is far less
    restrictive while still directional.
    """
    candidates = [z for z in zones if z.get("type") == want]
    if not candidates:
        return None
    return min(candidates, key=lambda z: _zone_distance(z, price))


# Public aliases (used by the pipeline's diagnostics).
pick_zone = _pick_zone
zone_distance = _zone_distance


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
    zone_opens: list[float] | None = None,
    zone_closes: list[float] | None = None,
    zone_timeframe: str = "M5",
    zone_config: ZoneConfig | None = None,
    zone_tolerance_atr: float = DEFAULT_ZONE_TOLERANCE_ATR,
    zone_proximity_atr: float = DEFAULT_ZONE_PROXIMITY_ATR,
    entry_trigger_atr: float = DEFAULT_ENTRY_TRIGGER_ATR,
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
            be inside the zone OR within ``zone_tolerance_atr`` of it; when
            False the plan is returned regardless (caller stores it as PENDING).
        zone_opens: candle opens for the zone timeframe (sharper OB detection).
        zone_tolerance_atr: treat price within this many ATRs of the band as
            "at the zone" (prevents the too-strict exact-band requirement).
        zone_proximity_atr: reject a zone farther than this many ATRs from price
            (avoids waiting for an unreachable zone; 0 disables the guard).
        entry_trigger_atr: price within this many ATRs of the zone band counts
            as "at the zone" — the practical firing distance (larger = more
            permissive; the entry still fills at the band edge).

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
    if zone_closes is not None:
        zones = detect_entry_zones(
            symbol="",
            timeframe=zone_timeframe,
            opens=zone_opens or [],
            highs=zone_highs,
            lows=zone_lows,
            closes=zone_closes,
            atr=atr,
            config=zone_config,
        )
    else:
        zones = find_fair_value_gaps(zone_highs, zone_lows) + find_order_blocks(
            zone_highs, zone_lows, zone_opens
        )
    zone = _pick_zone(zones, want, price)
    if zone is None:
        return None

    top = _num(zone.get("top"))
    bottom = _num(zone.get("bottom"))
    if top <= 0 or bottom <= 0 or top <= bottom:
        return None

    # Proximity guard: skip zones too far from price (unreachable in practice).
    distance = _zone_distance(zone, price)
    if atr > 0 and zone_proximity_atr > 0:
        if distance > zone_proximity_atr * atr:
            return None

    # Watch-and-fire uses a MARKET order, so the entry is the CURRENT price
    # (not the zone edge — that would be a limit order). The zone anchors the
    # STOP: SL just beyond the far edge of the demand/supply band.
    entry = price
    if direction == "BULLISH":
        stop_loss = bottom
    else:
        stop_loss = top

    risk = abs(entry - stop_loss)
    if risk <= 0:
        return None
    # Reject absurdly wide stops (e.g. zone spans the whole range, or the price
    # is too far past the zone so the SL would be huge).
    if atr > 0 and max_risk_atr > 0 and risk > max_risk_atr * atr:
        return None

    sign = 1.0 if direction == "BULLISH" else -1.0
    take_profit = entry + sign * rr * risk

    # "At the zone" = inside the band OR within the tolerance buffer around it.
    # ``entry_trigger_atr`` is the practical firing distance: price within that
    # many ATRs of the band counts as "at the zone" (default 2.0 ATR is a normal
    # retracement, so entries actually fire in a trend instead of only when the
    # price sits exactly inside a narrow band).
    tol = max(zone_tolerance_atr * atr, 0.0) if atr > 0 else max(abs(top - bottom), 0.0)
    trigger_window = max(tol, entry_trigger_atr * atr) if atr > 0 else tol
    inside = (bottom - tol) <= price <= (top + tol)
    if require_inside_zone and not inside and distance > trigger_window:
        # Not yet close enough → no immediate entry (caller stores PENDING).
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
        zone_opens: list[float] | None = None,
        zone_closes: list[float] | None = None,
        zone_timeframe: str = "M5",
        zone_config: ZoneConfig | None = None,
        zone_tolerance_atr: float = DEFAULT_ZONE_TOLERANCE_ATR,
        zone_proximity_atr: float = DEFAULT_ZONE_PROXIMITY_ATR,
        entry_trigger_atr: float = DEFAULT_ENTRY_TRIGGER_ATR,
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
                zone_opens=zone_opens,
                zone_closes=zone_closes,
                zone_timeframe=zone_timeframe,
                zone_config=zone_config,
                zone_tolerance_atr=zone_tolerance_atr,
                zone_proximity_atr=zone_proximity_atr,
                entry_trigger_atr=entry_trigger_atr,
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
                zone_opens=zone_opens,
                zone_closes=zone_closes,
                zone_timeframe=zone_timeframe,
                zone_config=zone_config,
                zone_tolerance_atr=zone_tolerance_atr,
                zone_proximity_atr=zone_proximity_atr,
                entry_trigger_atr=entry_trigger_atr,
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
