# -*- coding: utf-8 -*-
"""Position Monitor — real-time position monitoring, SL/TP management, trailing, abnormal detection.

Phase 15 component for continuous position oversight in MetaTrader 5 trading.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from mt5.connector import get_ohlc, get_positions, get_tick

logger = logging.getLogger(__name__)


class Side(str, Enum):
    """Position side enumeration."""

    BUY = "BUY"
    SELL = "SELL"


class EventType(str, Enum):
    """Abnormal event type enumeration."""

    PRICE_SPIKE = "PRICE_SPIKE"
    VOLUME_SURGE = "VOLUME_SURGE"
    SLIPPAGE = "SLIPPAGE"
    GAP = "GAP"
    NEWS_FLASH = "NEWS_FLASH"
    RISK_BREACH = "RISK_BREACH"
    MARGIN_CALL = "MARGIN_CALL"
    # Audit P2-2: external position changes detected by diffing snapshots.
    SL_CHANGED = "SL_CHANGED"
    TP_CHANGED = "TP_CHANGED"
    PARTIAL_CLOSE = "PARTIAL_CLOSE"
    POSITION_DISAPPEARED = "POSITION_DISAPPEARED"


class Severity(str, Enum):
    """Event severity levels."""

    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass
class PositionSnapshot:
    """Real-time snapshot of an open position.

    Attributes:
        symbol: Trading symbol (e.g., "EURUSD").
        side: Position direction (BUY/SELL).
        volume: Position lot volume.
        entry_price: Original entry price.
        current_price: Latest market price.
        pnl: Unrealized profit/loss in account currency.
        pnl_pct: PnL as percentage of position value.
        sl: Current stop loss price (0.0 if not set).
        tp: Current take profit price (0.0 if not set).
        margin: Margin used by position.
        swap: Accumulated swap charges.
        ticket: MT5 position ticket number.
        timestamp: Snapshot capture time (UTC).
    """

    symbol: str
    side: Side
    volume: float
    entry_price: float
    current_price: float
    pnl: float
    pnl_pct: float
    sl: float
    tp: float
    margin: float
    swap: float
    ticket: int
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "symbol": self.symbol,
            "side": self.side.value,
            "volume": self.volume,
            "entry_price": self.entry_price,
            "current_price": self.current_price,
            "pnl": self.pnl,
            "pnl_pct": self.pnl_pct,
            "sl": self.sl,
            "tp": self.tp,
            "margin": self.margin,
            "swap": self.swap,
            "ticket": self.ticket,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class AbnormalEvent:
    """Detected abnormal market or position event.

    Attributes:
        event_type: Category of abnormal event.
        severity: Severity level.
        message: Human-readable description.
        symbol: Affected trading symbol.
        timestamp: Event detection time (UTC).
        metadata: Additional context (e.g., ATR value, price change).
    """

    event_type: EventType
    severity: Severity
    message: str
    symbol: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "event_type": self.event_type.value,
            "severity": self.severity.value,
            "message": self.message,
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
        }


class PositionMonitor:
    """Real-time position monitor with SL/TP management, trailing, and abnormal detection.

    Monitors open positions every tick via MT5 connector. Provides:
    - Dynamic SL/TP updates (breakeven, trailing)
    - Abnormal movement detection (>3x ATR threshold)
    - Risk threshold breach detection
    - Exit event generation for TP/SL hits, abnormal events, risk breaches

    Args:
        mt5_connector: MT5 connector instance or module providing get_positions, get_tick, get_ohlc.
        atr_lookback: Period for ATR calculation (default 14).
    """

    def __init__(
        self,
        mt5_connector: Any = None,
        atr_lookback: int = 14,
        close_detector: Any = None,
        default_contract_size: float = 100000.0,
    ) -> None:
        """Initialize the Position Monitor.

        Args:
            mt5_connector: Object exposing get_positions(), get_tick(symbol),
                          get_ohlc(symbol, timeframe, count). Defaults to mt5.connector.
            atr_lookback: Number of bars for ATR calculation.
            close_detector: Optional object exposing ``observe(positions) -> list``
                (audit P1-6). When supplied, ``monitor_all_positions`` feeds the
                raw positions to it so disappeared tickets trigger trade review.
                Optional so existing callers are unaffected.
            default_contract_size: Fallback contract size used only when the
                broker symbol spec cannot be read (audit P2-7). Overridable so
                non-FX instruments are not mis-scaled.
        """
        self.mt5_connector = mt5_connector
        self.atr_lookback = max(1, atr_lookback)
        self.close_detector = close_detector
        self.default_contract_size = float(default_contract_size)

        # In-memory state tracking
        self._position_history: dict[int, list[PositionSnapshot]] = {}
        self._last_sl: dict[int, float] = {}
        self._last_tp: dict[int, float] = {}
        self._last_volume: dict[int, float] = {}
        self._entry_prices: dict[int, float] = {}
        self._breakeven_applied: set[int] = set()

    # -------------------------------------------------------------------------
    # Internal Helpers
    # -------------------------------------------------------------------------

    def _get_positions(self) -> list[Any]:
        """Fetch positions from connector."""
        if self.mt5_connector is not None:
            if hasattr(self.mt5_connector, "get_positions"):
                return self.mt5_connector.get_positions()
            if hasattr(self.mt5_connector, "positions"):
                try:
                    return self.mt5_connector.positions()
                except Exception:
                    pass
        return get_positions()

    def _get_tick(self, symbol: str) -> Any:
        """Fetch current tick for symbol."""
        if self.mt5_connector is not None:
            if hasattr(self.mt5_connector, "get_tick"):
                return self.mt5_connector.get_tick(symbol)
            if hasattr(self.mt5_connector, "symbol_info_tick"):
                return self.mt5_connector.symbol_info_tick(symbol)
        return get_tick(symbol)

    def _get_ohlc(self, symbol: str, timeframe: str = "H1", count: int = 100) -> list[Any]:
        """Fetch OHLC bars for ATR calculation."""
        if self.mt5_connector is not None:
            if hasattr(self.mt5_connector, "get_ohlc"):
                return self.mt5_connector.get_ohlc(symbol, timeframe, count)
        return get_ohlc(symbol, timeframe, count)

    def _calculate_atr(self, symbol: str, timeframe: str = "H1") -> float:
        """Calculate Average True Range for a symbol.

        Args:
            symbol: Trading symbol.
            timeframe: Timeframe for ATR (default H1).

        Returns:
            ATR value, or 0.0 if insufficient data.
        """
        bars = self._get_ohlc(symbol, timeframe, self.atr_lookback + 1)
        if not bars or len(bars) < 2:
            return 0.0

        true_ranges: list[float] = []
        prev_close = None

        for bar in bars:
            high = getattr(bar, "high", 0.0)
            low = getattr(bar, "low", 0.0)
            close = getattr(bar, "close", 0.0)

            if prev_close is not None:
                tr = max(
                    high - low,
                    abs(high - prev_close),
                    abs(low - prev_close),
                )
                true_ranges.append(tr)
            prev_close = close

        if not true_ranges:
            return 0.0

        return sum(true_ranges[-self.atr_lookback :]) / min(len(true_ranges), self.atr_lookback)

    def _to_side(self, side_str: str) -> Side:
        """Normalize side string to Side enum."""
        s = (side_str or "").strip().upper()
        if "SELL" in s:
            return Side.SELL
        return Side.BUY

    def _normalize_position(self, pos: Any) -> PositionSnapshot:
        """Convert raw position to PositionSnapshot."""
        ticket = getattr(pos, "ticket", 0) if not isinstance(pos, dict) else pos.get("ticket", 0)
        symbol = getattr(pos, "symbol", "") if not isinstance(pos, dict) else pos.get("symbol", "")
        side_raw = (
            getattr(pos, "side", "BUY")
            if not isinstance(pos, dict)
            else pos.get("side") or pos.get("type", "BUY")
        )
        side = self._to_side(str(side_raw))

        vol_val = (
            getattr(pos, "volume", 0.0) if not isinstance(pos, dict) else pos.get("volume", 0.0)
        )
        volume = float(vol_val)

        p_open = (
            getattr(pos, "price_open", 0.0)
            if not isinstance(pos, dict)
            else pos.get("price_open", 0.0)
        )
        entry_price = float(p_open)

        p_curr = (
            getattr(pos, "price_current", 0.0)
            if not isinstance(pos, dict)
            else pos.get("price_current", 0.0)
        )
        current_price = float(p_curr)

        profit = (
            getattr(pos, "profit", 0.0) if not isinstance(pos, dict) else pos.get("profit", 0.0)
        )
        unrealized = (
            getattr(pos, "unrealized_pnl", 0.0)
            if not isinstance(pos, dict)
            else pos.get("unrealized_pnl", 0.0)
        )
        pnl = float(profit or unrealized)

        margin = float(
            getattr(pos, "margin", 0.0) if not isinstance(pos, dict) else pos.get("margin", 0.0)
        )
        swap = float(
            getattr(pos, "swap", 0.0) if not isinstance(pos, dict) else pos.get("swap", 0.0)
        )
        # Schema reports None when no level is placed; PositionSnapshot keeps
        # its documented 0.0-if-unset convention for its stop/target logic.
        sl = float(
            (getattr(pos, "sl", 0.0) if not isinstance(pos, dict) else pos.get("sl", 0.0)) or 0.0
        )
        tp = float(
            (getattr(pos, "tp", 0.0) if not isinstance(pos, dict) else pos.get("tp", 0.0)) or 0.0
        )

        # Calculate PnL percentage
        position_value = entry_price * volume
        pnl_pct = (pnl / position_value * 100.0) if position_value > 0 else 0.0

        # Track entry price for breakeven logic
        if ticket and ticket not in self._entry_prices:
            self._entry_prices[ticket] = entry_price

        return PositionSnapshot(
            symbol=symbol,
            side=side,
            volume=volume,
            entry_price=entry_price,
            current_price=current_price,
            pnl=pnl,
            pnl_pct=pnl_pct,
            sl=sl,
            tp=tp,
            margin=margin,
            swap=swap,
            ticket=ticket,
        )

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def monitor_position(self, symbol: str) -> Optional[PositionSnapshot]:
        """Get real-time snapshot for a specific symbol's open position.

        Args:
            symbol: Trading symbol to monitor.

        Returns:
            PositionSnapshot if position exists, None otherwise.
        """
        positions = self._get_positions()
        sym = symbol.strip().upper()

        for pos in positions:
            pos_symbol = (
                getattr(pos, "symbol", "").upper()
                if not isinstance(pos, dict)
                else str(pos.get("symbol", "")).upper()
            )
            if pos_symbol == sym:
                return self._normalize_position(pos)
        return None

    def monitor_all_positions(self, account_id: Optional[int] = None) -> list[PositionSnapshot]:
        """Get snapshots of all open positions.

        Args:
            account_id: Optional account filter (not used in current implementation).

        Returns:
            List of PositionSnapshot for all open positions.
        """
        positions = self._get_positions()

        # Audit P1-6: feed the raw positions to the close detector so a ticket
        # that disappeared since the last snapshot triggers trade review (the
        # live trade → review → learning path). Fail-safe: never break the loop.
        if self.close_detector is not None:
            try:
                self.close_detector.observe(positions)
            except Exception as exc:  # noqa: BLE001 - observation is best-effort
                logger.warning("Close detector failed: %s", exc)

        snapshots: list[PositionSnapshot] = []

        for pos in positions:
            snapshot = self._normalize_position(pos)
            snapshots.append(snapshot)

            # Store history for trend analysis
            ticket = snapshot.ticket
            if ticket not in self._position_history:
                self._position_history[ticket] = []
            self._position_history[ticket].append(snapshot)
            # Keep last 100 snapshots
            if len(self._position_history[ticket]) > 100:
                self._position_history[ticket] = self._position_history[ticket][-100:]

        return snapshots

    def _snapshot_positions(self) -> list[PositionSnapshot]:
        """Build snapshots + history WITHOUT feeding the close detector.

        Internal helper for callers that already handled position-close
        observation (e.g. :meth:`detect_position_changes`), so a single cycle
        never double-fires the close detector.
        """
        snapshots: list[PositionSnapshot] = []
        for pos in self._get_positions():
            snapshot = self._normalize_position(pos)
            snapshots.append(snapshot)
            ticket = snapshot.ticket
            if ticket not in self._position_history:
                self._position_history[ticket] = []
            self._position_history[ticket].append(snapshot)
            if len(self._position_history[ticket]) > 100:
                self._position_history[ticket] = self._position_history[ticket][-100:]
        return snapshots

    def detect_position_changes(self, account_id: Optional[int] = None) -> list[AbnormalEvent]:
        """Diff the current positions against the last-seen state (audit P2-2).

        Detects changes the system did not make itself:
        - **external SL modification** (broker/manual change) → ``SL_CHANGED``
        - **external TP modification** → ``TP_CHANGED``
        - **partial close** (volume decreased) → ``PARTIAL_CLOSE``
        - **unexpected disappearance** (ticket gone) → ``POSITION_DISAPPEARED``

        The state maps are updated to the current snapshot so each change is
        reported once. Read-only: it never modifies SL/TP or closes anything.
        """
        events: list[AbnormalEvent] = []
        snapshots = self._snapshot_positions()
        seen: set[int] = set()

        for snap in snapshots:
            ticket = snap.ticket
            if not ticket:
                continue
            seen.add(ticket)
            prev_sl = self._last_sl.get(ticket)
            prev_tp = self._last_tp.get(ticket)
            prev_vol = self._last_volume.get(ticket)

            if prev_sl is not None and snap.sl != prev_sl:
                events.append(
                    AbnormalEvent(
                        event_type=EventType.SL_CHANGED,
                        severity=Severity.WARNING,
                        message=(
                            f"Stop loss changed on {snap.symbol} #{ticket}: "
                            f"{prev_sl} → {snap.sl}"
                        ),
                        symbol=snap.symbol,
                        metadata={"ticket": ticket, "old_sl": prev_sl, "new_sl": snap.sl},
                    )
                )
            if prev_tp is not None and snap.tp != prev_tp:
                events.append(
                    AbnormalEvent(
                        event_type=EventType.TP_CHANGED,
                        severity=Severity.WARNING,
                        message=(
                            f"Take profit changed on {snap.symbol} #{ticket}: "
                            f"{prev_tp} → {snap.tp}"
                        ),
                        symbol=snap.symbol,
                        metadata={"ticket": ticket, "old_tp": prev_tp, "new_tp": snap.tp},
                    )
                )
            if prev_vol is not None and snap.volume < prev_vol:
                events.append(
                    AbnormalEvent(
                        event_type=EventType.PARTIAL_CLOSE,
                        severity=Severity.WARNING,
                        message=(
                            f"Partial close on {snap.symbol} #{ticket}: "
                            f"{prev_vol} → {snap.volume}"
                        ),
                        symbol=snap.symbol,
                        metadata={
                            "ticket": ticket,
                            "old_volume": prev_vol,
                            "new_volume": snap.volume,
                        },
                    )
                )

            # Update tracked state.
            self._last_sl[ticket] = snap.sl
            self._last_tp[ticket] = snap.tp
            self._last_volume[ticket] = snap.volume

        # Unexpected disappearance: a tracked ticket that is no longer present.
        for ticket in list(self._last_sl.keys()):
            if ticket not in seen:
                events.append(
                    AbnormalEvent(
                        event_type=EventType.POSITION_DISAPPEARED,
                        severity=Severity.WARNING,
                        message=f"Position #{ticket} disappeared (closed externally?)",
                        symbol="",
                        metadata={"ticket": ticket},
                    )
                )
                self._last_sl.pop(ticket, None)
                self._last_tp.pop(ticket, None)
                self._last_volume.pop(ticket, None)

        return events

    def update_trailing_sl(
        self,
        symbol: str,
        trail_atr_factor: float = 1.5,
        timeframe: str = "H1",
    ) -> Optional[float]:
        """Update stop loss to trail price by ATR factor.

        For BUY: new SL = current_price - (ATR * trail_atr_factor)
        For SELL: new SL = current_price + (ATR * trail_atr_factor)

        Only moves SL in favorable direction (never widens risk).

        Args:
            symbol: Trading symbol.
            trail_atr_factor: ATR multiplier for trail distance (default 1.5).
            timeframe: Timeframe for ATR calculation.

        Returns:
            New SL price if updated, None if no change or no position.
        """
        snapshot = self.monitor_position(symbol)
        if not snapshot:
            return None

        atr = self._calculate_atr(symbol, timeframe)
        if atr <= 0:
            return None

        tick = self._get_tick(symbol)
        if not tick:
            return None

        is_buy = snapshot.side == Side.BUY
        current_price = getattr(tick, "bid", 0.0) if is_buy else getattr(tick, "ask", 0.0)
        if current_price <= 0:
            current_price = snapshot.current_price

        trail_distance = atr * trail_atr_factor
        ticket = snapshot.ticket

        if is_buy:
            new_sl = current_price - trail_distance
            # Only update if new SL is higher (more favorable) than current
            if snapshot.sl <= 0 or new_sl > snapshot.sl:
                if ticket not in self._last_sl or new_sl > self._last_sl[ticket]:
                    self._last_sl[ticket] = new_sl
                    return round(new_sl, 5)
        else:  # SELL
            new_sl = current_price + trail_distance
            # Only update if new SL is lower (more favorable) than current
            if snapshot.sl <= 0 or new_sl < snapshot.sl:
                if ticket not in self._last_sl or new_sl < self._last_sl[ticket]:
                    self._last_sl[ticket] = new_sl
                    return round(new_sl, 5)

        return None

    def update_breakeven_sl(self, symbol: str) -> Optional[float]:
        """Move stop loss to breakeven (entry price) if position is in profit.

        Only applies once per position. Protects initial capital.

        Args:
            symbol: Trading symbol.

        Returns:
            Breakeven SL price if applied, None if already applied or no profit.
        """
        snapshot = self.monitor_position(symbol)
        if not snapshot:
            return None

        ticket = snapshot.ticket
        if ticket in self._breakeven_applied:
            return None

        # Check if position has sufficient profit
        tick = self._get_tick(symbol)
        if not tick:
            return None

        is_buy = snapshot.side == Side.BUY
        current_price = getattr(tick, "bid", 0.0) if is_buy else getattr(tick, "ask", 0.0)
        if current_price <= 0:
            current_price = snapshot.current_price

        entry = self._entry_prices.get(ticket, snapshot.entry_price)

        if is_buy:
            in_profit = current_price > entry
            new_sl = entry
            if in_profit and (snapshot.sl <= 0 or new_sl > snapshot.sl):
                self._breakeven_applied.add(ticket)
                self._last_sl[ticket] = new_sl
                return round(new_sl, 5)
        else:  # SELL
            in_profit = current_price < entry
            new_sl = entry
            if in_profit and (snapshot.sl <= 0 or new_sl < snapshot.sl):
                self._breakeven_applied.add(ticket)
                self._last_sl[ticket] = new_sl
                return round(new_sl, 5)

        return None

    def detect_abnormal_movement(
        self,
        symbol: str,
        atr_threshold: float = 3.0,
        timeframe: str = "M1",
    ) -> Optional[AbnormalEvent]:
        """Detect abnormal price movement exceeding ATR threshold.

        Checks if price moved > atr_threshold * ATR within short timeframe.

        Args:
            symbol: Trading symbol.
            atr_threshold: ATR multiplier threshold (default 3.0).
            timeframe: Timeframe for analysis (default M1 for short-term).

        Returns:
            AbnormalEvent if detected, None otherwise.
        """
        atr = self._calculate_atr(symbol, "H1")  # Use H1 ATR as baseline
        if atr <= 0:
            return None

        tick = self._get_tick(symbol)
        if not tick:
            return None

        current_price = getattr(tick, "bid", 0.0)
        if current_price <= 0:
            return None

        # Get recent M1 bars to measure short-term move
        bars = self._get_ohlc(symbol, timeframe, 20)
        if len(bars) < 2:
            return None

        # Calculate max move from open of first bar to current
        first_open = getattr(bars[0], "open", current_price)
        price_change = abs(current_price - first_open)
        atr_multiple = price_change / atr if atr > 0 else 0

        if atr_multiple >= atr_threshold:
            is_critical = atr_multiple >= atr_threshold * 1.5
            severity = Severity.CRITICAL if is_critical else Severity.WARNING
            return AbnormalEvent(
                event_type=EventType.PRICE_SPIKE,
                severity=severity,
                message=(
                    f"Abnormal price movement detected: {atr_multiple:.1f}x ATR "
                    f"({price_change:.5f} vs ATR {atr:.5f}) on {symbol}"
                ),
                symbol=symbol,
                metadata={
                    "atr": atr,
                    "price_change": price_change,
                    "atr_multiple": round(atr_multiple, 2),
                    "threshold": atr_threshold,
                    "timeframe": timeframe,
                },
            )

        # Check for gap (open vs previous close)
        if len(bars) >= 2:
            prev_close = getattr(bars[1], "close", 0.0)
            if prev_close > 0:
                gap = abs(first_open - prev_close)
                gap_atr_multiple = gap / atr
                if gap_atr_multiple >= atr_threshold:
                    return AbnormalEvent(
                        event_type=EventType.GAP,
                        severity=Severity.WARNING,
                        message=(
                            f"Price gap detected: {gap_atr_multiple:.1f}x ATR "
                            f"({gap:.5f} vs ATR {atr:.5f}) on {symbol}"
                        ),
                        symbol=symbol,
                        metadata={
                            "atr": atr,
                            "gap_size": gap,
                            "atr_multiple": round(gap_atr_multiple, 2),
                            "prev_close": prev_close,
                            "current_open": first_open,
                        },
                    )

        return None

    def check_risk_change(
        self,
        symbol: str,
        max_risk_pct: float = 5.0,
    ) -> tuple[bool, float]:
        """Check if position risk exceeds threshold.

        Calculates risk as potential loss from current price to SL
        as percentage of account equity.

        Args:
            symbol: Trading symbol.
            max_risk_pct: Maximum allowed risk percentage (default 5.0%).

        Returns:
            Tuple of (at_risk: bool, current_risk_pct: float).
        """
        snapshot = self.monitor_position(symbol)
        if not snapshot:
            return (False, 0.0)

        if snapshot.sl <= 0:
            # No SL set — full position at risk
            return (True, 100.0)

        # Calculate risk distance
        if snapshot.side == Side.BUY:
            risk_distance = snapshot.current_price - snapshot.sl
        else:
            risk_distance = snapshot.sl - snapshot.current_price

        if risk_distance <= 0:
            return (False, 0.0)

        # Risk in account currency
        tick = self._get_tick(symbol)
        if not tick:
            return (False, 0.0)

        # Audit P2-7: use the REAL contract size from the broker symbol spec.
        # Fall back to a configurable default (never a silent 100000 baseline).
        contract_size = self._contract_size(symbol)
        if contract_size <= 0:
            return (False, 0.0)

        risk_per_lot = risk_distance * contract_size
        total_risk = risk_per_lot * snapshot.volume

        # Get account equity honestly. If it cannot be read, risk % is UNKNOWN —
        # do not fabricate an equity figure.
        equity = self._account_equity()
        if equity is None or equity <= 0:
            return (False, 0.0)

        risk_pct = total_risk / equity * 100.0
        at_risk = risk_pct > max_risk_pct

        return (at_risk, round(risk_pct, 2))

    def _contract_size(self, symbol: str) -> float:
        """Return the broker contract size for ``symbol`` (audit P2-7).

        Falls back to ``self.default_contract_size`` when the spec is
        unavailable. Never fabricates a fixed 100000.
        """
        try:
            from market.symbol_spec import get_symbol_spec

            spec = get_symbol_spec(symbol) or {}
            value = float(spec.get("contract_size") or 0.0)
            if value > 0:
                return value
        except Exception:  # noqa: BLE001 - spec lookup is best-effort
            logger.debug("Contract size lookup failed for %s", symbol)
        return float(self.default_contract_size)

    def _account_equity(self) -> Optional[float]:
        """Return the real account equity, or ``None`` when unavailable (P2-7)."""
        try:
            if self.mt5_connector is not None and hasattr(self.mt5_connector, "get_account_info"):
                account = self.mt5_connector.get_account_info()
            else:
                from mt5.connector import get_account_info

                account = get_account_info()
            equity = getattr(account, "equity", None) if account is not None else None
            return float(equity) if equity is not None else None
        except Exception:  # noqa: BLE001 - equity read is best-effort
            return None

    def check_exit_events(self, symbol: str) -> list[AbnormalEvent]:
        """Check for exit-triggering events on a position.

        Detects:
        - TP hit
        - SL hit
        - Abnormal movement
        - Risk threshold breach

        Args:
            symbol: Trading symbol.

        Returns:
            List of AbnormalEvent representing exit triggers.
        """
        events: list[AbnormalEvent] = []
        snapshot = self.monitor_position(symbol)

        if not snapshot:
            return events

        tick = self._get_tick(symbol)
        if not tick:
            return events

        bid = getattr(tick, "bid", 0.0)
        ask = getattr(tick, "ask", 0.0)

        # Check TP hit
        if snapshot.tp > 0:
            if snapshot.side == Side.BUY and bid >= snapshot.tp:
                events.append(
                    AbnormalEvent(
                        event_type=EventType.PRICE_SPIKE,
                        severity=Severity.INFO,
                        message=f"Take Profit hit at {snapshot.tp:.5f} on {symbol}",
                        symbol=symbol,
                        metadata={
                            "exit_reason": "TP_HIT",
                            "tp_price": snapshot.tp,
                            "current_bid": bid,
                        },
                    )
                )
            elif snapshot.side == Side.SELL and ask <= snapshot.tp:
                events.append(
                    AbnormalEvent(
                        event_type=EventType.PRICE_SPIKE,
                        severity=Severity.INFO,
                        message=f"Take Profit hit at {snapshot.tp:.5f} on {symbol}",
                        symbol=symbol,
                        metadata={
                            "exit_reason": "TP_HIT",
                            "tp_price": snapshot.tp,
                            "current_ask": ask,
                        },
                    )
                )

        # Check SL hit
        if snapshot.sl > 0:
            if snapshot.side == Side.BUY and bid <= snapshot.sl:
                events.append(
                    AbnormalEvent(
                        event_type=EventType.PRICE_SPIKE,
                        severity=Severity.CRITICAL,
                        message=f"Stop Loss hit at {snapshot.sl:.5f} on {symbol}",
                        symbol=symbol,
                        metadata={
                            "exit_reason": "SL_HIT",
                            "sl_price": snapshot.sl,
                            "current_bid": bid,
                        },
                    )
                )
            elif snapshot.side == Side.SELL and ask >= snapshot.sl:
                events.append(
                    AbnormalEvent(
                        event_type=EventType.PRICE_SPIKE,
                        severity=Severity.CRITICAL,
                        message=f"Stop Loss hit at {snapshot.sl:.5f} on {symbol}",
                        symbol=symbol,
                        metadata={
                            "exit_reason": "SL_HIT",
                            "sl_price": snapshot.sl,
                            "current_ask": ask,
                        },
                    )
                )

        # Check abnormal movement
        abnormal = self.detect_abnormal_movement(symbol)
        if abnormal:
            events.append(abnormal)

        # Check risk breach
        at_risk, risk_pct = self.check_risk_change(symbol)
        if at_risk:
            events.append(
                AbnormalEvent(
                    event_type=EventType.RISK_BREACH,
                    severity=Severity.CRITICAL,
                    message=f"Position risk {risk_pct:.1f}% exceeds threshold on {symbol}",
                    symbol=symbol,
                    metadata={"risk_pct": risk_pct, "exit_reason": "RISK_BREACH"},
                )
            )

        return events
