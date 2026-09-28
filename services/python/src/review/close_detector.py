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
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

__all__ = ["PositionCloseDetector"]


# Signature of the optional close-price resolver: ticket -> deal dict or None.
CloseDealResolver = Callable[[Any], Optional[dict[str, Any]]]


def _default_close_deal_resolver(ticket: Any) -> Optional[dict[str, Any]]:
    """Read the real closing deal for ``ticket`` from the MT5 connector.

    Fail-safe: any import/error returns ``None`` so the detector falls back to
    the last-seen snapshot. Never raises.
    """
    try:
        from mt5 import connector

        return connector.get_position_close_deal(ticket)
    except Exception:  # noqa: BLE001 - resolver is best-effort
        return None


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

    def __init__(
        self,
        on_close: Optional[Any] = None,
        close_deal_resolver: Optional[CloseDealResolver] = None,
    ) -> None:
        self._on_close = on_close
        # Optional resolver that returns the real closing deal (price/time/profit)
        # for a ticket from the broker's deal history. When it yields nothing the
        # record falls back to the last-seen snapshot (honest, flagged).
        self._close_deal_resolver = close_deal_resolver or _default_close_deal_resolver
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

    def _build_close_record(self, position: dict[str, Any]) -> dict[str, Any]:
        """Build a ``trade_result``-shaped dict for a disappeared position."""
        side = str(position.get("side", "") or "").upper()
        # Map to the position's direction (side) for review normalisation.
        direction = side if side in ("BUY", "SELL") else "BUY"
        ticket = position.get("ticket")
        record = {
            "trade_id": ticket,
            "ticket": ticket,
            "symbol": position.get("symbol", ""),
            "status": "CLOSED",
            "direction": direction,
            "side": direction,
            "entry_price": float(
                position.get("price_open", position.get("entry_price", 0.0)) or 0.0
            ),
            # Broker position close price is unknown from a disappearance alone;
            # default to the last seen current price (honest best-effort, never
            # 0). Overridden below when the real closing deal is available.
            "close_price": float(
                position.get("price_current", position.get("price_open", 0.0)) or 0.0
            ),
            "pnl": float(position.get("profit", position.get("unrealized_pnl", 0.0)) or 0.0),
            # Provenance of the close price so the R can be audited:
            # "last_seen" (snapshot fallback) vs "deal_history" (real fill).
            "close_price_source": "last_seen",
        }
        # Prefer the REAL closing deal from the broker's history (real exit
        # price/time/profit) so R is computed from the true outcome. Fail-safe:
        # a missing deal leaves the last-seen fallback in place.
        try:
            deal = self._close_deal_resolver(ticket) if ticket is not None else None
        except Exception:  # noqa: BLE001 - resolver must never break the close path
            deal = None
        if isinstance(deal, dict) and deal.get("price"):
            try:
                real_price = float(deal["price"])
                if real_price > 0:
                    record["close_price"] = real_price
                    record["close_price_source"] = "deal_history"
                    if deal.get("profit") is not None:
                        record["pnl"] = float(deal["profit"])
                    # Real close time (MT5 epoch seconds) → ISO string for bucketing.
                    raw_time = deal.get("time")
                    if raw_time:
                        from datetime import datetime, timezone

                        record["closed_at"] = datetime.fromtimestamp(
                            int(raw_time), tz=timezone.utc
                        ).isoformat()
            except (TypeError, ValueError):
                pass
        # T3b: attach the entry-time decision context (agent outputs / news
        # events / regime) registered when the entry was executed, so the
        # learning loops in the review callback have the raw material they
        # need. Fail-safe: a missing entry simply leaves the record as-is.
        try:
            from .entry_context import get_entry_context

            ctx = get_entry_context(position.get("ticket"))
        except Exception:  # noqa: BLE001 - the bridge is best-effort
            ctx = {}
        if ctx:
            if not record.get("symbol") and ctx.get("symbol"):
                record["symbol"] = ctx["symbol"]
            if ctx.get("agent_outputs"):
                record["agent_outputs"] = ctx["agent_outputs"]
            if ctx.get("news_events"):
                record["news_events"] = ctx["news_events"]
            if ctx.get("regime"):
                record["regime"] = ctx["regime"]
            # Carry the ORIGINAL stop-loss so the review can compute the trade's
            # R-multiple (risk = |entry - initial SL|). The broker snapshot only
            # shows the CURRENT SL (possibly trailed), so the entry context is
            # the authoritative source for the initial risk.
            if ctx.get("entry_price") and not record.get("entry_price"):
                record["entry_price"] = float(ctx["entry_price"])
            if ctx.get("stop_loss"):
                record["stop_loss"] = float(ctx["stop_loss"])
        return record

    def _fire(self, record: dict[str, Any]) -> None:
        if self._on_close is None:
            return
        try:
            self._on_close(record)
        except Exception as exc:  # noqa: BLE001 - never break the caller's loop
            logger.warning("Position-close hook failed for %s: %s", record.get("trade_id"), exc)
