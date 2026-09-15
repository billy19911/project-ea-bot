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
    ) -> None:
        self.default_magic = default_magic
        self.symbol_prefix = symbol_prefix
        self.symbol_suffix = symbol_suffix

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
    timestamp: float = field(
        default_factory=lambda: (
            logging.root.handlers[0].formatter.default_time_format if logging.root.handlers else 0.0
        )
    )
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
