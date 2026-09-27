# -*- coding: utf-8 -*-
"""Trade manager — per-cycle dynamic stop-loss management.

Bridges the pure decisions in :mod:`execution.sltp_manager` to the broker via
:meth:`execution.engine.ExecutionEngine.modify_position_sltp`. On each call it:

1. Reads the broker's open positions (read-only).
2. For each position, computes the desired stop-loss (BEP / progressive / trail).
3. When the desired stop is tighter than the current one, sends the change
   (arm-gated, fail-closed inside the engine).

Design guarantees:

* **Fail-safe** — any read/decision/send error for one position never blocks the
  others or the caller's loop; errors are logged and swallowed.
* **Monotonic** — the manager only ever *tightens* a stop; it never widens risk.
* **Observability** — keeps a small in-memory log of the last N modifications
  plus per-reason counters, exposed via :meth:`snapshot` for the dashboard.
* **Opt-in** — the caller decides when to call :meth:`manage`; nothing runs on a
  timer of its own.
"""

from __future__ import annotations

import logging
from collections import deque
from typing import Any, Callable, Optional

from execution.sltp_manager import SLTPConfig, decide_stop_loss

logger = logging.getLogger(__name__)

__all__ = ["TradeManager"]


def _to_dict(obj: Any) -> dict[str, Any]:
    """Best-effort dict conversion for pydantic models / dataclasses / objects."""
    if isinstance(obj, dict):
        return dict(obj)
    dump = getattr(obj, "model_dump", None)
    if callable(dump):
        try:
            return dict(dump())
        except Exception:  # noqa: BLE001 - malformed model
            return {}
    # dataclass / plain object fallback
    result: dict[str, Any] = {}
    for attr in (
        "ticket",
        "symbol",
        "side",
        "volume",
        "entry_price",
        "price_open",
        "current_price",
        "price_current",
        "sl",
        "tp",
    ):
        if hasattr(obj, attr):
            result[attr] = getattr(obj, attr)
    return result


