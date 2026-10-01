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
                    if deal.get("ticket") is not None:
                        record["broker_deal_ticket"] = deal["ticket"]
                    # Real close time: raw MT5 epoch = broker server wall clock
                    # (+3 h vs true UTC) → convert to the true UTC instant so
                    # ``closed_at`` is not stamped hours in the future
                    # (see mt5.broker_time).
                    raw_time = deal.get("time")
                    if raw_time:
                        from mt5.broker_time import from_broker_epoch

                        record["closed_at"] = from_broker_epoch(raw_time).isoformat()
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
        # Close reason (spec §3.1): infer from the close context when explicit —
        # SL hit / TP hit is detected by comparing the exit price against the
        # entry-time SL/TP bands; explicit close_reason on the input position is
        # preferred when present. Never fabricated: "unknown" when indeterminate.
        if not record.get("close_reason"):
            explicit = str(position.get("close_reason") or position.get("reason") or "").strip()
            if explicit:
                record["close_reason"] = explicit[:64]
            else:
                try:
                    sl_ctx = float((ctx or {}).get("stop_loss") or 0.0)
                    tp_ctx = float((ctx or {}).get("take_profit") or 0.0)
                    exit_px = float(record.get("close_price") or 0.0)
                    inferred = ""
                    if (
                        sl_ctx > 0
                        and exit_px > 0
                        and abs(exit_px - sl_ctx) / max(exit_px, 1e-9) < 0.0005
                    ):
                        inferred = "STOP_LOSS"
                    elif (
                        tp_ctx > 0
                        and exit_px > 0
                        and abs(exit_px - tp_ctx) / max(exit_px, 1e-9) < 0.0005
                    ):
                        inferred = "TAKE_PROFIT"
                    record["close_reason"] = inferred or "unknown"
                except (TypeError, ValueError, ZeroDivisionError):
                    record["close_reason"] = "unknown"
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
            # Take-profit / planned RR (spec §3.2) — carried for the ledger close
            # record so the exit snapshot keeps the entry-time plan intact.
            if ctx.get("take_profit"):
                try:
                    record["take_profit"] = float(ctx["take_profit"])
                except (TypeError, ValueError):
                    pass
            if ctx.get("planned_rr"):
                try:
                    record["planned_rr"] = float(ctx["planned_rr"])
                except (TypeError, ValueError):
                    pass
            if ctx.get("risk_distance"):
                try:
                    record["risk_distance"] = float(ctx["risk_distance"])
                except (TypeError, ValueError):
                    pass
        return record

    def _fire(self, record: dict[str, Any]) -> None:
        if self._on_close is None:
            return
        try:
            self._on_close(record)
        except Exception as exc:  # noqa: BLE001 - never break the caller's loop
            logger.warning("Position-close hook failed for %s: %s", record.get("trade_id"), exc)
