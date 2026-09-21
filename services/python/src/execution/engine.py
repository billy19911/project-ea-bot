# -*- coding: utf-8 -*-
"""Execution Engine — order validation, sending, confirmation, retry, and duplicate prevention.

Phase 14 deterministic trading engine component for MetaTrader 5 order execution.
"""

from __future__ import annotations

import logging
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

    # ---------------------------------------------------------------------------
    # Duplicate Prevention API
    # ---------------------------------------------------------------------------

    def _is_duplicate(self, idempotency_key: str) -> bool:
        """Check if an order with the given idempotency key is already pending or completed.

        Args:
            idempotency_key: Order uniqueness key.

        Returns:
            True if key exists in pending or completed order registries.
        """
        if not idempotency_key:
            return False
        return idempotency_key in self._pending_orders or idempotency_key in self._completed_orders

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
                    send_res = self._send_to_mt5(request)
                    if send_res.get("success"):
                        ticket = send_res.get("ticket")
                        set_order(request.idempotency_key, OrderState.SUBMITTED, {"ticket": ticket})
                        set_order(request.idempotency_key, OrderState.ACKNOWLEDGED)
                        confirmed = self.confirm_execution(ticket)
                        if confirmed:
                            set_order(request.idempotency_key, OrderState.FILLED)
                            set_order(request.idempotency_key, OrderState.POSITION_CONFIRMED)

                        # Sync position state after execution
                        pos_summary = self.sync_position(request.symbol)

                        # Cleanup and final state handling
                        self._clear_pending(request.idempotency_key)
                        # If unknown state after retries, keep as UNKNOWN for later query
                        final_state = get_order(request.idempotency_key).get("state")
                        if final_state == OrderState.UNKNOWN.value:
                            set_order(request.idempotency_key, OrderState.UNKNOWN)
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
                        {"ticket": adopted.ticket, "adopted": True},
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

        # 2. MetaTrader5 native library integration
        # SAFETY: never send real orders when the connector is attached to a
        # running terminal in read-only live-data mode (see mt5.connector).
        # Check both import paths — the FastAPI app imports ``src.mt5`` while
        # tests import ``mt5``, and they are distinct module instances.
        _live_data_block = False
        for _mod_name in ("mt5.connector", "src.mt5.connector"):
            try:
                import importlib

                _conn = importlib.import_module(_mod_name)
                if _conn.is_live_mode():
                    _live_data_block = True
                    break
            except ImportError:
                continue

        if _live_data_block:
            # Run 24: live mode is read-only UNLESS the operator explicitly
            # armed a valid execution terminal via the dashboard. Fail-closed:
            # any doubt (no selection, not running, not attached, not
            # execution-enabled) keeps real orders blocked.
            _armed = False
            for _mod_name in ("mt5.terminals", "src.mt5.terminals"):
                try:
                    import importlib

                    _terms = importlib.import_module(_mod_name)
                    if _terms.execution_permitted():
                        _armed = True
                        break
                except ImportError:
                    continue

            if not _armed:
                logger.warning(
                    "Execution blocked: MT5 live-data (read-only) mode is active — "
                    "native order_send is disabled."
                )
                return {
                    "success": False,
                    "ticket": None,
                    "error_code": 1,
                    "message": "LIVE DATA MODE (read-only) — order execution disabled.",
                    "price": None,
                }

        try:
            import MetaTrader5 as mt5

            order_type_mt5 = (
                mt5.ORDER_TYPE_BUY if request.order_type.upper() == "BUY" else mt5.ORDER_TYPE_SELL
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

        except ImportError:
            # Native MetaTrader5 is genuinely unavailable (no terminal). This is
            # NOT a broker error — fall through to the simulation/honest-failure
            # decision below.
            logger.debug("Native MT5 library not available; no live broker path.")
        except Exception as exc:
            # The native send was attempted AND raised. NEVER fabricate success
            # here: report the real failure so the caller/risk layer sees it.
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
                "ticket": int(time.time() * 1000) % 1_000_000,
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
