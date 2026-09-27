# -*- coding: utf-8 -*-
"""Deterministic SL/TP management decisions (BEP, trailing, progressive).

This module holds the **pure decision logic** for managing an open position's
stop-loss after entry. It performs no I/O: given a position snapshot, an ATR
value, and a config, it returns the *desired* new stop-loss (or ``None`` when no
change is warranted). The caller (:mod:`monitoring.trade_manager`) is
responsible for transmitting any change to the broker.

Three mechanisms, applied in priority order (each computed independently so the
safest/most-advanced rule wins):

1. **Break-even (BEP)** — once the position is in profit by ``bep_trigger_r``
   (expressed in R multiples, R = initial risk distance), move the stop to the
   entry price (optionally locking ``bep_lock_r`` R of profit).

2. **Progressive / TP1 lock** — once price reaches TP1 (1R by the project's
   ladder), move the stop up to lock in a fraction of the move (default: to
   break-even + ``tp1_lock_r`` R). This is the "+ move SL" behaviour.

3. **Trailing** — once the position is in profit, trail the stop by
   ``trail_atr_factor × ATR`` behind the current price. The trail only ever
   moves the stop in the *favourable* direction (never widens risk).

All rules are monotonic: the resulting stop is never worse (for the trader)
than the current stop. Any error yields ``None`` (no change) — fail-safe.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)

__all__ = ["SLTPConfig", "SLTPDecision", "decide_stop_loss"]


@dataclass(frozen=True)
class SLTPConfig:
    """Configuration for dynamic stop management.

    All distances are expressed as R multiples (R = initial risk distance =
    |entry - initial_stop|) so the logic is instrument-agnostic, except the
    trailing distance which is ATR-based.
    """

    enabled: bool = True
    breakeven_enabled: bool = True
    # Move to break-even once the position is up by this many R.
    bep_trigger_r: float = 1.0
    # Extra R locked beyond entry when moving to break-even (0 = pure entry).
    bep_lock_r: float = 0.0
    # Progressive step: once price reaches TP1 (1R by the ladder), lock this R.
    progressive_enabled: bool = True
    tp1_trigger_r: float = 1.0
    tp1_lock_r: float = 0.5
    # Trailing (ATR-based).
    trailing_enabled: bool = True
    trail_atr_factor: float = 1.5
    # Reject any change smaller than this many R (avoids churn/over-modification).
    min_move_r: float = 0.05


@dataclass(frozen=True)
class SLTPDecision:
    """A single desired stop-loss change."""

    new_sl: float
    reason: str
    locked_r: float


def _f(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _better_stop(direction: str, candidate: float, current: float) -> bool:
    """True when ``candidate`` is a tighter (more favourable) stop than ``current``.

    For a BUY the favourable direction is upward; for a SELL it is downward.
    A non-positive ``current`` (no stop) is always replaced.
    """
    if current <= 0:
        return True
    if direction == "buy":
        return candidate > current
    return candidate < current


def decide_stop_loss(
    *,
    direction: str,
    entry_price: float,
    current_sl: float,
    current_price: float,
    atr: float,
    initial_risk: Optional[float] = None,
    config: Optional[SLTPConfig] = None,
) -> Optional[SLTPDecision]:
    """Compute the desired new stop-loss for an open position (or ``None``).

    Args:
        direction: ``"buy"`` or ``"sell"`` (case-insensitive).
        entry_price: The position's entry price.
        current_sl: The currently-set stop-loss (0/negative when unset).
        current_price: The current market price for the position's side
            (bid for a long that would be closed by selling, ask for a short).
        atr: ATR value for the instrument/timeframe.
        initial_risk: Initial risk distance (|entry - initial SL|). When not
            given it defaults to ``atr`` (so 1R == 1 ATR) — callers should pass
            the real initial distance when known.
        config: :class:`SLTPConfig` (defaults applied when omitted).

    Returns:
        An :class:`SLTPDecision` when a tighter stop is warranted, else ``None``.
    """
    cfg = config or SLTPConfig()
    if not cfg.enabled:
        return None

    direction = str(direction or "").lower()
    if direction not in ("buy", "sell"):
        return None

    entry = _f(entry_price)
    cur_sl = _f(current_sl)
    price = _f(current_price)
    atr = _f(atr)
    if entry <= 0 or price <= 0:
        return None

    risk = _f(initial_risk)
    if risk <= 0:
        # Fall back to the ATR (documented 1R == 1 ATR when unknown).
        risk = atr if atr > 0 else (abs(entry - cur_sl) if cur_sl > 0 else 0.0)
    if risk <= 0:
        return None

    # Signed progress in R (positive = in profit).
    if direction == "buy":
        progress_r = (price - entry) / risk
    else:
        progress_r = (entry - price) / risk

    candidates: list[SLTPDecision] = []

    # 1. Break-even / BEP+lock
    if cfg.breakeven_enabled and progress_r >= cfg.bep_trigger_r:
        if direction == "buy":
            sl = entry + cfg.bep_lock_r * risk
        else:
            sl = entry - cfg.bep_lock_r * risk
        candidates.append(SLTPDecision(new_sl=sl, reason="breakeven", locked_r=cfg.bep_lock_r))

    # 2. Progressive TP1 lock
    if cfg.progressive_enabled and progress_r >= cfg.tp1_trigger_r:
        if direction == "buy":
            sl = entry + cfg.tp1_lock_r * risk
        else:
            sl = entry - cfg.tp1_lock_r * risk
        candidates.append(SLTPDecision(new_sl=sl, reason="tp1_lock", locked_r=cfg.tp1_lock_r))

    # 3. Trailing (ATR-based, once in profit and ATR known)
    if cfg.trailing_enabled and atr > 0 and progress_r > 0:
        trail_distance = atr * cfg.trail_atr_factor
        if direction == "buy":
            sl = price - trail_distance
        else:
            sl = price + trail_distance
        trail_r = (sl - entry) / risk if direction == "buy" else (entry - sl) / risk
        candidates.append(SLTPDecision(new_sl=sl, reason="trailing", locked_r=round(trail_r, 4)))

    if not candidates:
        return None

    # Pick the most favourable candidate (highest locked_r for buy means the
    # tightest protective stop; we compare by "locked R" which is monotonic in
    # favourability for both directions).
    best = max(candidates, key=lambda c: c.locked_r)

    # Only act if it actually tightens the stop by at least min_move_r.
    if not _better_stop(direction, best.new_sl, cur_sl):
        return None
    if cur_sl > 0 and abs(best.new_sl - cur_sl) / risk < cfg.min_move_r:
        return None

    return SLTPDecision(
        new_sl=round(best.new_sl, 5),
        reason=best.reason,
        locked_r=best.locked_r,
    )
