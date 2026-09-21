# -*- coding: utf-8 -*-
"""Order Builder (EPIC 08.03) and Execution Recovery Engine (EPIC 08.07).

- OrderBuilder: Deterministically builds OrderRequest objects from validated
  trade proposals or decision states, performing symbol normalization,
  price auto-population, and magic number tracking.
- ExecutionRecoveryEngine: Monitors position and order state for critical
  mismatches between internal tracking and MT5 live state, setting execution
  recovery states and blocking new orders on critical mismatches.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Sequence

from execution.engine import ExecutionEngine, OrderRequest

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Order Builder (08.03)
# ---------------------------------------------------------------------------


class OrderBuilderError(ValueError):
    """Raised when an order request cannot be built from a proposal."""


class OrderBuilder:
    """Builds OrderRequest instances from raw or normalized trade proposals."""

    def __init__(
        self,
        default_magic: int = 70000,
        symbol_prefix: str = "",
        symbol_suffix: str = "",
        symbol_spec_provider: Any = None,
    ) -> None:
        self.default_magic = default_magic
        self.symbol_prefix = symbol_prefix
        self.symbol_suffix = symbol_suffix
        # Optional callable ``(symbol) -> dict`` returning broker symbol metadata
        # (volume_step/min/max, digits). When supplied, order volume/prices are
        # normalised to broker constraints (audit P1-4). Default None keeps the
        # previous pass-through behaviour.
        self.symbol_spec_provider = symbol_spec_provider

    def build_order_request(
        self,
        proposal: dict[str, Any],
        market_quote: dict[str, Any] | None = None,
    ) -> OrderRequest:
        """Build a validated OrderRequest from a trade proposal.

        Args:
            proposal: Dictionary containing trade details (symbol, side/order_type,
              volume/lots, price, sl, tp, magic, comment, idempotency_key).
            market_quote: Optional quote snapshot with 'ask' and 'bid' prices to auto-fill
              market order prices if price is 0 or unprovided.

        Returns:
            Configured OrderRequest instance.

        Raises:
            OrderBuilderError if required fields are missing or invalid.
        """
        if not isinstance(proposal, dict):
            raise OrderBuilderError("Proposal must be a dictionary")

        # 1. Symbol normalization
        raw_symbol = proposal.get("symbol") or proposal.get("pair")
        if not raw_symbol or not isinstance(raw_symbol, str) or not raw_symbol.strip():
            raise OrderBuilderError("Proposal missing valid symbol")

        clean_symbol = raw_symbol.strip().upper()
        if self.symbol_prefix and not clean_symbol.startswith(self.symbol_prefix):
            clean_symbol = f"{self.symbol_prefix}{clean_symbol}"
        if self.symbol_suffix and not clean_symbol.endswith(self.symbol_suffix):
            clean_symbol = f"{clean_symbol}{self.symbol_suffix}"

        # 2. Side / Order Type mapping
        raw_side = proposal.get("order_type") or proposal.get("side") or proposal.get("action")
        if not raw_side or not isinstance(raw_side, str):
            raise OrderBuilderError("Proposal missing valid side or order_type")

        clean_side = raw_side.strip().upper()
        if clean_side in ("BUY", "LONG"):
            order_type = "BUY"
        elif clean_side in ("SELL", "SHORT"):
            order_type = "SELL"
        elif clean_side in (
            "BUY_LIMIT",
            "SELL_LIMIT",
            "BUY_STOP",
            "SELL_STOP",
            "BUY_STOP_LIMIT",
            "SELL_STOP_LIMIT",
        ):
            order_type = clean_side
        else:
            raise OrderBuilderError(f"Unsupported order side/type: '{raw_side}'")

        # 3. Volume / Lot Size extraction
        raw_volume = proposal.get("volume") if "volume" in proposal else proposal.get("lots")
        if raw_volume is None:
            raw_volume = proposal.get("size", 0.0)

        try:
            volume = float(raw_volume)
        except (ValueError, TypeError) as exc:
            raise OrderBuilderError(f"Invalid volume value: {raw_volume}") from exc

        if volume <= 0:
            raise OrderBuilderError(f"Volume must be positive, got {volume}")

        # 4. Price auto-fill if market order
        raw_price = proposal.get("price", 0.0)
        try:
            price = float(raw_price) if raw_price is not None else 0.0
        except (ValueError, TypeError):
            price = 0.0

        if price <= 0.0 and market_quote:
            if "BUY" in order_type and "ask" in market_quote:
                price = float(market_quote["ask"])
            elif "SELL" in order_type and "bid" in market_quote:
                price = float(market_quote["bid"])

        # 5. Stop Loss & Take Profit
        sl = float(proposal.get("sl") or proposal.get("stop_loss") or 0.0)
        tp = float(proposal.get("tp") or proposal.get("take_profit") or 0.0)

        # 6. Magic & Comment
        magic = int(proposal.get("magic") or self.default_magic)
        comment = str(proposal.get("comment") or proposal.get("tag") or f"EA-Bot-{order_type}")

        # 7. Idempotency Key
        idempotency_key = str(
            proposal.get("idempotency_key") or proposal.get("client_order_id") or ""
        )

        # 8. Broker constraint normalisation (audit P1-4): snap the volume to a
        # valid step and round prices to the symbol's digits when a spec is
        # available. Any adjustment is logged; failure is non-fatal (we keep the
        # original value rather than dropping the order).
        volume, price, sl, tp = self._normalise_to_spec(clean_symbol, volume, price, sl, tp)

        kwargs: dict[str, Any] = {
            "symbol": clean_symbol,
            "order_type": order_type,
            "volume": volume,
            "price": price,
            "sl": sl,
            "tp": tp,
            "magic": magic,
            "comment": comment,
        }
        if idempotency_key:
            kwargs["idempotency_key"] = idempotency_key

        return OrderRequest(**kwargs)

    # ------------------------------------------------------------------
    # Broker constraint normalisation (audit P1-4)
    # ------------------------------------------------------------------
    def _normalise_to_spec(
        self,
        symbol: str,
        volume: float,
        price: float,
        sl: float,
        tp: float,
    ) -> tuple[float, float, float, float]:
        """Snap volume to ``volume_step`` and round prices to ``digits``.

        Only runs when a ``symbol_spec_provider`` is configured. Any error is
        swallowed (the original values are returned) so a spec lookup failure
        can never drop an otherwise-valid order.
        """
        if self.symbol_spec_provider is None:
            return volume, price, sl, tp
        try:
            spec = self.symbol_spec_provider(symbol) or {}
        except Exception as exc:  # noqa: BLE001 - spec lookup is best-effort
            logger.warning("Symbol spec lookup failed for %s: %s", symbol, exc)
            return volume, price, sl, tp
        if not isinstance(spec, dict) or not spec:
            return volume, price, sl, tp

        # ── Volume: clamp to [min, max] and snap to the nearest step ────────
        try:
            step = float(spec.get("volume_step") or 0.0)
            vmin = float(spec.get("volume_min") or 0.0)
            vmax = float(spec.get("volume_max") or 0.0)
            new_volume = float(volume)
            if step > 0:
                new_volume = round(new_volume / step) * step
                # Avoid floating-point artefacts (e.g. 0.30000000000000004).
                new_volume = round(new_volume, 8)
            if vmin > 0 and new_volume < vmin:
                new_volume = vmin
            if vmax > 0 and new_volume > vmax:
                new_volume = vmax
            if new_volume != volume:
                logger.info(
                    "Volume normalised for %s: %s → %s (step=%s, min=%s, max=%s)",
                    symbol,
                    volume,
                    new_volume,
                    step,
                    vmin,
                    vmax,
                )
            volume = new_volume
        except (TypeError, ValueError) as exc:
            logger.warning("Volume normalisation skipped for %s: %s", symbol, exc)

        # ── Prices: round to the symbol's digits ────────────────────────────
        try:
            digits = int(spec.get("digits")) if spec.get("digits") is not None else None
        except (TypeError, ValueError):
            digits = None
        if digits is not None:
            if price > 0:
                price = round(price, digits)
            if sl > 0:
                sl = round(sl, digits)
            if tp > 0:
                tp = round(tp, digits)

        return volume, price, sl, tp


# ---------------------------------------------------------------------------
# Recovery Engine (08.07)
# ---------------------------------------------------------------------------


class RecoveryState(Enum):
    """Status of the execution recovery engine."""

    NORMAL = "NORMAL"
    WARN_MISMATCH = "WARN_MISMATCH"
    BLOCKED_CRITICAL = "BLOCKED_CRITICAL"


@dataclass
class MismatchEvent:
    """Record of a state mismatch between internal tracking and live MT5 state."""

    symbol: str
    mismatch_type: str
    internal_val: Any
    broker_val: Any
    severity: str = "HIGH"  # CRITICAL, HIGH, WARN
    timestamp: float = field(default_factory=time.time)
    resolved: bool = False
    resolution_notes: str = ""


class ExecutionRecoveryEngine:
    """Reconciles position & order mismatches and blocks execution on critical errors."""

    def __init__(
        self,
        execution_engine: ExecutionEngine | None = None,
        critical_mismatch_threshold: int = 1,
    ) -> None:
        self.execution_engine = execution_engine
        self.critical_mismatch_threshold = critical_mismatch_threshold
        self.state = RecoveryState.NORMAL
        self.mismatch_history: list[MismatchEvent] = []

    def is_execution_blocked(self) -> bool:
        """Return True if new order executions must be blocked due to critical mismatch."""
        return self.state == RecoveryState.BLOCKED_CRITICAL

    def audit_reconciliation(
        self,
        internal_positions: Sequence[dict[str, Any]],
        broker_positions: Sequence[dict[str, Any]],
    ) -> list[MismatchEvent]:
        """Compare internal position ledger against broker/MT5 positions.

        Detects:
        - Orphan broker position (position exists in MT5 but missing in internal ledger)
        - Missing internal position (position in ledger missing in MT5)
        - Parameter mismatch (lot size, SL/TP deviation)

        Returns list of new MismatchEvents generated.
        """
        new_events: list[MismatchEvent] = []
        internal_by_ticket = {
            int(p["ticket"]): p for p in internal_positions if "ticket" in p and p["ticket"]
        }
        broker_by_ticket = {
            int(p["ticket"]): p for p in broker_positions if "ticket" in p and p["ticket"]
        }

        # 1. Orphan broker positions
        for ticket, b_pos in broker_by_ticket.items():
            if ticket not in internal_by_ticket:
                event = MismatchEvent(
                    symbol=str(b_pos.get("symbol", "UNKNOWN")),
                    mismatch_type="ORPHAN_BROKER_POSITION",
                    internal_val=None,
                    broker_val=b_pos,
                    severity="CRITICAL",
                )
                new_events.append(event)

        # 2. Missing internal positions
        for ticket, i_pos in internal_by_ticket.items():
            if ticket not in broker_by_ticket:
                event = MismatchEvent(
                    symbol=str(i_pos.get("symbol", "UNKNOWN")),
                    mismatch_type="MISSING_INTERNAL_POSITION",
                    internal_val=i_pos,
                    broker_val=None,
                    severity="CRITICAL",
                )
                new_events.append(event)

        # 3. Parameter mismatches (volume, sl, tp)
        for ticket, i_pos in internal_by_ticket.items():
            if ticket in broker_by_ticket:
                b_pos = broker_by_ticket[ticket]
                i_vol = float(i_pos.get("volume", 0.0))
                b_vol = float(b_pos.get("volume", 0.0))
                if abs(i_vol - b_vol) > 0.0001:
                    event = MismatchEvent(
                        symbol=str(i_pos.get("symbol", "UNKNOWN")),
                        mismatch_type="VOLUME_MISMATCH",
                        internal_val=i_vol,
                        broker_val=b_vol,
                        severity="CRITICAL",
                    )
                    new_events.append(event)

                # Audit P3-2: SL/TP deviation (the docstring promised this; the
                # code previously only checked volume). A divergence between the
                # internal ledger and the broker stops/targets is CRITICAL.
                for field_name, mismatch_type in (("sl", "SL_MISMATCH"), ("tp", "TP_MISMATCH")):
                    i_val = float(i_pos.get(field_name, 0.0) or 0.0)
                    b_val = float(b_pos.get(field_name, 0.0) or 0.0)
                    if abs(i_val - b_val) > 1e-6:
                        new_events.append(
                            MismatchEvent(
                                symbol=str(i_pos.get("symbol", "UNKNOWN")),
                                mismatch_type=mismatch_type,
                                internal_val=i_val,
                                broker_val=b_val,
                                severity="CRITICAL",
                            )
                        )

        self.mismatch_history.extend(new_events)

        # Evaluate state transition
        critical_count = sum(
            1 for e in self.mismatch_history if not e.resolved and e.severity == "CRITICAL"
        )
        if critical_count >= self.critical_mismatch_threshold:
            self.state = RecoveryState.BLOCKED_CRITICAL
            logger.error(
                "ExecutionRecoveryEngine state set to BLOCKED_CRITICAL (%d critical mismatches)",
                critical_count,
            )
        elif critical_count > 0:
            self.state = RecoveryState.WARN_MISMATCH
        else:
            self.state = RecoveryState.NORMAL

        return new_events

    def clear_recovery_block(self, notes: str = "Manual override") -> None:
        """Clear the recovery block and reset state to NORMAL after resolving mismatches."""
        for event in self.mismatch_history:
            if not event.resolved:
                event.resolved = True
                event.resolution_notes = notes
        self.state = RecoveryState.NORMAL
        logger.info("Recovery state reset to NORMAL. Notes: %s", notes)
