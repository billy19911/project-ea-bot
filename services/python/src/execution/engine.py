# -*- coding: utf-8 -*-
"""Execution Engine — order validation, sending, confirmation, retry, and duplicate prevention.

Phase 14 deterministic trading engine component for MetaTrader 5 order execution.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from .state_machine import OrderState, get_order, set_order

logger = logging.getLogger(__name__)

# Valid order types accepted by the execution engine
VALID_ORDER_TYPES = {
    "BUY",
    "SELL",
    "BUY_LIMIT",
    "SELL_LIMIT",
    "BUY_STOP",
    "SELL_STOP",
    "BUY_STOP_LIMIT",
    "SELL_STOP_LIMIT",
}

# Transient MT5 return codes that qualify for retry with exponential backoff
TRANSIENT_RETCODES = {
    10004,  # TRADE_RETCODE_REQUOTE
    10006,  # TRADE_RETCODE_REJECT
    10007,  # TRADE_RETCODE_CANCEL
    10012,  # TRADE_RETCODE_TIMEOUT
    10015,  # TRADE_RETCODE_INVALID_PRICE (price slipped/changed)
    10018,  # TRADE_RETCODE_MARKET_CLOSED (transient market transition)
    10021,  # TRADE_RETCODE_PRICE_CHANGED
    10027,  # TRADE_RETCODE_TRADE_DISABLED
    10031,  # TRADE_RETCODE_CONNECTION
}

# Substring keywords indicating transient network or broker conditions
TRANSIENT_KEYWORDS = (
    "timeout",
    "requote",
    "trade_disabled",
    "trade disabled",
    "connection",
    "busy",
    "price changed",
    "network",
    "offline",
    "temporary",
)


@dataclass
class OrderRequest:
    """Trading order request with idempotency key and risk parameters.

    Attributes:
        symbol: Financial instrument symbol (e.g. "EURUSD", "XAUUSD").
        order_type: Order type ("BUY", "SELL", "BUY_LIMIT", etc.).
        volume: Trade lot volume (e.g. 0.1, 1.0).
        price: Desired execution price, 0.0 for market order.
        sl: Stop loss price level (0.0 if not set).
        tp: Take profit price level (0.0 if not set).
        magic: Expert Advisor magic number for tracking.
        comment: Order comment/tag.
        idempotency_key: Unique order submission ID to prevent duplicates.
    """

    symbol: str
    order_type: str
    volume: float
    price: float = 0.0
    sl: float = 0.0
    tp: float = 0.0
    magic: int = 0
    comment: str = ""
    idempotency_key: str = field(default_factory=lambda: str(uuid.uuid4()))
    approval_token: Optional[str] = None
    """Gate-issued approval marker (audit B-3).

    When ``ExecutionEngine(require_approval=True)`` is set, ``execute_order``
    refuses to dispatch an order whose ``approval_token`` is empty. Only the
    deterministic pipeline, *after* the Risk Gate approves, stamps this token —
    so a direct call to the executor (or an un-gated order surface) fails
    closed instead of reaching MT5.
    """
    # TASK 08 — durable order identity. Optional account/signal metadata stamped
    # by the caller (fan-out coordinator / pipeline) so the persisted ledger can
    # always trace an order back to the canonical signal + account + terminal it
    # belongs to. ``intent_id`` is the ``idempotency_key`` above; the broker
    # tickets are filled in by the engine once the broker acknowledges them.
    signal_id: Optional[str] = None
    account_id: Optional[str] = None
    terminal_id: Optional[str] = None
    broker_order_ticket: Optional[int] = None
    broker_deal_ticket: Optional[int] = None
    broker_position_ticket: Optional[int] = None


@dataclass
class ExecutionResult:
    """Outcome of an order execution attempt.

    Attributes:
        success: True if the order was successfully executed and confirmed.
        ticket: MT5 order/deal ticket number if successful.
        error_code: Error code (0 on success, MT5 retcode or internal code).
        error_message: Human-readable error description.
        retries: Number of retry attempts executed.
        position_opened: Synchronized position details if opened/confirmed.
    """

    success: bool
    ticket: Optional[int] = None
    error_code: int = 0
    error_message: str = ""
    retries: int = 0
    position_opened: Optional[dict[str, Any]] = None


@dataclass
class FanoutResult:
    """Aggregate outcome of a multi-terminal fan-out (F1).

    A single analysis decision is dispatched to every armed fan-out target.
    ``per_terminal`` records the individual outcome so a partial failure is
    visible (order succeeded on some terminals, failed on others) rather than
    collapsed into one ambiguous verdict.

    Attributes:
        results: One dict per target terminal:
            ``{terminal_id, label, symbol, volume, success, ticket, error_code,
            error_message, price}``.
        succeeded: Count of terminals where the order was executed.
        failed: Count of terminals where the order did NOT execute.
        target_count: How many terminals were targeted.
    """

    results: list[dict[str, Any]] = field(default_factory=list)
    succeeded: int = 0
    failed: int = 0
    target_count: int = 0

    @property
    def any_success(self) -> bool:
        return self.succeeded > 0

    @property
    def all_success(self) -> bool:
        return self.target_count > 0 and self.failed == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "results": list(self.results),
            "succeeded": self.succeeded,
            "failed": self.failed,
            "target_count": self.target_count,
            "any_success": self.any_success,
            "all_success": self.all_success,
        }


class ExecutionEngine:
    """Execution engine with order validation, retry logic, and duplicate prevention.

    Coordinates order lifecycle:
    1. Pre-flight validation (symbol, volume limits, price spread tolerance, SL/TP).
    2. Duplicate submission prevention via idempotency keys.
    3. Order dispatching to MT5 with exponential backoff on transient errors.
    4. Post-execution fill confirmation and position reconciliation.
    """

    def __init__(
        self,
        mt5_connector: Any = None,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        spread_tolerance: float = 0.005,
        min_volume: float = 0.01,
        max_volume: float = 100.0,
        simulation_mode: bool = False,
        order_locator: Optional[Callable[[OrderRequest], Optional[dict[str, Any]]]] = None,
        require_approval: bool = False,
    ) -> None:
        """Initialize the Execution Engine.

        Args:
            mt5_connector: MT5Connector instance or module for MT5 interaction.
            max_retries: Maximum retry attempts for transient failures (default 3).
            retry_delay: Base delay in seconds for exponential backoff (default 1.0s).
            spread_tolerance: Maximum allowable price deviation from current market quote.
            min_volume: Minimum allowable lot volume.
            max_volume: Maximum allowable lot volume.
            simulation_mode: When True and no real broker path exists, a *clearly
                labelled* simulated fill is returned (``success=True`` with
                ``simulated=True``). Defaults to **False**: with no connector and
                no native MetaTrader5, ``execute_order`` returns an honest
                ``success=False`` (never a fabricated ticket). Autonomy must
                opt in to simulation explicitly.
            order_locator: Optional callable ``(request) -> Optional[dict]`` that
                looks up an order/position already present at the broker for
                this request (matched by symbol/magic/volume). Used to make
                retries idempotent against LOST RESPONSES (audit P1-1): if a
                prior attempt actually landed but its reply was lost, the retry
                adopts that fill instead of sending a duplicate order.
            require_approval: When True (audit B-3), ``execute_order`` refuses to
                dispatch any order whose ``approval_token`` is empty, failing
                closed with an honest error. The production runtime opts in so
                the deterministic Risk Gate becomes an *executor-enforced*
                boundary, not merely a caller convention. Defaults to **False**
                to preserve existing direct/test usage.
        """
        self.mt5_connector = mt5_connector
        self.max_retries = max(0, max_retries)
        self.retry_delay = max(0.0, retry_delay)
        self.spread_tolerance = spread_tolerance
        self.min_volume = min_volume
        self.max_volume = max_volume
        self.simulation_mode = bool(simulation_mode)
        self.order_locator = order_locator
        self.require_approval = bool(require_approval)

        # In-memory tracking for pending and completed orders
        self._pending_orders: dict[str, float] = {}
        self._completed_orders: dict[str, ExecutionResult] = {}
        # Hardening §8: guards the duplicate-check + record-pending sequence so
        # two concurrent calls with the same idempotency key cannot BOTH pass
        # duplicate detection and both dispatch an order.
        self._registry_lock = threading.RLock()
        # Monotonic counter for simulated ticket generation (audit B8): two
        # simulated fills within the same millisecond must not collide on the
        # same ticket number.
        self._sim_ticket_seq = 0

    @staticmethod
    def _identity_fields(request: OrderRequest) -> dict[str, Any]:
        """Return the durable order-identity fields for a request (TASK 08).

        Only non-empty values are emitted so a partial identity never overwrites
        a previously-persisted good value with ``None``. The canonical
        ``intent_id`` is the request's idempotency key (durable across restarts).
        """
        fields: dict[str, Any] = {"intent_id": request.idempotency_key}
        for name in ("signal_id", "account_id", "terminal_id"):
            value = getattr(request, name, None)
            if value not in (None, ""):
                fields[name] = value
        for name in ("broker_order_ticket", "broker_deal_ticket", "broker_position_ticket"):
            value = getattr(request, name, None)
            if value not in (None, ""):
                fields[name] = value
        return fields

    def _next_simulated_ticket(self) -> int:
        """Return a unique, monotonically-increasing simulated ticket id.

        Uses a per-instance counter combined with the millisecond clock so that
        two simulated fills generated in the same millisecond (or in a tight
        loop) never share a ticket number.
        """
        self._sim_ticket_seq = (self._sim_ticket_seq + 1) % 1000
        return int(time.time() * 1000) % 1_000_000 * 1000 + self._sim_ticket_seq

    # ---------------------------------------------------------------------------
    # Execution-quality analytics (PRD §47) — best-effort observability
    # ---------------------------------------------------------------------------

    def _record_execution_quality(
        self,
        request: OrderRequest,
        *,
        actual_fill: float,
        rejected: bool = False,
        partial: bool = False,
        filled_ratio: float = 1.0,
        latency_ms: float = 0.0,
        spread: float = 0.0,
    ) -> None:
        """Record one observed execution into the shared analytics singleton.

        Best-effort: a failure here must NEVER raise into the execution path.
        Only REAL values are recorded — nothing is fabricated when a value is
        unknown (missing spread/latency default to 0.0/not-measured).
        """
        try:
            try:
                from ..observability.execution_quality import ExecutionRecord
                from ..system.v2_endpoints import get_execution_quality
            except ImportError:
                from src.observability.execution_quality import ExecutionRecord
                from src.system.v2_endpoints import get_execution_quality

            direction = 1
            side = str(getattr(request, "side", "") or "").upper()
            order_type = str(getattr(request, "order_type", "") or "").upper()
            if "SELL" in side or side == "1" or "SELL" in order_type:
                direction = -1
            requested = float(getattr(request, "price", 0.0) or 0.0)
            filled = float(actual_fill or 0.0)
            get_execution_quality().record(
                ExecutionRecord(
                    requested_entry=requested,
                    # Rejected orders have no fill — record 0.0 (real: nothing
                    # filled), never a fabricated price.
                    actual_fill=filled if not rejected else 0.0,
                    direction=direction,
                    spread=float(spread or 0.0),
                    latency_ms=float(latency_ms or 0.0),
                    rejected=bool(rejected),
                    partial=bool(partial),
                    filled_ratio=float(filled_ratio),
                )
            )
        except Exception as exc:  # noqa: BLE001 - analytics never breaks execution
            logger.debug("execution-quality record skipped: %s", exc)

    # ---------------------------------------------------------------------------
    # Duplicate Prevention API
    # ---------------------------------------------------------------------------

    def _is_duplicate(self, idempotency_key: str) -> bool:
        """Check if an order with the given idempotency key is already pending or completed.

        Phase 1 Item #6: also consults the DURABLE order-state ledger (state
        machine's attached store) so a process restart does NOT forget an
        already-submitted order. A key with a persisted record in a
        non-intent state (i.e. it was actually dispatched) is treated as a
        duplicate.

        Args:
            idempotency_key: Order uniqueness key.

        Returns:
            True if key exists in pending/completed registries OR the durable ledger.
        """
        if not idempotency_key:
            return False
        with self._registry_lock:
            if idempotency_key in self._pending_orders or idempotency_key in self._completed_orders:
                return True
            # Durable check: survives restart (Phase 1 Item #6).
            try:
                from .state_machine import OrderState, get_order, get_store

                store = get_store()
                if store is not None:
                    record = store.get_order(idempotency_key)
                    if record:
                        state = str(record.get("state", "")).lower()
                        # Any state beyond the fresh intent marker means this order
                        # already moved toward the broker → treat as duplicate.
                        if state and state != OrderState.INTENT_CREATED.value:
                            return True
                # In-memory ledger check (fallback when no durable store attached).
                try:
                    record = get_order(idempotency_key)
                    state = str(record.get("state", "")).lower()
                    if state and state != OrderState.INTENT_CREATED.value:
                        return True
                except KeyError:
                    pass
            except Exception as exc:  # noqa: BLE001 - durability check is best-effort
                logger.debug("Durable duplicate check skipped: %s", exc)
            return False

    def _record_pending(self, idempotency_key: str) -> None:
        """Record an idempotency key as pending execution.

        Args:
            idempotency_key: Order uniqueness key.
        """
        if idempotency_key:
            self._pending_orders[idempotency_key] = time.time()

    def _clear_pending(self, idempotency_key: str) -> None:
        """Remove an idempotency key from the pending registry.

        Args:
            idempotency_key: Order uniqueness key.
        """
        self._pending_orders.pop(idempotency_key, None)

    # ---------------------------------------------------------------------------
    # Order Validation API
    # ---------------------------------------------------------------------------

    def validate_order(self, request: OrderRequest) -> tuple[bool, list[str]]:
        """Perform pre-flight checks on the incoming order request.

        Validates:
        - Symbol validity (non-empty, exists in connector if available).
        - Order type validity.
        - Lot size boundaries (min/max lot limits).
        - Price spread tolerance against current market quotes.
        - Stop Loss and Take Profit sanity relative to order side.

        Args:
            request: The order request to validate.

        Returns:
            Tuple of (is_valid, list of error messages).
        """
        errors: list[str] = []

        # 1. Symbol validation
        if not request.symbol or not isinstance(request.symbol, str) or not request.symbol.strip():
            errors.append("Symbol cannot be empty")
            symbol_clean = ""
        else:
            # Audit P3-3: resolve broker suffixes (XAUUSD ↔ XAUUSDc) so a base
            # symbol still validates against the broker's naming. Fail-safe:
            # returns the input unchanged when resolution is impossible.
            symbol_clean = self._resolve_symbol(request.symbol)

        symbol_info = None
        if symbol_clean and self._has_symbol_lookup():
            symbol_info = self._get_symbol_info(symbol_clean)
            if symbol_info is None:
                errors.append(f"Invalid symbol '{symbol_clean}': not available in MT5")

        # 2. Order type validation
        order_type_clean = (request.order_type or "").strip().upper()
        if order_type_clean not in VALID_ORDER_TYPES:
            errors.append(
                f"Invalid order_type '{request.order_type}'. "
                f"Must be one of: {', '.join(sorted(VALID_ORDER_TYPES))}"
            )

        # 3. Lot size boundaries
        min_vol = self.min_volume
        max_vol = self.max_volume
        if symbol_info is not None:
            min_vol = self._get_field(symbol_info, "volume_min", min_vol) or min_vol
            max_vol = self._get_field(symbol_info, "volume_max", max_vol) or max_vol

        if request.volume <= 0:
            errors.append(f"Volume must be greater than 0, got {request.volume}")
        elif request.volume < min_vol:
            errors.append(f"Volume {request.volume} is below minimum allowed lot size {min_vol}")
        elif request.volume > max_vol:
            errors.append(f"Volume {request.volume} exceeds maximum allowed lot size {max_vol}")

        # 4. Price within spread tolerance
        current_tick = self._get_current_tick(symbol_clean) if symbol_clean else None
        if request.price > 0 and current_tick is not None:
            ask = getattr(current_tick, "ask", None)
            bid = getattr(current_tick, "bid", None)
            if ask is not None and bid is not None:
                is_buy = "BUY" in order_type_clean
                market_price = ask if is_buy else bid
                price_diff = abs(request.price - market_price)
                spread = abs(ask - bid)
                allowed_deviation = max(self.spread_tolerance, spread * 2.0)
                if price_diff > allowed_deviation:
                    errors.append(
                        f"Price {request.price} exceeds spread tolerance "
                        f"(diff {price_diff:.5f} > allowed {allowed_deviation:.5f})"
                    )

        # 5. Stop Loss and Take Profit consistency
        effective_price = request.price
        if effective_price <= 0 and current_tick is not None:
            effective_price = (
                getattr(current_tick, "ask", 0.0)
                if "BUY" in order_type_clean
                else getattr(current_tick, "bid", 0.0)
            )

        if effective_price > 0:
            if "BUY" in order_type_clean:
                if request.sl > 0 and request.sl >= effective_price:
                    errors.append(
                        "Buy order SL ({}) must be strictly below price "
                        "({})".format(request.sl, effective_price)
                    )
                if request.tp > 0 and request.tp <= effective_price:
                    errors.append(
                        "Buy order TP ({}) must be strictly above price "
                        "({})".format(request.tp, effective_price)
                    )
            elif "SELL" in order_type_clean:
                if request.sl > 0 and request.sl <= effective_price:
                    errors.append(
                        "Sell order SL ({}) must be strictly above price "
                        "({})".format(request.sl, effective_price)
                    )
                if request.tp > 0 and request.tp >= effective_price:
                    errors.append(
                        "Sell order TP ({}) must be strictly below price "
                        "({})".format(request.tp, effective_price)
                    )

        return (len(errors) == 0, errors)

    # ---------------------------------------------------------------------------
    # Order Execution API
    # ---------------------------------------------------------------------------

    def execute_order(self, request: OrderRequest) -> ExecutionResult:
        """Execute an order with validation, duplicate protection, and retry logic.

        Args:
            request: The order request to execute.

        Returns:
            ExecutionResult containing execution status, ticket, retries, and errors.
        """
        # Ensure idempotency key exists
        if not request.idempotency_key:
            request.idempotency_key = str(uuid.uuid4())

        # Audit B-3: make the deterministic Risk Gate an executor-enforced
        # boundary. When the engine is configured to require approval, an order
        # without a gate-issued token is refused BEFORE any MT5 dispatch. This
        # fails closed for direct callers / un-gated order surfaces.
        if self.require_approval and not getattr(request, "approval_token", None):
            msg = (
                "Execution rejected: require_approval is enabled but the order "
                "carries no gate-issued approval_token (fail-closed). Only the "
                "deterministic pipeline may stamp approval after the Risk Gate."
            )
            logger.warning(msg)
            set_order(request.idempotency_key, OrderState.UNKNOWN)
            self._record_execution_quality(request, actual_fill=0.0, rejected=True)
            return ExecutionResult(
                success=False,
                ticket=None,
                error_code=403,
                error_message=msg,
                retries=0,
                position_opened=None,
            )

        # Check duplicate submission
        if self._is_duplicate(request.idempotency_key):
            msg = (
                f"Duplicate order submission rejected: "
                f"idempotency key '{request.idempotency_key}' already processed or pending"
            )
            logger.warning(msg)
            self._record_execution_quality(request, actual_fill=0.0, rejected=True)
            return ExecutionResult(
                success=False,
                ticket=None,
                error_code=409,
                error_message=msg,
                retries=0,
                position_opened=None,
            )

        # Durable execution lifecycle (Phase 34): seed the order state machine.
        set_order(request.idempotency_key, OrderState.INTENT_CREATED)

        # Pre-flight order validation
        is_valid, validation_errors = self.validate_order(request)
        if not is_valid:
            error_str = "; ".join(validation_errors)
            logger.warning("Order validation failed: %s", error_str)
            set_order(
                request.idempotency_key,
                OrderState.UNKNOWN,
                extra={"rejected": True, "reason": error_str},
            )
            self._record_execution_quality(request, actual_fill=0.0, rejected=True)
            return ExecutionResult(
                success=False,
                ticket=None,
                error_code=400,
                error_message=f"Validation failed: {error_str}",
                retries=0,
                position_opened=None,
            )

        # Record pending state
        set_order(request.idempotency_key, OrderState.RISK_APPROVED)
        set_order(request.idempotency_key, OrderState.SUBMITTING)
        self._record_pending(request.idempotency_key)

        retries = 0
        last_error_code = 0
        last_error_message = ""

        try:
            for attempt in range(self.max_retries + 1):
                try:
                    send_started = time.monotonic()
                    send_res = self._send_to_mt5(request)
                    send_latency_ms = (time.monotonic() - send_started) * 1000.0
                    if send_res.get("success"):
                        ticket = send_res.get("ticket")
                        # TASK 08 — persist durable order identity atomically with
                        # the broker tickets. The broker order ticket == deal
                        # ticket for a market DEAL on MT5; the position ticket is
                        # what reconciliation matches against ``positions_get``.
                        identity = self._identity_fields(request)
                        set_order(
                            request.idempotency_key,
                            OrderState.SUBMITTED,
                            {"ticket": ticket, **identity, "broker_order_ticket": ticket},
                        )
                        set_order(
                            request.idempotency_key,
                            OrderState.ACKNOWLEDGED,
                            {"ticket": ticket, "broker_deal_ticket": ticket},
                        )
                        confirmed = self.confirm_execution(ticket)
                        if confirmed:
                            set_order(request.idempotency_key, OrderState.FILLED)
                            # Persist the identity fields the reconciliation
                            # providers need to match an internal position
                            # against the broker book (audit B-4 follow-up).
                            set_order(
                                request.idempotency_key,
                                OrderState.POSITION_CONFIRMED,
                                {
                                    "ticket": ticket,
                                    "symbol": request.symbol,
                                    "volume": request.volume,
                                    "magic": request.magic,
                                    **self._identity_fields(request),
                                    "broker_order_ticket": ticket,
                                    "broker_deal_ticket": ticket,
                                    "broker_position_ticket": ticket,
                                },
                            )

                        # Sync position state after execution
                        pos_summary = self.sync_position(request.symbol)

                        # Cleanup and final state handling
                        self._clear_pending(request.idempotency_key)
                        # If unknown state after retries, keep as UNKNOWN for later query
                        final_state = get_order(request.idempotency_key).get("state")
                        if final_state == OrderState.UNKNOWN.value:
                            set_order(request.idempotency_key, OrderState.UNKNOWN)
                        actual_fill = float(
                            send_res.get("price")
                            or send_res.get("fill_price")
                            or getattr(request, "price", 0.0)
                            or 0.0
                        )
                        self._record_execution_quality(
                            request,
                            actual_fill=actual_fill,
                            partial=bool(send_res.get("partial", False)),
                            filled_ratio=float(send_res.get("filled_ratio", 1.0) or 1.0),
                            latency_ms=send_latency_ms,
                            spread=float(send_res.get("spread", 0.0) or 0.0),
                        )
                        success_result = ExecutionResult(
                            success=True,
                            ticket=ticket,
                            error_code=0,
                            error_message="",
                            retries=retries,
                            position_opened=pos_summary if confirmed else None,
                        )
                        self._completed_orders[request.idempotency_key] = success_result
                        logger.info(
                            "Order executed successfully: ticket=%s, retries=%d, confirmed=%s",
                            ticket,
                            retries,
                            confirmed,
                        )
                        return success_result

                    last_error_code = send_res.get("error_code", 1)
                    last_error_message = send_res.get("message", "Order send returned failure")

                except Exception as exc:
                    last_error_code = -1
                    last_error_message = f"Execution exception: {exc}"
                    logger.warning("Attempt %d raised exception: %s", attempt + 1, exc)

                is_transient = self._is_transient_error(last_error_code, last_error_message)
                if not is_transient or attempt >= self.max_retries:
                    break

                # Audit P1-1: before resending on a transient/connection error,
                # check whether a PRIOR attempt actually landed at the broker but
                # its reply was lost. If so, adopt that fill (idempotent) instead
                # of sending a duplicate order.
                adopted = self._adopt_lost_response(request)
                if adopted is not None:
                    self._clear_pending(request.idempotency_key)
                    set_order(
                        request.idempotency_key,
                        OrderState.POSITION_CONFIRMED,
                        {
                            "ticket": adopted.ticket,
                            "adopted": True,
                            "symbol": request.symbol,
                            "volume": request.volume,
                            "magic": request.magic,
                            **self._identity_fields(request),
                            "broker_order_ticket": adopted.ticket,
                            "broker_deal_ticket": adopted.ticket,
                            "broker_position_ticket": adopted.ticket,
                        },
                    )
                    self._completed_orders[request.idempotency_key] = adopted
                    logger.warning(
                        "Adopted a landed order for idempotency key %s (retry avoided "
                        "to prevent a duplicate position).",
                        request.idempotency_key,
                    )
                    return adopted

                retries += 1
                backoff = self.retry_delay * (2 ** (attempt))
                logger.info(
                    "Transient error (%s, code=%s). Retrying %d/%d after %.2fs...",
                    last_error_message,
                    last_error_code,
                    retries,
                    self.max_retries,
                    backoff,
                )
                time.sleep(backoff)

            # Execution attempts exhausted
            self._clear_pending(request.idempotency_key)
            failure_result = ExecutionResult(
                success=False,
                ticket=None,
                error_code=last_error_code,
                error_message=last_error_message,
                retries=retries,
                position_opened=None,
            )
            self._completed_orders[request.idempotency_key] = failure_result
            self._record_execution_quality(request, actual_fill=0.0, rejected=True)
            logger.error(
                "Order execution failed permanently after %d retries: %s",
                retries,
                last_error_message,
            )
            return failure_result

        finally:
            self._clear_pending(request.idempotency_key)

    # ---------------------------------------------------------------------------
    # Confirmation & Reconciliation API
    # ---------------------------------------------------------------------------

    def confirm_execution(self, ticket: Optional[int]) -> bool:
        """Verify that an order was filled and exists as an active MT5 position or deal.

        Args:
            ticket: Order or deal ticket number.

        Returns:
            True if position/ticket was confirmed in MT5, False otherwise.
        """
        if ticket is None or ticket <= 0:
            return False

        # Query all active positions from MT5 / connector
        positions = self._get_all_positions()
        for pos in positions:
            pos_ticket = (
                pos.get("ticket") if isinstance(pos, dict) else getattr(pos, "ticket", None)
            )
            if pos_ticket == ticket:
                return True

        # Check direct positions_get(ticket=ticket) if supported
        if self.mt5_connector is not None:
            if hasattr(self.mt5_connector, "positions_get"):
                try:
                    res = self.mt5_connector.positions_get(ticket=ticket)
                    if res:
                        return True
                except Exception:
                    pass

        # Also fallback to native MetaTrader5 module if available
        try:
            import MetaTrader5 as mt5

            pos = mt5.positions_get(ticket=ticket)
            if pos and len(pos) > 0:
                return True
        except (ImportError, Exception):
            pass

        return False

    def sync_position(self, symbol: str) -> dict[str, Any]:
        """Synchronize and reconcile current active MT5 positions for a symbol.

        Args:
            symbol: Financial instrument symbol.

        Returns:
            Dict summarizing positions count, total volume, buy/sell volumes,
            net volume, unrealized PnL, and individual position records.
        """
        sym_clean = self._resolve_symbol(symbol) if symbol else ""
        positions = self._get_all_positions()

        matching_positions: list[dict[str, Any]] = []
        total_volume = 0.0
        buy_volume = 0.0
        sell_volume = 0.0
        total_profit = 0.0
        weighted_price_sum = 0.0

        for pos in positions:
            pos_dict = self._normalize_position(pos)
            if pos_dict.get("symbol", "").upper() == sym_clean:
                matching_positions.append(pos_dict)
                vol = float(pos_dict.get("volume", 0.0))
                total_volume += vol
                side = str(pos_dict.get("side", "")).upper()
                if "BUY" in side:
                    buy_volume += vol
                elif "SELL" in side:
                    sell_volume += vol

                profit = float(pos_dict.get("profit", 0.0))
                total_profit += profit
                price_open = float(pos_dict.get("price_open", 0.0))
                weighted_price_sum += price_open * vol

        avg_price = (weighted_price_sum / total_volume) if total_volume > 0 else 0.0

        return {
            "symbol": sym_clean,
            "positions_count": len(matching_positions),
            "total_volume": round(total_volume, 4),
            "buy_volume": round(buy_volume, 4),
            "sell_volume": round(sell_volume, 4),
            "net_volume": round(buy_volume - sell_volume, 4),
            "unrealized_pnl": round(total_profit, 2),
            "average_price": round(avg_price, 5),
            "positions": matching_positions,
            "synced_at": datetime.now(timezone.utc).isoformat(),
        }

    # ---------------------------------------------------------------------------
    # Internal Helpers
    # ---------------------------------------------------------------------------

    def _adopt_lost_response(self, request: OrderRequest) -> Optional[ExecutionResult]:
        """Try to adopt an order that landed despite a lost reply (audit P1-1).

        Consults the injected ``order_locator`` (a callable that searches the
        broker for a matching order/position). When a match is found, returns a
        successful :class:`ExecutionResult` carrying the found ticket so the
        caller stops retrying and never sends a duplicate.

        Returns ``None`` when no locator is configured, the locator errors, or
        no matching order is found (i.e. the retry should proceed normally).
        """
        if self.order_locator is None:
            return None
        try:
            found = self.order_locator(request)
        except Exception as exc:  # noqa: BLE001 - locator must never break retry
            logger.warning("Order locator failed (retry proceeds): %s", exc)
            return None
        if not found:
            return None
        ticket = found.get("ticket") if isinstance(found, dict) else getattr(found, "ticket", None)
        return ExecutionResult(
            success=True,
            ticket=int(ticket) if ticket is not None else None,
            error_code=0,
            error_message="",
            retries=0,
            position_opened=self.sync_position(request.symbol),
        )

    def _get_armed_terminal_ids(self) -> list[str]:
        """Return the terminal ids explicitly armed by the operator (B-9).

        A native ``mt5.order_send`` is a real broker order, so it must be gated
        by the operator arm switch. In the multi-terminal model each terminal
        carries its own arm flag; ``mt5.terminals.get_armed_terminals()``
        returns the ids that are armed AND eligible (config ``execution: true``
        AND running). Fail-closed: any doubt → empty list.

        Both import paths are checked because the FastAPI app imports
        ``src.mt5`` while tests import ``mt5``.
        """
        for mod_name in ("mt5.terminals", "src.mt5.terminals"):
            try:
                import importlib

                terms = importlib.import_module(mod_name)
                return list(terms.get_armed_terminals())
            except ImportError:
                continue
            except Exception as exc:  # noqa: BLE001 - any doubt → stay blocked
                logger.warning("Armed-terminal check failed (blocked): %s", exc)
                return []
        return []

    def _native_execution_armed(self) -> bool:
        """Return True only when an armed terminal IS the attached binding.

        The MetaTrader5 binding is process-wide: a native ``order_send`` lands
        on whichever terminal the binding is attached to. An armed terminal
        that is NOT attached can never receive the order, so the gate stays
        fail-closed until the attached terminal is itself armed and eligible
        (``mt5.terminals.execution_permitted``). Any doubt → False. Both import
        paths are checked because the FastAPI app imports ``src.mt5`` while
        tests import ``mt5``.
        """
        for mod_name in ("mt5.terminals", "src.mt5.terminals"):
            try:
                import importlib

                terms = importlib.import_module(mod_name)
                return bool(terms.execution_permitted())
            except ImportError:
                continue
            except Exception as exc:  # noqa: BLE001 - any doubt → stay blocked
                logger.warning("Execution arm check failed (blocked): %s", exc)
                return False
        return False

    def modify_position_sltp(
        self,
        ticket: int,
        symbol: str,
        sl: float,
        tp: Optional[float] = None,
    ) -> dict[str, Any]:
        """Modify an existing position's SL (and optionally TP) at the broker.

        SAFETY (audit B-7 parity): a native ``mt5.order_send`` with
        ``TRADE_ACTION_SLTP`` changes a REAL position, so it is gated by the
        operator arm switch exactly like opening orders — fail-closed when no
        eligible terminal is armed/attached. In simulation mode (or when native
        MT5 is unavailable) this returns an honest ``simulated`` result and
        never touches a broker.

        Args:
            ticket: The position ticket to modify.
            symbol: Instrument symbol (required by the MT5 modify payload).
            sl: The new stop-loss price.
            tp: Optional new take-profit price (kept unchanged when None).

        Returns:
            dict with ``success`` (bool), ``error_code`` (int), ``message``,
            ``reason``/``simulated`` metadata. Never raises.
        """
        if not ticket or ticket <= 0:
            return {"success": False, "error_code": 400, "message": "Invalid ticket"}
        if sl <= 0:
            return {"success": False, "error_code": 400, "message": "Invalid SL price"}

        # Simulation / no native library → labelled no-op (never fabricate a
        # broker modification).
        try:
            import MetaTrader5 as mt5
        except ImportError:
            logger.info(
                "SLTP modify (simulated): ticket=%s %s -> SL=%.5f",
                ticket,
                symbol,
                sl,
            )
            return {
                "success": True,
                "simulated": True,
                "error_code": 0,
                "message": "Simulated SLTP modification (no native MT5)",
                "sl": sl,
                "tp": tp,
            }

        if not self._native_execution_armed():
            logger.warning(
                "SLTP modify blocked: no armed/attached terminal (fail-closed) " "for ticket=%s",
                ticket,
            )
            return {
                "success": False,
                "error_code": 403,
                "message": "EXECUTION NOT ARMED — SLTP modification disabled.",
            }

        try:
            payload: dict[str, Any] = {
                "action": mt5.TRADE_ACTION_SLTP,
                "symbol": symbol,
                "position": ticket,
                "sl": sl,
            }
            if tp is not None and tp > 0:
                payload["tp"] = tp
            res = mt5.order_send(payload)
            parsed = self._parse_send_result(res)
            return {
                "success": bool(parsed.get("success")),
                "error_code": int(parsed.get("error_code", -1) or 0),
                "message": str(parsed.get("message", "") or ""),
                "sl": sl,
                "tp": tp,
            }
        except Exception as exc:  # noqa: BLE001 - never fabricate success
            logger.warning("Native MT5 SLTP modify raised: %s", exc)
            return {
                "success": False,
                "error_code": -1,
                "message": f"Native MT5 SLTP modify failed: {exc}",
            }

    def execute_order_fanout(
        self,
        request: OrderRequest,
        *,
        targets: Optional[list[dict[str, Any]]] = None,
        risk_price: float = 0.0,
        tp_price: float = 0.0,
    ) -> FanoutResult:
        """Dispatch ONE decision to EVERY armed fan-out terminal (F1).

        The MetaTrader5 binding is process-wide (one terminal per process), so
        this RE-ATTACHES to each target terminal in turn, resolves that
        terminal's own symbol name, recomputes the absolute entry/SL/TP from the
        decision's *distances* against that terminal's live price, sizes the lot
        from that account's equity, and sends the order. The binding is restored
        to the originally attached terminal in a ``finally`` (fail-safe).

        Safety:
        - Fail-closed when ``require_approval`` is set and no token is present.
        - Only targets returned by ``mt5.terminals.get_fanout_targets`` (running
          + ``execution:true`` + armed) are eligible; the caller passes them in
          (or they are resolved here when ``targets`` is None).
        - Simulation mode never touches a broker (a per-terminal simulated fill).
        - Partial failure is allowed: one terminal failing never aborts the
          others; the outcome is recorded per terminal.

        Args:
            request: The base order (symbol, order_type, volume as fallback,
                magic, comment, approval_token).
            targets: Pre-resolved fan-out target entries. When None, they are
                read from ``mt5.terminals.get_fanout_targets()``.
            risk_price: SL distance in PRICE units from entry (0 = none). Used to
                compute each terminal's absolute SL from its own entry price.
            tp_price: TP distance in PRICE units from entry (0 = none).

        Returns:
            :class:`FanoutResult` with one result row per target.
        """
        # Audit B-3 parity: the fan-out is a real-money dispatch surface.
        if self.require_approval and not getattr(request, "approval_token", None):
            msg = (
                "Fan-out rejected: require_approval is enabled but the order "
                "carries no gate-issued approval_token (fail-closed)."
            )
            logger.warning(msg)
            return FanoutResult(
                results=[
                    {
                        "terminal_id": None,
                        "success": False,
                        "error_code": 403,
                        "error_message": msg,
                    }
                ],
                succeeded=0,
                failed=1,
                target_count=0,
            )

        if targets is None:
            targets = self._get_fanout_targets()
        if not targets:
            logger.warning("Fan-out: no armed/eligible terminals to dispatch to.")
            return FanoutResult(results=[], succeeded=0, failed=0, target_count=0)

        # Simulation mode (or no native MT5): one simulated fill per terminal.
        try:
            import MetaTrader5 as mt5  # noqa: F401
        except ImportError:
            if self.simulation_mode:
                out = FanoutResult(target_count=len(targets))
                for t in targets:
                    out.results.append(
                        {
                            "terminal_id": t.get("id"),
                            "label": t.get("label"),
                            "symbol": request.symbol,
                            "volume": request.volume,
                            "success": True,
                            "ticket": self._next_simulated_ticket(),
                            "error_code": 0,
                            "error_message": "Simulated fan-out fill",
                            "price": request.price or 0.0,
                            "simulated": True,
                        }
                    )
                    out.succeeded += 1
                return out
            return FanoutResult(
                results=[{"success": False, "error_message": "No MT5 and simulation off"}],
                succeeded=0,
                failed=len(targets),
                target_count=len(targets),
            )

        from mt5 import connector  # local import: avoid hard dependency at import time

        original_path = self._current_attached_path()
        out = FanoutResult(target_count=len(targets))
        try:
            for t in targets:
                row = self._dispatch_to_terminal(t, request, risk_price, tp_price)
                out.results.append(row)
                if row.get("success"):
                    out.succeeded += 1
                else:
                    out.failed += 1
        finally:
            # ALWAYS restore the binding to where it was (fail-safe).
            try:
                connector.shutdown()
                if original_path:
                    connector.use_live_data_mode(path=original_path)
            except Exception as exc:  # noqa: BLE001 - restore is best-effort
                logger.warning("Fan-out: could not restore binding: %s", exc)
        return out

    def _dispatch_to_terminal(
        self,
        target: dict[str, Any],
        request: OrderRequest,
        risk_price: float,
        tp_price: float,
    ) -> dict[str, Any]:
        """Re-attach to ONE terminal and send the (re-priced) order.

        Never raises: any error becomes a failed row so the fan-out continues.
        """
        tid = target.get("id")
        row: dict[str, Any] = {
            "terminal_id": tid,
            "label": target.get("label") or tid,
            "symbol": request.symbol,
            "volume": request.volume,
            "success": False,
            "ticket": None,
            "error_code": -1,
            "error_message": "",
            "price": None,
        }
        try:
            import MetaTrader5 as mt5

            from mt5 import connector
            from mt5.symbol_resolver import clear_symbol_cache, resolve_symbol

            path = target.get("path")
            # Re-attach the process-wide binding to THIS terminal.
            connector.shutdown()
            if not connector.use_live_data_mode(path=path):
                row["error_message"] = f"Gagal attach ke terminal '{tid}'."
                return row
            clear_symbol_cache()

            # Resolve the broker's symbol name for this terminal (XAUUSD → XAUUSDc).
            symbol = resolve_symbol(request.symbol) or request.symbol
            row["symbol"] = symbol

            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                row["error_message"] = f"Tidak ada tick untuk simbol '{symbol}'."
                return row
            entry = float(tick.ask if request.order_type.upper() == "BUY" else tick.bid)

            sign = 1.0 if request.order_type.upper() == "BUY" else -1.0
            sl = entry - sign * risk_price if risk_price and risk_price > 0 else 0.0
            tp = entry + sign * tp_price if tp_price and tp_price > 0 else 0.0
            row["price"] = entry

            volume = self._size_for_terminal(
                target, entry, risk_price, symbol, fallback_volume=request.volume
            )
            row["volume"] = volume
            if volume <= 0:
                row["error_message"] = "Volume lot tidak valid (0)."
                return row

            payload = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": float(volume),
                "type": (
                    mt5.ORDER_TYPE_BUY
                    if request.order_type.upper() == "BUY"
                    else mt5.ORDER_TYPE_SELL
                ),
                "price": entry,
                "sl": float(sl) if sl else 0.0,
                "tp": float(tp) if tp else 0.0,
                "magic": request.magic,
                "comment": request.comment,
                "type_time": mt5.ORDER_TIME_GTC,
            }
            res = mt5.order_send(payload)
            parsed = self._parse_send_result(res)
            row["success"] = bool(parsed.get("success"))
            row["ticket"] = parsed.get("ticket")
            row["error_code"] = int(parsed.get("error_code", 0) or 0)
            row["error_message"] = str(parsed.get("message", "") or "")
            return row
        except Exception as exc:  # noqa: BLE001 - one failure must not stop others
            logger.warning("Fan-out dispatch to %s failed: %s", tid, exc)
            row["error_message"] = str(exc)[:200]
            return row

    def _size_for_terminal(
        self,
        target: dict[str, Any],
        entry: float,
        risk_price: float,
        symbol: str = "",
        fallback_volume: float = 0.0,
    ) -> float:
        """Size the lot for ONE terminal from its account equity (F1/F3).

        Priority: ``fixed_lot`` (explicit) → ``risk_per_trade_pct`` of the
        terminal's equity given the SL distance → signal volume
        (``fallback_volume``) when the terminal has no sizing configured
        (B-10: auto-detected/running terminals without config must still trade
        the signal lot). Always clamped to
        ``[min_volume, max_lot_per_trade or max_volume]`` + normalized to
        ``volume_step``.
        """
        fixed = target.get("fixed_lot")
        max_lot = target.get("max_lot_per_trade") or self.max_volume
        try:
            if fixed and float(fixed) > 0:
                vol = float(fixed)
            else:
                risk_pct = target.get("risk_per_trade_pct")
                if risk_pct and float(risk_pct) > 0 and risk_price and risk_price > 0:
                    import MetaTrader5 as mt5

                    info = mt5.account_info()
                    equity = float(getattr(info, "equity", 0.0) or 0.0) if info else 0.0
                    if equity > 0:
                        risk_money = equity * float(risk_pct) / 100.0
                        # lot ≈ risk_money / (loss per lot at the SL distance).
                        sym = mt5.symbol_info(symbol or "")
                        tick_value = (
                            float(getattr(sym, "trade_tick_value", 0.0) or 0.0) if sym else 0.0
                        )
                        tick_size = (
                            float(getattr(sym, "trade_tick_size", 0.0) or 0.0) if sym else 0.0
                        )
                        if tick_value > 0 and tick_size > 0:
                            risk_per_lot = risk_price / tick_size * tick_value
                            vol = risk_money / risk_per_lot if risk_per_lot > 0 else 0.0
                        else:
                            vol = 0.0
                    else:
                        vol = 0.0
                else:
                    # No sizing configured → fall back to the signal volume
                    # (B-10: auto-detected/running terminals without config).
                    vol = float(fallback_volume or 0.0)
            if vol <= 0:
                return 0.0
            # Clamp to broker volume constraints.
            vol = max(float(self.min_volume), min(float(vol), float(max_lot)))
            try:
                sym = mt5.symbol_info(symbol or "")
                step = float(getattr(sym, "volume_step", 0.0) or 0.0) if sym else 0.0
                vmin = float(getattr(sym, "volume_min", 0.0) or 0.0) if sym else 0.0
                if vmin > 0:
                    vol = max(vol, vmin)
                if step and step > 0:
                    vol = round(vol / step) * step
                    # Guard: rounding could drop below the broker minimum.
                    if vmin > 0 and vol < vmin:
                        vol = vmin
            except Exception:  # noqa: BLE001 - clamping is best-effort
                pass
            return round(vol, 4)
        except Exception:  # noqa: BLE001 - sizing must never raise
            return 0.0

    def _current_attached_path(self) -> Optional[str]:
        """Return the folder of the currently attached terminal (or None)."""
        try:
            import MetaTrader5 as mt5

            info = mt5.terminal_info()
            path = getattr(info, "path", None) if info else None
            return str(path) if path else None
        except Exception:  # noqa: BLE001 - best-effort
            return None

    def _get_fanout_targets(self) -> list[dict[str, Any]]:
        """Return armed+eligible fan-out targets (fail-closed to empty)."""
        for mod_name in ("mt5.terminals", "src.mt5.terminals"):
            try:
                import importlib

                terms = importlib.import_module(mod_name)
                return list(terms.get_fanout_targets())
            except ImportError:
                continue
            except Exception as exc:  # noqa: BLE001 - any doubt → blocked
                logger.warning("Fan-out target lookup failed (blocked): %s", exc)
                return []
        return []

    def _is_transient_error(self, code: int, message: str) -> bool:
        """Determine if an error code or message represents a transient failure.

        Args:
            code: Numeric error code.
            message: Error description string.

        Returns:
            True if the error is transient and retryable.
        """
        if code in TRANSIENT_RETCODES:
            return True

        msg_lower = (message or "").lower()
        return any(kw in msg_lower for kw in TRANSIENT_KEYWORDS)

    def _send_to_mt5(self, request: OrderRequest) -> dict[str, Any]:
        """Send order request payload to the MT5 connector or module.

        Args:
            request: Order request to transmit.

        Returns:
            Normalized dict with success, ticket, error_code, message keys.
        """
        # 1. Custom connector method dispatch
        if self.mt5_connector is not None:
            # Check for order_send
            if hasattr(self.mt5_connector, "order_send"):
                req_payload = {
                    "symbol": request.symbol,
                    "volume": request.volume,
                    "order_type": request.order_type,
                    "price": request.price,
                    "sl": request.sl,
                    "tp": request.tp,
                    "magic": request.magic,
                    "comment": request.comment,
                }
                res = self.mt5_connector.order_send(req_payload)
                return self._parse_send_result(res)

            # Check for execute_order
            if hasattr(self.mt5_connector, "execute_order"):
                req_payload = {
                    "symbol": request.symbol,
                    "side": "BUY" if "BUY" in request.order_type.upper() else "SELL",
                    "order_type": request.order_type,
                    "quantity": request.volume,
                    "price": request.price,
                    "sl": request.sl,
                    "tp": request.tp,
                    "comment": request.comment,
                }
                res = self.mt5_connector.execute_order(req_payload)
                return self._parse_send_result(res)

        # 2. Explicit simulation is selected before probing native MT5. The
        # approval-enforced runtime still reaches the native safety guard so an
        # unarmed terminal cannot be mistaken for a paper fill.
        if self.simulation_mode and not self.require_approval:
            logger.info(
                "ExecutionEngine in simulation_mode — returning a labelled "
                "SIMULATED fill for %s %s.",
                request.symbol,
                request.order_type,
            )
            return {
                "success": True,
                "ticket": self._next_simulated_ticket(),
                "error_code": 0,
                "message": "Simulated order execution successful",
                "price": request.price,
                "simulated": True,
            }

        # 2. MetaTrader5 native library integration
        # SAFETY: a native ``mt5.order_send`` is a REAL broker order. It must
        # NEVER be called unless the operator has explicitly ARMED a valid
        # execution terminal via the dashboard — regardless of whether the
        # connector is attached in read-only live-data mode. This closes the hole
        # where an importable ``MetaTrader5`` (a real terminal present) let the
        # engine call ``order_send`` without the arm gate or ``initialize()`` —
        # which returned ``None`` → a confusing ``error_code=0``.
        # Fail-closed: any doubt (module missing, no selection, not running, not
        # attached, not execution-enabled) keeps real orders blocked.
        try:
            import MetaTrader5 as mt5
        except ImportError:
            # Native MetaTrader5 is genuinely unavailable (no terminal). This is
            # NOT a broker error — fall through to the simulation/honest-failure
            # decision below (audit P0-2).
            logger.debug("Native MT5 library not available; no live broker path.")
        else:
            armed_ids = self._get_armed_terminal_ids()
            if not self._native_execution_armed():
                logger.warning(
                    "Execution blocked: no armed MT5 execution terminal — native "
                    "order_send is disabled (fail-closed). Armed terminal ids: %s",
                    armed_ids,
                )
                return {
                    "success": False,
                    "ticket": None,
                    "error_code": 403,
                    "message": (
                        "EXECUTION NOT ARMED — no operator-armed terminal; native "
                        "order_send is disabled."
                    ),
                    "price": None,
                }
            # Log which terminal(s) are armed (Phase 1: order goes to the first
            # armed terminal, which is also the attached binding; Phase 2 will
            # loop multiple armed terminals).
            if armed_ids:
                logger.info(
                    "Executing order on armed terminal(s): %s (attached binding receives order)",
                    armed_ids,
                )
            try:
                order_type_mt5 = (
                    mt5.ORDER_TYPE_BUY
                    if request.order_type.upper() == "BUY"
                    else mt5.ORDER_TYPE_SELL
                )
                price = request.price
                if price <= 0:
                    tick = mt5.symbol_info_tick(request.symbol)
                    if tick:
                        price = tick.ask if request.order_type.upper() == "BUY" else tick.bid

                payload = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": request.symbol,
                    "volume": request.volume,
                    "type": order_type_mt5,
                    "price": price,
                    "sl": request.sl,
                    "tp": request.tp,
                    "magic": request.magic,
                    "comment": request.comment,
                    "type_time": mt5.ORDER_TIME_GTC,
                }
                res = mt5.order_send(payload)
                return self._parse_send_result(res)
            except Exception as exc:
                # The native send was attempted AND raised. NEVER fabricate
                # success here: report the real failure so the caller/risk layer
                # sees it.
                logger.warning("Native MT5 order_send raised: %s", exc)
                return {
                    "success": False,
                    "ticket": None,
                    "error_code": -1,
                    "message": f"Native MT5 send failed: {exc}",
                    "price": None,
                }

        # 3. No live broker path. Simulation is EXPLICIT opt-in only; default is
        # an honest failure with no fabricated ticket (audit P0-2).
        if self.simulation_mode:
            logger.info(
                "ExecutionEngine in simulation_mode — returning a labelled "
                "SIMULATED fill for %s %s.",
                request.symbol,
                request.order_type,
            )
            return {
                "success": True,
                "ticket": self._next_simulated_ticket(),
                "error_code": 0,
                "message": "Simulated order execution successful",
                "price": request.price or 1.0850,
                "simulated": True,
            }

        logger.error(
            "No broker path available and simulation_mode is off — refusing to "
            "fabricate a fill for %s %s.",
            request.symbol,
            request.order_type,
        )
        return {
            "success": False,
            "ticket": None,
            "error_code": 1,
            "message": (
                "No live MT5 connection and simulation_mode is disabled — order "
                "not sent (no fabricated fill)."
            ),
            "price": None,
            "simulated": False,
        }

    def _parse_send_result(self, res: Any) -> dict[str, Any]:
        """Normalize various MT5 connector return formats into a consistent response structure.

        Args:
            res: Raw result from order_send or execute_order.

        Returns:
            Normalized dictionary with success, ticket, error_code, and message.
        """
        if isinstance(res, dict):
            success = bool(res.get("success", False))
            ticket = res.get("ticket") or res.get("order_id") or res.get("order")
            retcode = res.get("retcode") or res.get("error_code")
            if retcode is None:
                retcode = 0 if success else 1
            return {
                "success": success,
                "ticket": int(ticket) if ticket is not None else None,
                "error_code": int(retcode),
                "message": res.get("message") or res.get("comment", ""),
                "price": res.get("price"),
            }

        # MetaTrader5 OrderSendResult object
        retcode = getattr(res, "retcode", None)
        comment = getattr(res, "comment", "")
        order = getattr(res, "order", getattr(res, "deal", None))

        # MT5 TRADE_RETCODE_DONE = 10009
        is_done = retcode == 10009 or (retcode == 0 and order is not None)
        return {
            "success": is_done,
            "ticket": int(order) if order else None,
            "error_code": int(retcode or 0) if not is_done else 0,
            "message": comment,
            "price": getattr(res, "price", None),
        }

    @staticmethod
    def _get_field(source: Any, name: str, default: Any = None) -> Any:
        """Read a field from a dict or object."""
        if isinstance(source, dict):
            return source.get(name, default)
        return getattr(source, name, default)

    def _has_symbol_lookup(self) -> bool:
        """Return whether the configured connector can verify available symbols."""
        if self.mt5_connector is None:
            return False
        return any(
            hasattr(self.mt5_connector, method)
            for method in ("get_symbol_info", "symbol_info", "get_symbols")
        )

    def _resolve_symbol(self, symbol: str) -> str:
        """Resolve a base symbol to the broker's actual name (audit P3-3).

        Uses ``mt5.symbol_resolver.resolve_symbol`` so a base like ``XAUUSD``
        maps to the broker's ``XAUUSDc`` (and vice-versa). Fail-safe: returns the
        upper-cased input unchanged when resolution is unavailable.
        """
        clean = (symbol or "").strip().upper()
        if not clean:
            return clean
        for mod_name in ("mt5.symbol_resolver", "src.mt5.symbol_resolver"):
            try:
                import importlib

                resolved = importlib.import_module(mod_name).resolve_symbol(clean)
                if resolved:
                    return str(resolved).upper()
            except ImportError:
                continue
            except Exception:  # noqa: BLE001 - resolution is best-effort
                break
        return clean

    def _get_symbol_info(self, symbol: str) -> Any:
        """Fetch symbol metadata from connector or MT5."""
        if self.mt5_connector is not None:
            if hasattr(self.mt5_connector, "get_symbol_info"):
                return self.mt5_connector.get_symbol_info(symbol)
            if hasattr(self.mt5_connector, "symbol_info"):
                return self.mt5_connector.symbol_info(symbol)
            if hasattr(self.mt5_connector, "get_symbols"):
                symbols = self.mt5_connector.get_symbols()
                for s in symbols:
                    name = getattr(s, "symbol", s) if not isinstance(s, dict) else s.get("symbol")
                    if str(name).upper() == symbol.upper():
                        return s

        try:
            import MetaTrader5 as mt5

            return mt5.symbol_info(symbol)
        except (ImportError, Exception):
            return None

    def _get_current_tick(self, symbol: str) -> Any:
        """Fetch current tick for symbol from connector or MT5."""
        if self.mt5_connector is not None:
            if hasattr(self.mt5_connector, "get_tick"):
                return self.mt5_connector.get_tick(symbol)
            if hasattr(self.mt5_connector, "symbol_info_tick"):
                return self.mt5_connector.symbol_info_tick(symbol)

        try:
            import MetaTrader5 as mt5

            return mt5.symbol_info_tick(symbol)
        except (ImportError, Exception):
            return None

    def _get_all_positions(self) -> list[Any]:
        """Fetch all active positions from connector or MT5."""
        if self.mt5_connector is not None:
            if hasattr(self.mt5_connector, "positions"):
                try:
                    return self.mt5_connector.positions()
                except Exception:
                    pass
            if hasattr(self.mt5_connector, "get_positions"):
                try:
                    return self.mt5_connector.get_positions()
                except Exception:
                    pass

        try:
            import MetaTrader5 as mt5

            res = mt5.positions_get()
            return list(res) if res is not None else []
        except (ImportError, Exception):
            return []

    def _normalize_position(self, pos: Any) -> dict[str, Any]:
        """Convert a position object or dictionary into a normalized dictionary."""
        if isinstance(pos, dict):
            return {
                "ticket": pos.get("ticket", 0),
                "symbol": pos.get("symbol", ""),
                "side": pos.get("side") or pos.get("type", "BUY"),
                "volume": pos.get("volume") or pos.get("quantity", 0.0),
                "price_open": pos.get("price_open", 0.0),
                "price_current": pos.get("price_current", 0.0),
                "profit": pos.get("profit", 0.0),
                "sl": pos.get("sl", 0.0),
                "tp": pos.get("tp", 0.0),
            }

        return {
            "ticket": getattr(pos, "ticket", 0),
            "symbol": getattr(pos, "symbol", ""),
            "side": getattr(pos, "side", "BUY" if getattr(pos, "type", 0) == 0 else "SELL"),
            "volume": getattr(pos, "volume", getattr(pos, "quantity", 0.0)),
            "price_open": getattr(pos, "price_open", 0.0),
            "price_current": getattr(pos, "price_current", 0.0),
            "profit": getattr(pos, "profit", 0.0),
            "sl": getattr(pos, "sl", 0.0),
            "tp": getattr(pos, "tp", 0.0),
        }
