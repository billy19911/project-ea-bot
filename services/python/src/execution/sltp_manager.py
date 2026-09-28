# -*- coding: utf-8 -*-
"""Deterministic SL/TP management decisions — level-based ladder.

This module holds the **pure decision logic** for managing an open position's
stop-loss after entry. It performs no I/O: given a position snapshot, an ATR
value, and a config, it returns the *desired* new stop-loss (or ``None`` when no
change is warranted). The caller (:mod:`monitoring.trade_manager`) is
responsible for transmitting any change to the broker.

The stop moves along a **level ladder** (the project's reporting ladder:
TP1 = 1R, TP2 = 2R, TPmax = 3R of the initial risk R = |entry - initial SL|):

1. **Entry →** stop stays at its initial place; **no trailing before TP1**.
2. **Price reaches TP1 (1R)** → move the stop to **break-even + buffer**
   (``bep_buffer_r`` R above entry). The trade can no longer lose.
3. **Price reaches TP2 (2R)** → move the stop up to **TP1 (1R)** — locking 1R.
4. **Price beyond TP2** → **trail** the stop ``trail_atr_factor × ATR`` behind
   the price (runner management) until TPmax closes the trade — but never
   below the TP1 level already secured.

All rules are monotonic: the resulting stop is never worse (for the trader)
than the current stop. Any error yields ``None`` (no change) — fail-safe.

Design note (2026 rewrite): the previous implementation trailed from the FIRST
sign of profit (``progress_r > 0``), which made the SL "move before it should".
Trailing now only starts AFTER TP2 is reached.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)

__all__ = ["SLTPConfig", "SLTPDecision", "decide_stop_loss"]

# Ladder reward multiples (in R) — must match ``trading.level_plan``.
TP1_R = 1.0
TP2_R = 2.0
TPMAX_R = 3.0


@dataclass(frozen=True)
class SLTPConfig:
    """Configuration for the level-based stop ladder.

    Distances are expressed as R multiples (R = |entry - initial_stop|) so the
    logic is instrument-agnostic; only the post-TP2 trailing distance is ATR
    based.
    """

    enabled: bool = True
    # Move the stop to break-even (+buffer) once price reaches TP1.
    breakeven_enabled: bool = True
    # Buffer locked ABOVE entry at BEP, in R (e.g. 0.1 = 10% of risk). Keeps the
    # trade non-losing even after spread/slippage.
    bep_buffer_r: float = 0.1
    # When price reaches TP2, move the stop up to the TP1 level (locks 1R).
    tp1_lock_enabled: bool = True
    tp1_trigger_r: float = TP1_R
    tp1_lock_r: float = TP1_R
    # Trailing (ATR-based) — ONLY after price passes TP2 (runner mode).
    trailing_enabled: bool = True
    tp2_trigger_r: float = TP2_R
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

    # Level-based ladder. Pick the HIGHEST level already reached; only the one
    # stop for that level is proposed (no raw "trail from the first profit").
    candidates: list[SLTPDecision] = []

    def _lock(lock_r: float) -> float:
        """Price at ``lock_r`` R in the favourable direction."""
        if direction == "buy":
            return entry + lock_r * risk
        return entry - lock_r * risk

    # Rung 2 — TP2 reached: lock the TP1 level (1R).
    if cfg.tp1_lock_enabled and progress_r >= cfg.tp2_trigger_r:
        candidates.append(
            SLTPDecision(new_sl=_lock(cfg.tp1_lock_r), reason="tp2_lock", locked_r=cfg.tp1_lock_r)
        )
        # Rung 3 — beyond TP2: trail the runner by ATR, but never below TP1.
        if cfg.trailing_enabled and atr > 0:
            trail_distance = atr * cfg.trail_atr_factor
            if direction == "buy":
                sl = max(price - trail_distance, _lock(cfg.tp1_lock_r))
            else:
                sl = min(price + trail_distance, _lock(cfg.tp1_lock_r))
            trail_r = (sl - entry) / risk if direction == "buy" else (entry - sl) / risk
            candidates.append(
                SLTPDecision(new_sl=sl, reason="trailing", locked_r=round(trail_r, 4))
            )
    # Rung 1 — TP1 reached (but not yet TP2): move stop to BEP + buffer.
    elif cfg.breakeven_enabled and progress_r >= cfg.tp1_trigger_r:
        candidates.append(
            SLTPDecision(
                new_sl=_lock(cfg.bep_buffer_r),
                reason="breakeven",
                locked_r=cfg.bep_buffer_r,
            )
        )

    if not candidates:
        return None

    # Pick the most favourable candidate (highest locked R = tightest stop).
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
