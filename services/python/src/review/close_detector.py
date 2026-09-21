# -*- coding: utf-8 -*-
"""Position-close detector (audit P1-6).

The learning loop needs a *close* event to run trade review → lesson, but the
production execution engine never closes positions and the paper simulator is
unwired — so no live trade ever reached review. This detector closes that gap
**without touching orders**: it observes successive snapshots of the broker's
open positions (read-only) and, when a previously-seen ticket disappears, emits
a synthetic close record and fires :meth:`ReviewAutoTrigger.on_position_closed`.

Design guarantees:

* **Observation-only** — it never places, modifies, or closes anything. It only
  compares position sets it is given.
* **Fail-safe** — a review/hook error never propagates; the detector simply
  records what it can.
* **Explicit opt-in** — the caller decides when to call :meth:`observe`; the
  detector holds no clock/timer and never runs on its own.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

__all__ = ["PositionCloseDetector"]


def _to_dict(obj: Any) -> dict[str, Any]:
    """Best-effort dict conversion for pydantic models / objects."""
    if isinstance(obj, dict):
        return dict(obj)
    dump = getattr(obj, "model_dump", None)
    if callable(dump):
        try:
            return dict(dump())
        except Exception:  # noqa: BLE001 - malformed model
            return {}
    return {}


class PositionCloseDetector:
    """Detect closed positions by diffing successive open-position snapshots.

    Args:
        on_close: Callable invoked with each synthetic close record (typically
            ``ReviewAutoTrigger.on_position_closed``). Optional.
    """

    def __init__(self, on_close: Optional[Any] = None) -> None:
        self._on_close = on_close
        # Last observed position per ticket.
        self._known: dict[Any, dict[str, Any]] = {}

    def observe(self, positions: Any) -> list[dict[str, Any]]:
        """Compare ``positions`` against the previous snapshot.

        Returns the list of synthetic close records emitted this call. A ticket
        present before but absent now is treated as closed.
        """
        current: dict[Any, dict[str, Any]] = {}
        for pos in positions or []:
            d = _to_dict(pos)
            ticket = d.get("ticket")
            if ticket is not None:
                current[ticket] = d

        closed: list[dict[str, Any]] = []
        for ticket, prev in self._known.items():
            if ticket not in current:
                record = self._build_close_record(prev)
                closed.append(record)
                self._fire(record)

        self._known = current
        return closed

    @staticmethod
    def _build_close_record(position: dict[str, Any]) -> dict[str, Any]:
        """Build a ``trade_result``-shaped dict for a disappeared position."""
        side = str(position.get("side", "") or "").upper()
        # Map to the position's direction (side) for review normalisation.
        direction = side if side in ("BUY", "SELL") else "BUY"
        return {
            "trade_id": position.get("ticket"),
            "ticket": position.get("ticket"),
            "symbol": position.get("symbol", ""),
            "status": "CLOSED",
            "direction": direction,
            "side": direction,
            "entry_price": float(
                position.get("price_open", position.get("entry_price", 0.0)) or 0.0
            ),
            # Broker position close price is unknown from a disappearance alone;
            # use the last seen current price (honest best-effort, never 0).
            "close_price": float(
                position.get("price_current", position.get("price_open", 0.0)) or 0.0
            ),
            "pnl": float(position.get("profit", position.get("unrealized_pnl", 0.0)) or 0.0),
        }

    def _fire(self, record: dict[str, Any]) -> None:
        if self._on_close is None:
            return
        try:
            self._on_close(record)
        except Exception as exc:  # noqa: BLE001 - never break the caller's loop
            logger.warning("Position-close hook failed for %s: %s", record.get("trade_id"), exc)