class TradeManager:
    """Applies dynamic SL management to open positions each cycle.

    Args:
        config: :class:`SLTPConfig` controlling BEP / progressive / trailing.
        position_reader: Callable returning the broker's open positions
            (list of dicts/objects). Defaults to ``mt5.connector.get_positions``.
        tick_reader: Callable ``(symbol) -> tick`` exposing ``bid``/``ask``.
            Defaults to ``mt5.connector.get_tick``.
        atr_reader: Callable ``(symbol) -> float`` returning the ATR to use for
            trailing. Defaults to a hook the runtime can inject (returns 0.0 when
            unavailable, which disables trailing only).
        apply_sltp: Callable ``(ticket, symbol, sl, tp) -> dict`` that transmits
            the change. Defaults to the execution engine's
            ``modify_position_sltp``.
    """

    def __init__(
        self,
        config: Optional[SLTPConfig] = None,
        position_reader: Optional[Callable[[], list[Any]]] = None,
        tick_reader: Optional[Callable[[str], Any]] = None,
        atr_reader: Optional[Callable[[str], float]] = None,
        apply_sltp: Optional[Callable[[int, str, float, Optional[float]], dict]] = None,
    ) -> None:
        self.config = config or SLTPConfig()
        self._position_reader = position_reader
        self._tick_reader = tick_reader
        self._atr_reader = atr_reader
        self._apply_sltp = apply_sltp
        self._recent: deque[dict[str, Any]] = deque(maxlen=50)
        self._counts: dict[str, int] = {
            "evaluated": 0,
            "modified": 0,
            "errors": 0,
            "skipped": 0,
        }

    # ------------------------------------------------------------------
    # Readers / senders (with production defaults)
    # ------------------------------------------------------------------
    def _positions(self) -> list[Any]:
        if self._position_reader is not None:
            return list(self._position_reader() or [])
        for mod_name in ("mt5.connector", "src.mt5.connector"):
            try:
                import importlib

                return list(importlib.import_module(mod_name).get_positions() or [])
            except Exception:  # noqa: BLE001 - fail-safe
                continue
        return []

    def _tick(self, symbol: str) -> Any:
        if self._tick_reader is not None:
            return self._tick_reader(symbol)
        for mod_name in ("mt5.connector", "src.mt5.connector"):
            try:
                import importlib

                return importlib.import_module(mod_name).get_tick(symbol)
            except Exception:  # noqa: BLE001 - fail-safe
                continue
        return None

    def _atr(self, symbol: str) -> float:
        if self._atr_reader is None:
            return 0.0
        try:
            return float(self._atr_reader(symbol) or 0.0)
        except Exception:  # noqa: BLE001 - fail-safe
            return 0.0

    def _apply(self, ticket: int, symbol: str, sl: float, tp: Optional[float]) -> dict:
        if self._apply_sltp is not None:
            return self._apply_sltp(ticket, symbol, sl, tp) or {}
        try:
            from execution.engine import ExecutionEngine

            return ExecutionEngine().modify_position_sltp(ticket, symbol, sl, tp)
        except Exception as exc:  # noqa: BLE001 - fail-safe
            return {"success": False, "message": f"no apply hook: {exc}"}

    # ------------------------------------------------------------------
    # Main entry
    # ------------------------------------------------------------------
    def manage(self) -> list[dict[str, Any]]:
        """Evaluate every open position and apply warranted stop changes.

        Returns the list of modifications applied this call (empty when none).
        Never raises.
        """
        applied: list[dict[str, Any]] = []
        try:
            positions = self._positions()
        except Exception as exc:  # noqa: BLE001 - fail-safe
            self._counts["errors"] += 1
            logger.warning("Trade manager could not read positions: %s", exc)
            return applied

        for raw in positions:
            try:
                change = self._evaluate_and_apply(raw)
                if change is not None:
                    applied.append(change)
            except Exception as exc:  # noqa: BLE001 - one position never blocks others
                self._counts["errors"] += 1
                logger.warning("Trade manager error for a position: %s", exc)
        return applied

    def _evaluate_and_apply(self, raw: Any) -> Optional[dict[str, Any]]:
        pos = _to_dict(raw)
        ticket = pos.get("ticket")
        symbol = str(pos.get("symbol") or "")
        if not ticket or not symbol:
            self._counts["skipped"] += 1
            return None

        side_raw = pos.get("side")
        side = getattr(side_raw, "value", side_raw)
        side = str(side or "").lower()
        if side not in ("buy", "sell"):
            # Derive from volume sign or type when needed.
            self._counts["skipped"] += 1
            return None

        entry = pos.get("entry_price", pos.get("price_open", 0.0))
        current_sl = pos.get("sl", 0.0)
        tp = pos.get("tp", 0.0) or None

        tick = self._tick(symbol)
        bid = getattr(tick, "bid", None) if tick is not None else None
        ask = getattr(tick, "ask", None) if tick is not None else None
        # A long is exited at the bid; a short at the ask.
        price = bid if side == "buy" else ask
        if price is None:
            price = pos.get("current_price", pos.get("price_current", 0.0))

        atr = self._atr(symbol)

        self._counts["evaluated"] += 1
        decision = decide_stop_loss(
            direction=side,
            entry_price=entry,
            current_sl=current_sl,
            current_price=price,
            atr=atr,
            initial_risk=None,
            config=self.config,
        )
        if decision is None:
            self._counts["skipped"] += 1
            return None

        result = self._apply(int(ticket), symbol, decision.new_sl, tp)
        record = {
            "ticket": int(ticket),
            "symbol": symbol,
            "side": side,
            "old_sl": current_sl,
            "new_sl": decision.new_sl,
            "reason": decision.reason,
            "locked_r": decision.locked_r,
            "sent": bool(result.get("success")),
            "simulated": bool(result.get("simulated")),
            "error_code": int(result.get("error_code", 0) or 0),
            "message": str(result.get("message", "") or ""),
        }
        if result.get("success"):
            self._counts["modified"] += 1
        else:
            self._counts["errors"] += 1
        self._recent.append(record)
        logger.info(
            "SL managed: #%s %s -> %.5f (%s, sent=%s)",
            ticket,
            symbol,
            decision.new_sl,
            decision.reason,
            result.get("success"),
        )
        return record

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------
    def snapshot(self) -> dict[str, Any]:
        """Return counters + recent modifications for the dashboard."""
        return {
            "enabled": self.config.enabled,
            "counts": dict(self._counts),
            "recent": list(self._recent),
        }
