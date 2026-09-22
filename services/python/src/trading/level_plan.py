# -*- coding: utf-8 -*-
"""Level plan — Entry / SL / TP1 / TP2 / TPmax the way this project sizes risk.

The project's money management (``risk.money_management.MoneyManager``) derives
the stop from ATR: ``SL = 1.5 x ATR`` and ``TP = 3.0 x ATR`` (a 2R target).
This module turns that single-risk model into the reporting ladder requested
for the signal reports:

* ``tp1``   — 1R (first partial target),
* ``tp2``   — 2R (equals the project's production TP when SL = 1.5 x ATR),
* ``tpmax`` — 3R (runner target).

Design rules:

* Pure functions — no I/O, no MT5, no Telegram. Deterministic and unit-testable.
* Never fabricates: a plan is produced only when a direction, a positive entry
  and a positive risk distance are all available.
* The ladder is always derived from the *actual* SL distance
  (``abs(entry - sl)``), so it stays consistent with whatever SL/TP the order
  really carries; the ATR model is only used for *indicative* ladders when no
  order/proposal exists yet.
"""

from __future__ import annotations

from typing import Any, Optional

__all__ = [
    "build_level_plan",
    "direction_from_text",
    "extract_price_atr",
    "indicative_levels",
]

# Reward multiples (in R = the stop distance) for the reporting ladder.
TP1_R = 1.0
TP2_R = 2.0
TPMAX_R = 3.0
# ATR model used for indicative ladders — matches MoneyManager.calculate_sl_tp
# defaults (sl_multiplier=1.5, tp_multiplier=3.0 => TP2 is the production TP).
SL_ATR_MULT = 1.5
TP_ATR_MULT = 3.0


def _num(value: Any) -> float:
    """Coerce a value to float, degrading to 0.0 (never raises)."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def direction_from_text(*texts: Any) -> str:
    """Map the first BULLISH/BEARISH hint in ``texts`` to BUY/SELL (else "")."""
    for text in texts:
        upper = str(text or "").upper()
        if "BULLISH" in upper:
            return "BUY"
        if "BEARISH" in upper:
            return "SELL"
    return ""


def _ladder(direction: str, entry: float, risk: float) -> dict[str, Any]:
    """Build the shared ladder shape from a positive risk distance."""
    sign = 1.0 if direction == "BUY" else -1.0
    return {
        "direction": direction,
        "entry": round(entry, 5),
        "sl": round(entry - sign * risk, 5),
        "tp1": round(entry + sign * TP1_R * risk, 5),
        "tp2": round(entry + sign * TP2_R * risk, 5),
        "tpmax": round(entry + sign * TPMAX_R * risk, 5),
        "risk_distance": round(risk, 5),
        "rr": {"tp1": TP1_R, "tp2": TP2_R, "tpmax": TPMAX_R},
    }


def build_level_plan(
    direction: str,
    entry: float,
    stop_loss: float,
    *,
    take_profit: float = 0.0,
    atr: float = 0.0,
) -> Optional[dict[str, Any]]:
    """Build the Entry/SL/TP1/TP2/TPmax ladder from the real SL distance.

    Used once a proposal/order carries a stop: the ladder stays consistent
    with that stop (1R / 2R / 3R of the actual risk). Returns ``None`` when
    direction/entry/stop are unusable — never fabricates a level.
    """
    side = str(direction or "").upper()
    if side not in ("BUY", "SELL"):
        return None
    entry_v = _num(entry)
    sl_v = _num(stop_loss)
    if entry_v <= 0 or sl_v <= 0:
        return None
    risk = abs(entry_v - sl_v)
    if risk <= 0:
        return None
    levels = _ladder(side, entry_v, risk)
    levels["sl"] = round(sl_v, 5)  # keep the exact stop that was given
    tp_v = _num(take_profit)
    if tp_v > 0:
        levels["tp"] = round(tp_v, 5)
    atr_v = _num(atr)
    if atr_v > 0:
        levels["atr"] = round(atr_v, 5)
    levels["source"] = "order"
    return levels


def indicative_levels(direction: str, price: float, atr: float) -> Optional[dict[str, Any]]:
    """Build an *indicative* ladder (no order yet) from the project's ATR model.

    SL = 1.5 x ATR and TP2 = 3.0 x ATR (= 2R), so TP1 = 1R and TPmax = 3R.
    Returns ``None`` when direction/price/ATR are unusable.
    """
    side = str(direction or "").upper()
    if side not in ("BUY", "SELL"):
        return None
    price_v = _num(price)
    atr_v = _num(atr)
    if price_v <= 0 or atr_v <= 0:
        return None
    risk = SL_ATR_MULT * atr_v
    levels = _ladder(side, price_v, risk)
    levels["atr"] = round(atr_v, 5)
    levels["source"] = "analysis"
    return levels


def _state_value(state: Any, key: str) -> float:
    """Read ``key`` from a market_state dict or object (0.0 when absent)."""
    if isinstance(state, dict):
        return _num(state.get(key))
    return _num(getattr(state, key, 0.0))


def extract_price_atr(context: Any) -> tuple[float, float]:
    """Best-effort ``(price, atr)`` from a pipeline context/snapshot.

    Understands the shapes the feed loop and callers actually produce:
    ``price``/``close``, ``volatility`` (atr/price), a ``market_state`` dict or
    object (``close``/``atr``), the ``prices`` series tail and ``market_info``
    quotes. Missing evidence degrades to ``0.0`` — the caller then simply has
    no indicative ladder.
    """
    ctx = context if isinstance(context, dict) else {}
    state = ctx.get("market_state")
    vol = ctx.get("volatility")
    vol = vol if isinstance(vol, dict) else {}
    market_info = ctx.get("market_info")
    market_info = market_info if isinstance(market_info, dict) else {}

    prices = ctx.get("prices")
    last_price: Any = None
    if isinstance(prices, (list, tuple)) and prices:
        last_price = prices[-1]

    price = 0.0
    for candidate in (
        ctx.get("price"),
        ctx.get("close"),
        _state_value(state, "close"),
        vol.get("price"),
        last_price,
        market_info.get("ask"),
        market_info.get("bid"),
        market_info.get("price"),
    ):
        price = _num(candidate)
        if price > 0:
            break

    atr = 0.0
    for candidate in (ctx.get("atr"), vol.get("atr"), _state_value(state, "atr")):
        atr = _num(candidate)
        if atr > 0:
            break
    return price, atr
