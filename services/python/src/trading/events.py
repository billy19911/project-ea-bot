# -*- coding: utf-8 -*-
"""Event Detection Engine — detects market regime and technical events.

Designed for autonomous multi-agent trading systems with no LLM usage.
Uses a class-based design (EventDetector) with all imports at module level.

Backward-compatible wrapper functions ``detect_events`` and
``update_market_state`` are provided at module level for callers
that import them directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional

from fastapi import APIRouter

from .indicators import adx, atr, bollinger_bands, ema, macd, rsi, stochastic

if TYPE_CHECKING:  # Avoid circular import at runtime; see EventDetector.
    from .event_engine import EventDeduplicator, EventHistory, EventQueue

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class EventTypes(Enum):
    """Enumeration of detectable market events.

    These events feed into the AI Agent Framework (registry + supervisor)
    and the Risk Gate for safety validation before any order execution.
    """

    # --- Regime / trend events ---
    TREND_BULLISH = "TREND_BULLISH"
    TREND_BEARISH = "TREND_BEARISH"
    TREND_NEUTRAL = "TREND_NEUTRAL"
    TREND_STRENGTHENING = "TREND_STRENGTHENING"
    TREND_WEAKENING = "TREND_WEAKENING"

    # --- Momentum events ---
    MOMENTUM_BULLISH = "MOMENTUM_BULLISH"
    MOMENTUM_BEARISH = "MOMENTUM_BEARISH"
    MOMENTUM_DIVERGENCE = "MOMENTUM_DIVERGENCE"

    # --- Volatility events ---
    VOLATILITY_EXPANDING = "VOLATILITY_EXPANDING"
    VOLATILITY_CONTRACTING = "VOLATILITY_CONTRACTING"
    VOLATILITY_SPIKE = "VOLATILITY_SPIKE"

    # --- Price action events ---
    BREAKOUT = "BREAKOUT"
    BREAKDOWN = "BREAKDOWN"
    REVERSAL = "REVERSAL"
    DOJI = "DOJI"
    GAP_UP = "GAP_UP"
    GAP_DOWN = "GAP_DOWN"

    # --- Indicator crossover events ---
    EMA_CROSSOVER = "EMA_CROSSOVER"
    MACD_CROSSOVER = "MACD_CROSSOVER"
    RSI_OVERBOUGHT = "RSI_OVERBOUGHT"
    RSI_OVERSOLD = "RSI_OVERSOLD"
    STOCH_OVERBOUGHT = "STOCH_OVERBOUGHT"
    STOCH_OVERSOLD = "STOCH_OVERSOLD"

    # --- Risk events ---
    DRAWDOWN_WARNING = "DRAWDOWN_WARNING"
    EXPOSURE_LIMIT_REACHED = "EXPOSURE_LIMIT_REACHED"
    LIQUIDITY_WARNING = "LIQUIDITY_WARNING"

    # --- Lifecycle / risk-monitor events ---
    # Produced as dict payloads by the position-close detector
    # (orchestration/runtime) and the risk monitor (risk/monitor). The
    # supervisor routes TRADE_CLOSE to ReviewLead and RISK_* to RiskLead.
    TRADE_CLOSE = "TRADE_CLOSE"
    RISK_DRAWDOWN = "RISK_DRAWDOWN"
    RISK_EXPOSURE = "RISK_EXPOSURE"
    RISK_MARGIN = "RISK_MARGIN"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class MarketState:
    """Persistent market state tracked across bars.

    Used as *prev_state* input to :meth:`EventDetector.detect` to compare
    current bar against the previous bar's state.
    """

    symbol: str = ""
    timestamp: Optional[str] = None
    close: float = 0.0
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    volume: float = 0.0
    trend_direction: Optional[str] = None  # "BULLISH","BEARISH","NEUTRAL"
    trend_strength: float = 0.0
    volatility_regime: Optional[str] = None
    volatility_value: float = 0.0
    BB_width: float = 0.0
    ema_fast: Optional[float] = None
    ema_slow: Optional[float] = None
    rsi: Optional[float] = None
    macd_histogram: Optional[float] = None
    atr: Optional[float] = None
    adx_value: Optional[float] = None
    stoch_k: Optional[float] = None
    stoch_d: Optional[float] = None
    prev_event_types: list[EventTypes] = field(default_factory=list)


@dataclass
class DetectedEvent:
    """A single detected event with metadata."""

    event_type: EventTypes
    severity: float  # 0.0-1.0
    description: str
    timestamp: str
    symbol: str = ""
    #: Market evidence captured when the event was detected (close/high/low
    #: series, computed market state, volatility inputs), attached by the
    #: market feed loop so downstream analysis runs on real data. Optional and
    #: backward compatible — defaults to an empty snapshot.
    market_snapshot: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# EventDetector — class-based entry point
# ---------------------------------------------------------------------------


class EventDetector:
    """Detects market events from OHLCV data.

    Phase 5 adds optional EventQueue, EventHistory, and EventDeduplicator.
    If provided, detected events are deduplicated, prioritized, enqueued,
    and stored in history.
    """

    def __init__(
        self,
        deduplicator: "EventDeduplicator | None" = None,
        queue: "EventQueue | None" = None,
        history: "EventHistory | None" = None,
    ) -> None:
        """Create a detector with optional extensions.

        Args:
            deduplicator: Instance handling duplicate suppression.
            queue: In‑memory priority queue for emitted events.
            history: Persistent in‑memory history store.
        """
        self._deduplicator = deduplicator
        self._queue = queue
        self._history = history

    def _process_and_route(self, events: list[DetectedEvent], symbol: str) -> None:
        """Apply deduplication, queue, and history to a list of events.

        This helper is synchronous because the underlying queue/history are
        thread‑safe (no asyncio required). The detector itself remains sync.
        """
        for ev in events:
            emit = True
            # Deduplication based on bar index – approximate with event count
            if self._deduplicator is not None:
                # Use global counter per detector instance.
                emit = self._deduplicator.should_emit(
                    symbol, ev.event_type, getattr(ev, "_bar_index", 0)
                )
            if not emit:
                continue
            if self._queue is not None:
                self._queue.enqueue(ev)
            if self._history is not None:
                self._history.add(ev)

    def detect(
        self,
        ohlcv: list[dict],
        prev_state: Optional[MarketState] = None,
    ) -> list[DetectedEvent]:
        """Detect market events from OHLCV data.

        Args:
            ohlcv: OHLCV dicts with keys: open, high, low, close, volume
                (oldest → newest).
            prev_state: Previous MarketState from the prior bar.

        Returns:
            List of DetectedEvent instances.
        """
        if not ohlcv:
            return []

        bar = ohlcv[-1]
        closes = [b["close"] for b in ohlcv]
        highs = [b["high"] for b in ohlcv]
        lows = [b["low"] for b in ohlcv]

        events: list[DetectedEvent] = []
        ts = datetime.now(timezone.utc).isoformat()
        symbol = bar.get("symbol", "")

        # --- Indicator calculations ---
        ema_fast_val = ema(closes, 9)
        ema_slow_val = ema(closes, 21)
        rsi_val = rsi(closes, 14)
        macd_hist = self._compute_macd_histogram(closes)
        adx_val = adx(highs, lows, closes, 14)
        bb = bollinger_bands(closes, 20, 2.0)
        stoch_result = stochastic(highs, lows, closes, 14, 3)

        # --- Regime: trend direction ---
        if ema_fast_val is not None and ema_slow_val is not None:
            if ema_fast_val > ema_slow_val:
                diff_pct = (ema_fast_val - ema_slow_val) / ema_slow_val
                sev = min(0.5 + diff_pct * 0.5, 1.0)
                desc = (
                    f"EMA bullish: fast={ema_fast_val:.2f}"
                    f" > slow={ema_slow_val:.2f}"
                )
                events.append(
                    DetectedEvent(
                        event_type=EventTypes.TREND_BULLISH,
                        severity=sev,
                        description=desc,
                        timestamp=ts,
                        symbol=symbol,
                    )
                )
            elif ema_fast_val < ema_slow_val:
                diff_pct = (ema_slow_val - ema_fast_val) / ema_fast_val
                sev = min(0.5 + diff_pct * 0.5, 1.0)
                desc = (
                    f"EMA bearish: fast={ema_fast_val:.2f}"
                    f" < slow={ema_slow_val:.2f}"
                )
                events.append(
                    DetectedEvent(
                        event_type=EventTypes.TREND_BEARISH,
                        severity=sev,
                        description=desc,
                        timestamp=ts,
                        symbol=symbol,
                    )
                )
            else:
                events.append(
                    DetectedEvent(
                        event_type=EventTypes.TREND_NEUTRAL,
                        severity=0.3,
                        description="EMA crossover neutral",
                        timestamp=ts,
                        symbol=symbol,
                    )
                )

        # --- Trend strengthening / weakening (ADX-based) ---
        adx_cond = (
            adx_val is not None
            and prev_state is not None
            and prev_state.adx_value is not None
        )
        if adx_cond:
            if adx_val > prev_state.adx_value + 2.0:  # type: ignore
                sev = min((adx_val - prev_state.adx_value) / 10.0, 1.0)  # type: ignore
                desc = (
                    f"ADX strengthening:"
                    f" {prev_state.adx_value:.1f}"  # type: ignore
                    f" -> {adx_val:.1f}"
                )
                events.append(
                    DetectedEvent(
                        event_type=EventTypes.TREND_STRENGTHENING,
                        severity=sev,
                        description=desc,
                        timestamp=ts,
                        symbol=symbol,
                    )
                )
            elif adx_val < prev_state.adx_value - 2.0:  # type: ignore
                sev = min((prev_state.adx_value - adx_val) / 10.0, 1.0)  # type: ignore
                desc = (
                    f"ADX weakening:"
                    f" {prev_state.adx_value:.1f}"  # type: ignore
                    f" -> {adx_val:.1f}"
                )
                events.append(
                    DetectedEvent(
                        event_type=EventTypes.TREND_WEAKENING,
                        severity=sev,
                        description=desc,
                        timestamp=ts,
                        symbol=symbol,
                    )
                )

        # --- Momentum: MACD ---
        if macd_hist is not None:
            ref = max(ema_fast_val or 1.0, 0.01)
            if macd_hist > 0:
                sev = min(macd_hist / ref * 0.1, 1.0)
                events.append(
                    DetectedEvent(
                        event_type=EventTypes.MOMENTUM_BULLISH,
                        severity=sev,
                        description=f"MACD bullish histogram: {macd_hist:.4f}",
                        timestamp=ts,
                        symbol=symbol,
                    )
                )
            elif macd_hist < 0:
                sev = min(abs(macd_hist) / ref * 0.1, 1.0)
                events.append(
                    DetectedEvent(
                        event_type=EventTypes.MOMENTUM_BEARISH,
                        severity=sev,
                        description=f"MACD bearish histogram: {macd_hist:.4f}",
                        timestamp=ts,
                        symbol=symbol,
                    )
                )

        # --- RSI events ---
        if rsi_val is not None:
            if rsi_val >= 70.0:
                sev = min((rsi_val - 70.0) / 30.0, 1.0)
                events.append(
                    DetectedEvent(
                        event_type=EventTypes.RSI_OVERBOUGHT,
                        severity=sev,
                        description=f"RSI overbought: {rsi_val:.1f}",
                        timestamp=ts,
                        symbol=symbol,
                    )
                )
            elif rsi_val <= 30.0:
                sev = min((30.0 - rsi_val) / 30.0, 1.0)
                events.append(
                    DetectedEvent(
                        event_type=EventTypes.RSI_OVERSOLD,
                        severity=sev,
                        description=f"RSI oversold: {rsi_val:.1f}",
                        timestamp=ts,
                        symbol=symbol,
                    )
                )

        # --- Stochastic events ---
        if stoch_result is not None:
            if stoch_result.k >= 80.0:
                sev = min((stoch_result.k - 80.0) / 20.0, 1.0)
                desc = f"Stochastic overbought: %K={stoch_result.k:.1f}"
                events.append(
                    DetectedEvent(
                        event_type=EventTypes.STOCH_OVERBOUGHT,
                        severity=sev,
                        description=desc,
                        timestamp=ts,
                        symbol=symbol,
                    )
                )
            elif stoch_result.k <= 20.0:
                sev = min((20.0 - stoch_result.k) / 20.0, 1.0)
                desc = f"Stochastic oversold: %K={stoch_result.k:.1f}"
                events.append(
                    DetectedEvent(
                        event_type=EventTypes.STOCH_OVERSOLD,
                        severity=sev,
                        description=desc,
                        timestamp=ts,
                        symbol=symbol,
                    )
                )

        # --- Breakout / breakdown via Bollinger Bands ---
        if bb is not None:
            bb_upper = bb.upper
            bb_lower = bb.lower
            bb_middle = bb.middle
            close_price = bar["close"]

            if prev_state is not None:
                prev_close = prev_state.close
                if close_price > bb_upper and prev_close <= bb_upper:
                    sev = min((close_price - bb_upper) / bb_upper, 1.0)
                    desc = (
                        f"Price broke above BB upper:"
                        f" {close_price:.2f} > {bb_upper:.2f}"
                    )
                    events.append(
                        DetectedEvent(
                            event_type=EventTypes.BREAKOUT,
                            severity=sev,
                            description=desc,
                            timestamp=ts,
                            symbol=symbol,
                        )
                    )
                if close_price < bb_lower and prev_close >= bb_lower:
                    sev = min((bb_lower - close_price) / bb_lower, 1.0)
                    desc = (
                        f"Price broke below BB lower:"
                        f" {close_price:.2f} < {bb_lower:.2f}"
                    )
                    events.append(
                        DetectedEvent(
                            event_type=EventTypes.BREAKDOWN,
                            severity=sev,
                            description=desc,
                            timestamp=ts,
                            symbol=symbol,
                        )
                    )

            # Reversal detection
            if prev_state is not None and prev_state.close is not None:
                prev_c = prev_state.close
                if prev_c > bb_upper and close_price < bb_middle:
                    desc = (
                        f"Reversal from upper band:"
                        f" {prev_c:.2f} -> {close_price:.2f}"
                    )
                    events.append(
                        DetectedEvent(
                            event_type=EventTypes.REVERSAL,
                            severity=0.7,
                            description=desc,
                            timestamp=ts,
                            symbol=symbol,
                        )
                    )
                elif prev_c < bb_lower and close_price > bb_middle:
                    desc = (
                        f"Reversal from lower band:"
                        f" {prev_c:.2f} -> {close_price:.2f}"
                    )
                    events.append(
                        DetectedEvent(
                            event_type=EventTypes.REVERSAL,
                            severity=0.7,
                            description=desc,
                            timestamp=ts,
                            symbol=symbol,
                        )
                    )

            # Volatility expansion / contraction
            bb_width = (bb.upper - bb.lower) / bb_middle if bb_middle > 0 else 0.0
            if prev_state is not None and prev_state.BB_width > 0:
                if bb_width > prev_state.BB_width * 1.2:
                    sev = min(
                        (bb_width - prev_state.BB_width) / prev_state.BB_width,
                        1.0,
                    )
                    desc = (
                        f"BB width expanding:"
                        f" {prev_state.BB_width:.3f}"
                        f" -> {bb_width:.3f}"
                    )
                    events.append(
                        DetectedEvent(
                            event_type=EventTypes.VOLATILITY_EXPANDING,
                            severity=sev,
                            description=desc,
                            timestamp=ts,
                            symbol=symbol,
                        )
                    )
                elif bb_width < prev_state.BB_width * 0.8:
                    sev = min(
                        (prev_state.BB_width - bb_width) / prev_state.BB_width,
                        1.0,
                    )
                    desc = (
                        f"BB width contracting:"
                        f" {prev_state.BB_width:.3f}"
                        f" -> {bb_width:.3f}"
                    )
                    events.append(
                        DetectedEvent(
                            event_type=EventTypes.VOLATILITY_CONTRACTING,
                            severity=sev,
                            description=desc,
                            timestamp=ts,
                            symbol=symbol,
                        )
                    )

        # --- Doji detection ---
        body = abs(bar["close"] - bar["open"])
        range_val = bar["high"] - bar["low"]
        if range_val > 0 and body / range_val < 0.1:
            ratio = body / range_val
            events.append(
                DetectedEvent(
                    event_type=EventTypes.DOJI,
                    severity=0.4,
                    description=f"Doji candle: body/range={ratio:.2f}",
                    timestamp=ts,
                    symbol=symbol,
                )
            )

        # --- Gap detection ---
        pc = prev_state
        if pc is not None and pc.close is not None and pc.close > 0:
            gap = (bar["open"] - pc.close) / pc.close
            if gap > 0.005:
                pct = gap * 100
                desc = f"Gap up: {pct:.2f}%" f" ({pc.close:.2f} -> {bar['open']:.2f})"
                events.append(
                    DetectedEvent(
                        event_type=EventTypes.GAP_UP,
                        severity=min(pct, 1.0),
                        description=desc,
                        timestamp=ts,
                        symbol=symbol,
                    )
                )
            elif gap < -0.005:
                pct = abs(gap) * 100
                desc = f"Gap down: {pct:.2f}%" f" ({pc.close:.2f} -> {bar['open']:.2f})"
                events.append(
                    DetectedEvent(
                        event_type=EventTypes.GAP_DOWN,
                        severity=min(pct, 1.0),
                        description=desc,
                        timestamp=ts,
                        symbol=symbol,
                    )
                )

        # --- EMA crossover event ---
        if (
            pc is not None
            and pc.ema_fast is not None
            and pc.ema_slow is not None
            and ema_fast_val is not None
            and ema_slow_val is not None
        ):
            if pc.ema_fast <= pc.ema_slow and ema_fast_val > ema_slow_val:
                desc = (
                    f"EMA crossover: fast crossed above slow"
                    f" ({pc.ema_fast:.2f}->{ema_fast_val:.2f})"
                )
                events.append(
                    DetectedEvent(
                        event_type=EventTypes.EMA_CROSSOVER,
                        severity=0.8,
                        description=desc,
                        timestamp=ts,
                        symbol=symbol,
                    )
                )
            elif pc.ema_fast >= pc.ema_slow and ema_fast_val < ema_slow_val:
                desc = (
                    f"EMA crossover: fast crossed below slow"
                    f" ({pc.ema_fast:.2f}->{ema_fast_val:.2f})"
                )
                events.append(
                    DetectedEvent(
                        event_type=EventTypes.EMA_CROSSOVER,
                        severity=0.8,
                        description=desc,
                        timestamp=ts,
                        symbol=symbol,
                    )
                )

        # After detection, route via optional queue/history/dedup
        if hasattr(self, "_process_and_route"):
            self._process_and_route(events, symbol)
        return events

    def update_state(
        self,
        ohlcv: list[dict],
        prev_state: Optional[MarketState] = None,
    ) -> MarketState:
        """Compute and return the updated MarketState for the latest bar.

        Args:
            ohlcv: OHLCV data (oldest -> newest).
            prev_state: Previous market state (optional).

        Returns:
            New MarketState reflecting the latest bar's indicator values.
        """
        if not ohlcv:
            return MarketState()

        bar = ohlcv[-1]
        closes = [b["close"] for b in ohlcv]
        highs = [b["high"] for b in ohlcv]
        lows = [b["low"] for b in ohlcv]

        ema_fast_val = ema(closes, 9)
        ema_slow_val = ema(closes, 21)
        rsi_val = rsi(closes, 14)
        macd_hist = self._compute_macd_histogram(closes)
        atr_val = atr(highs, lows, closes, 14)
        adx_val = adx(highs, lows, closes, 14)
        bb = bollinger_bands(closes, 20, 2.0)
        stoch_result = stochastic(highs, lows, closes, 14, 3)

        # Trend direction
        trend_direction = None
        trend_strength = 0.0
        if ema_fast_val is not None and ema_slow_val is not None:
            denom = ema_slow_val if ema_slow_val > 0 else 1.0
            diff = abs(ema_fast_val - ema_slow_val) / denom
            trend_strength = min(diff, 1.0)
            if ema_fast_val > ema_slow_val:
                trend_direction = "BULLISH"
            elif ema_fast_val < ema_slow_val:
                trend_direction = "BEARISH"
            else:
                trend_direction = "NEUTRAL"

        # Volatility regime
        volatility_regime = "NORMAL"
        volatility_value = atr_val or 0.0
        bb_width = 0.0
        if bb is not None and bb.middle > 0:
            bb_width = (bb.upper - bb.lower) / bb.middle
            if bb_width > 0.10:
                volatility_regime = "EXPANDING"
            elif bb_width < 0.03:
                volatility_regime = "CONTRACTING"

        return MarketState(
            symbol=bar.get("symbol", ""),
            timestamp=bar.get("time", datetime.now(timezone.utc).isoformat()),
            close=bar["close"],
            open=bar["open"],
            high=bar["high"],
            low=bar["low"],
            volume=bar.get("volume", 0.0),
            trend_direction=trend_direction,
            trend_strength=trend_strength,
            volatility_regime=volatility_regime,
            volatility_value=volatility_value,
            BB_width=bb_width,
            ema_fast=ema_fast_val,
            ema_slow=ema_slow_val,
            rsi=rsi_val,
            macd_histogram=macd_hist,
            atr=atr_val,
            adx_value=adx_val,
            stoch_k=stoch_result.k if stoch_result else None,
            stoch_d=stoch_result.d if stoch_result else None,
            prev_event_types=[],
        )

    @staticmethod
    def _compute_macd_histogram(
        closes: list[float],
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9,
    ) -> Optional[float]:
        """Helper: latest MACD histogram value."""
        res = macd(closes, fast_period, slow_period, signal_period)
        if res is None:
            return None
        return res.histogram


# ---------------------------------------------------------------------------
# Backward-compatible wrapper functions
# ---------------------------------------------------------------------------

_detector = EventDetector()


def detect_events(
    ohlcv: list[dict],
    prev_state: Optional[MarketState] = None,
) -> list[DetectedEvent]:
    """Detect market events from OHLCV data.

    Backward-compatible wrapper — delegates to ``EventDetector().detect()``.
    """
    return _detector.detect(ohlcv, prev_state)


def update_market_state(
    ohlcv: list[dict],
    prev_state: Optional[MarketState] = None,
) -> MarketState:
    """Compute and return the updated MarketState for the latest bar.

    Backward-compatible wrapper — delegates to
    ``EventDetector().update_state()``.
    """
    return _detector.update_state(ohlcv, prev_state)


# ---------------------------------------------------------------------------
# FastAPI router for event detection
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/events", tags=["event-detection"])


@router.post(
    "/detect",
    summary="Detect market events from OHLCV data",
)
async def detect_market_events(ohlcv: list[dict]):
    """Detect events from OHLCV data and return them with state."""
    prev_state = None
    events = detect_events(ohlcv, prev_state)
    state = update_market_state(ohlcv, prev_state)

    return {
        "success": True,
        "events": [
            {
                "type": e.event_type.value,
                "severity": e.severity,
                "description": e.description,
                "timestamp": e.timestamp,
                "symbol": e.symbol,
            }
            for e in events
        ],
        "market_state": {
            "symbol": state.symbol,
            "trend_direction": state.trend_direction,
            "trend_strength": state.trend_strength,
            "volatility_regime": state.volatility_regime,
            "volatility_value": state.volatility_value,
            "BB_width": state.BB_width,
            "close": state.close,
            "rsi": state.rsi,
            "macd_histogram": state.macd_histogram,
            "atr": state.atr,
            "adx": state.adx_value,
            "timestamp": state.timestamp,
        },
    }


@router.post(
    "/state",
    summary="Update and return market state",
)
async def get_market_state(ohlcv: list[dict]):
    """Compute and return the current market state from OHLCV data."""
    state = update_market_state(ohlcv)
    return {
        "success": True,
        "market_state": {
            "symbol": state.symbol,
            "trend_direction": state.trend_direction,
            "trend_strength": state.trend_strength,
            "volatility_regime": state.volatility_regime,
            "volatility_value": state.volatility_value,
            "BB_width": state.BB_width,
            "close": state.close,
            "open": state.open,
            "high": state.high,
            "low": state.low,
            "volume": state.volume,
            "rsi": state.rsi,
            "macd_histogram": state.macd_histogram,
            "atr": state.atr,
            "adx": state.adx_value,
            "stoch_k": state.stoch_k,
            "stoch_d": state.stoch_d,
            "ema_fast": state.ema_fast,
            "ema_slow": state.ema_slow,
            "timestamp": state.timestamp,
        },
    }
