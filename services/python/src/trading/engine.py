# -*- coding: utf-8 -*-
"""Deterministic Trading Engine — combines indicators, trend detection, and risk metrics.

Designed for autonomous multi-agent trading systems with no LLM usage.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, TypedDict

from .indicators import adx, atr, bollinger_bands, ema, macd, rsi, stochastic
from .position_sizing import atr_position_size, calculate_take_profit
from .risk import max_drawdown, profit_factor, sharpe_ratio, sortino_ratio, win_rate

logger = logging.getLogger(__name__)


class SignalType(str, Enum):
    """Trading signal type."""

    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


# ---------------------------------------------------------------------------
# Engine configuration
# ---------------------------------------------------------------------------


class TradingEngineConfig(TypedDict, total=False):
    """Configuration for the trading engine."""

    fast_ema_period: int
    slow_ema_period: int
    rsi_period: int
    rsi_overbought: float
    rsi_oversold: float
    macd_fast: int
    macd_slow: int
    macd_signal: int
    atr_period: int
    adx_period: int
    stoch_period: int
    stoch_smooth: int
    risk_percent: float
    atr_stop_multiplier: float
    reward_risk_ratio: float
    min_confidence: float


DEFAULT_CONFIG: TradingEngineConfig = {
    "fast_ema_period": 9,
    "slow_ema_period": 21,
    "rsi_period": 14,
    "rsi_overbought": 70.0,
    "rsi_oversold": 30.0,
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    "atr_period": 14,
    "adx_period": 14,
    "stoch_period": 14,
    "stoch_smooth": 3,
    "risk_percent": 2.0,
    "atr_stop_multiplier": 2.0,
    "reward_risk_ratio": 2.0,
    "min_confidence": 0.5,
}


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class IndicatorsSnapshot:
    """Snapshot of indicator values at the latest bar."""

    ema_fast: Optional[float] = None
    ema_slow: Optional[float] = None
    rsi: Optional[float] = None
    macd_line: Optional[float] = None
    macd_signal: Optional[float] = None
    macd_histogram: Optional[float] = None
    atr: Optional[float] = None
    adx_value: Optional[float] = None
    bb_upper: Optional[float] = None
    bb_middle: Optional[float] = None
    bb_lower: Optional[float] = None
    stoch_k: Optional[float] = None
    stoch_d: Optional[float] = None


@dataclass
class TradingSignal:
    """Trading signal with all relevant data."""

    signal_type: SignalType
    confidence: float
    entry_price: float
    stop_loss: Optional[float]
    take_profit: Optional[float]
    position_size: float
    atr_value: Optional[float]
    reason: str
    indicators: IndicatorsSnapshot


@dataclass
class AnalysisResult:
    """Full market analysis output."""

    symbol: str
    timeframe: str
    close: float
    timestamp: Optional[str]
    indicators: IndicatorsSnapshot
    signal: TradingSignal


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class TradingEngine:
    """Deterministic trading engine combining technical analysis with risk control."""

    def __init__(self, config: Optional[TradingEngineConfig] = None) -> None:
        """Initialise the engine.

        Args:
            config: Optional configuration dict.  Missing keys fall back to
                :data:`DEFAULT_CONFIG`.
        """
        self._config: dict[str, object] = dict(DEFAULT_CONFIG)
        if config:
            self._config.update(config)

    @property
    def config(self) -> dict[str, object]:
        """Return the active configuration."""
        return self._config

    # -- public API --------------------------------------------------------

    def generate_signal(
        self,
        ohlc_data: list,
        account_equity: float = 10000.0,
        timestamp: Optional[str] = None,
    ) -> TradingSignal:
        """Generate a trading signal from OHLC data.

        Accepts several input formats:

        - ``list[float]`` — close prices only (oldest → newest).
        - ``list[dict]`` — dicts with ``open``, ``high``, ``low``, ``close`` keys.
        - ``list[list]`` or ``list[tuple]`` — ``(open, high, low, close)``.
        - Objects with ``.close``, ``.high``, ``.low`` attributes (e.g. MT5 models).

        Args:
            ohlc_data: Price data in one of the supported formats.
            account_equity: Account equity for position sizing (default 10 000).
            timestamp: Optional ISO timestamp string for logging.

        Returns:
            :class:`TradingSignal` with signal, confidence, and risk levels.
        """
        if not ohlc_data:
            raise ValueError("OHLC data is empty")

        closes, highs, lows = self._parse_ohlc(ohlc_data)

        min_bars = max(
            int(self._config["slow_ema_period"]),
            int(self._config["macd_slow"]) + int(self._config["macd_signal"]),
            int(self._config["rsi_period"]) + 1,
            int(self._config["atr_period"]) + 1,
            int(self._config["adx_period"]) + 1,
            int(self._config["stoch_period"]),
        )

        if len(closes) < min_bars:
            logger.info(
                "Insufficient data: %d bars, need %d — returning HOLD", len(closes), min_bars
            )
            return self._build_hold_signal(closes[-1], "Insufficient data", IndicatorsSnapshot())

        close = closes[-1]

        # -- Indicators ---------------------------------------------------
        fast_ema = ema(closes, int(self._config["fast_ema_period"]))
        slow_ema = ema(closes, int(self._config["slow_ema_period"]))

        if fast_ema is None or slow_ema is None:
            return self._build_hold_signal(close, "EMA calculation failed", IndicatorsSnapshot())

        rsi_val = rsi(closes, int(self._config["rsi_period"]))
        macd_res = macd(
            closes,
            int(self._config["macd_fast"]),
            int(self._config["macd_slow"]),
            int(self._config["macd_signal"]),
        )
        atr_val = atr(highs, lows, closes, int(self._config["atr_period"]))
        adx_val = adx(highs, lows, closes, int(self._config["adx_period"]))
        bb = bollinger_bands(closes, 20, 2.0)
        stoch = stochastic(
            highs,
            lows,
            closes,
            int(self._config["stoch_period"]),
            int(self._config["stoch_smooth"]),
        )

        snapshot = IndicatorsSnapshot(
            ema_fast=fast_ema,
            ema_slow=slow_ema,
            rsi=rsi_val,
            macd_line=macd_res.macd_line if macd_res else None,
            macd_signal=macd_res.signal_line if macd_res else None,
            macd_histogram=macd_res.histogram if macd_res else None,
            atr=atr_val,
            adx_value=adx_val,
            bb_upper=bb.upper if bb else None,
            bb_middle=bb.middle if bb else None,
            bb_lower=bb.lower if bb else None,
            stoch_k=stoch.k if stoch else None,
            stoch_d=stoch.d if stoch else None,
        )

        # -- Conditions -------------------------------------------------------
        ema_bullish = fast_ema > slow_ema
        ema_bearish = fast_ema < slow_ema

        rsi_buy_ok = (
            rsi_val is not None
            and rsi_val < self._config["rsi_overbought"]  # type: ignore[operator]
        )
        rsi_sell_ok = (
            rsi_val is not None and rsi_val > self._config["rsi_oversold"]  # type: ignore[operator]
        )

        macd_bullish = macd_res is not None and macd_res.histogram > 0.0  # type: ignore[union-attr]
        macd_bearish = macd_res is not None and macd_res.histogram < 0.0  # type: ignore[union-attr]

        buy_conditions = ema_bullish and rsi_buy_ok and macd_bullish
        sell_conditions = ema_bearish and rsi_sell_ok and macd_bearish

        # Bollinger confirmation only matters once a directional signal exists
        bb_lower = bb.lower if bb else None

        # -- Signal & confidence ----------------------------------------------
        signal_type = SignalType.HOLD
        confidence = 0.0
        reason = "No clear signal"

        if buy_conditions:
            signal_type = SignalType.BUY
            confidence = self._calculate_buy_confidence(snapshot)
            reason = self._build_reason(snapshot, "BUY — EMA bullish crossover")

        elif sell_conditions:
            signal_type = SignalType.SELL
            confidence = self._calculate_sell_confidence(snapshot)
            reason = self._build_reason(snapshot, "SELL — EMA bearish crossover")

            # Bollinger confirmation gate for SELL signals
            if bb_lower is not None and close <= bb_lower:
                confidence = min(confidence + 0.10, 1.0)

        # Clamp confidence
        confidence = max(0.0, min(1.0, confidence))

        # -- Position sizing -----------------------------------------------
        stop_loss, take_profit, position_size = self._calculate_risk_levels(
            signal_type, close, atr_val, account_equity
        )

        return TradingSignal(
            signal_type=signal_type,
            confidence=confidence,
            entry_price=close,
            stop_loss=stop_loss,
            take_profit=take_profit,
            position_size=position_size,
            atr_value=atr_val,
            reason=reason,
            indicators=snapshot,
        )

    def analyze(
        self,
        ohlc_data: list,
        symbol: str = "UNKNOWN",
        timeframe: str = "H1",
        account_equity: float = 10000.0,
    ) -> AnalysisResult:
        """Run full market analysis and return a structured result.

        Args:
            ohlc_data: Price data (supports the same formats as
                :meth:`generate_signal`).
            symbol: Symbol name for the result.
            timeframe: Timeframe label for the result.
            account_equity: Account equity for position sizing.

        Returns:
            :class:`AnalysisResult` with indicators, signal, and context.
        """
        signal = self.generate_signal(
            ohlc_data, account_equity, timestamp=datetime.now(timezone.utc).isoformat()
        )
        closes = self._extract_closes(ohlc_data)
        return AnalysisResult(
            symbol=symbol,
            timeframe=timeframe,
            close=closes[-1] if closes else 0.0,
            timestamp=datetime.now(timezone.utc).isoformat(),
            indicators=signal.indicators,
            signal=signal,
        )

    def evaluate_backtest(
        self,
        trades: list[list[float]],
        initial_equity: float,
    ) -> dict[str, Optional[float]]:
        """Evaluate backtest performance from a list of trades.

        Args:
            trades: Each trade is ``[entry, exit, direction, size]`` where
                ``direction`` is ``1`` (long) or ``-1`` (short).
            initial_equity: Starting account equity.

        Returns:
            Dictionary with ``return``, ``max_drawdown``, ``sharpe``,
            ``sortino``, ``win_rate``, ``profit_factor``.
        """
        if not trades:
            return {
                "return": None,
                "max_drawdown": None,
                "sharpe": None,
                "sortino": None,
                "win_rate": None,
                "profit_factor": None,
            }

        equity = float(initial_equity)
        equity_curve: list[float] = [equity]
        returns: list[float] = []
        profits: list[float] = []

        for trade in trades:
            if len(trade) < 4:
                continue
            entry, exit_price, direction, size = trade[0], trade[1], trade[2], trade[3]
            if entry == 0 or size <= 0:
                continue

            pnl = (exit_price - entry) * size if direction == 1 else (entry - exit_price) * size
            equity += pnl
            equity_curve.append(equity)

            ret = (pnl / abs(entry)) * 100.0
            returns.append(ret)
            profits.append(pnl)

        total_return = (
            ((equity - initial_equity) / initial_equity) * 100.0 if initial_equity > 0 else None
        )

        return {
            "return": total_return,
            "max_drawdown": max_drawdown(equity_curve),
            "sharpe": sharpe_ratio(returns) if returns else None,
            "sortino": sortino_ratio(returns) if returns else None,
            "win_rate": win_rate(profits) if profits else None,
            "profit_factor": profit_factor(profits) if profits else None,
        }

    # -- internal helpers ------------------------------------------------

    def _parse_ohlc(self, data: list) -> tuple[list[float], list[float], list[float]]:
        """Parse OHLC data into (closes, highs, lows) arrays (oldest → newest)."""
        first = data[0]
        closes: list[float]
        highs: list[float]
        lows: list[float]

        if isinstance(first, (int, float)):
            closes = [float(x) for x in data]
            highs = closes
            lows = closes

        elif isinstance(first, dict):
            closes = [float(x["close"]) for x in data]
            highs = [float(x["high"]) for x in data]
            lows = [float(x["low"]) for x in data]

        elif isinstance(first, (list, tuple)):
            if len(first) == 4:
                closes = [float(x[3]) for x in data]
                highs = [float(x[1]) for x in data]
                lows = [float(x[2]) for x in data]
            elif len(first) == 1:
                closes = [float(x[0]) for x in data]
                highs = closes
                lows = closes
            else:
                raise ValueError(f"Expected 4 (OHLC) or 1 (close) elements, got {len(first)}")

        else:
            raises = not isinstance(first, (int, float))
            if raises:
                closes = [float(getattr(x, "close", float(x))) for x in data]
                highs = [float(getattr(x, "high", closes[i])) for i, x in enumerate(data)]
                lows = [float(getattr(x, "low", closes[i])) for i, x in enumerate(data)]
            else:
                raise ValueError(f"Unsupported OHLC format: {type(first)}")

        return closes, highs, lows

    def _extract_closes(self, data: list) -> list[float]:
        """Extract close prices from various OHLC formats."""
        try:
            closes, _, _ = self._parse_ohlc(data)
            return closes
        except (KeyError, ValueError, AttributeError):
            return [float(x) for x in data if isinstance(x, (int, float))]

    def _build_hold_signal(
        self, price: float, reason: str, indicators: IndicatorsSnapshot
    ) -> TradingSignal:
        """Build a HOLD signal with zero confidence."""
        return TradingSignal(
            signal_type=SignalType.HOLD,
            confidence=0.0,
            entry_price=price,
            stop_loss=None,
            take_profit=None,
            position_size=0.0,
            atr_value=indicators.atr,
            reason=reason,
            indicators=indicators,
        )

    def _calculate_buy_confidence(self, snap: IndicatorsSnapshot) -> float:
        """Calculate confidence for a BUY signal (0.0–1.0)."""
        score = 0.0
        score += 0.35  # EMA alignment already confirmed
        if snap.rsi is not None:
            # Favour mid-range RSI (around 50, not overbought)
            score += 0.25 * max(
                0.0, 1.0 - snap.rsi / self._config["rsi_overbought"]
            )  # type: ignore
        else:
            score += 0.10
        if snap.macd_histogram is not None and snap.macd_histogram > 0:
            score += 0.20
        else:
            score += 0.10
        if snap.adx_value is not None and snap.adx_value > 20.0:
            score += 0.20 * min(snap.adx_value / 50.0, 1.0)
        else:
            score += 0.10
        return score

    def _calculate_sell_confidence(self, snap: IndicatorsSnapshot) -> float:
        """Calculate confidence for a SELL signal (0.0–1.0)."""
        score = 0.0
        score += 0.35  # EMA alignment already confirmed
        if snap.rsi is not None:
            # Favour mid-range RSI (around 50, not oversold)
            score += 0.25 * min(snap.rsi / self._config["rsi_oversold"], 1.0)  # type: ignore
        else:
            score += 0.10
        if snap.macd_histogram is not None and snap.macd_histogram < 0:
            score += 0.20
        else:
            score += 0.10
        if snap.adx_value is not None and snap.adx_value > 20.0:
            score += 0.20 * min(snap.adx_value / 50.0, 1.0)
        else:
            score += 0.10
        return score

    def _build_reason(self, snap: IndicatorsSnapshot, action: str) -> str:
        """Build a human-readable reason string for a signal."""
        parts = [action]
        if snap.rsi is not None:
            parts.append(f"RSI={snap.rsi:.1f}")
        if snap.macd_histogram is not None:
            parts.append(f"MACD_hist={snap.macd_histogram:.4f}")
        if snap.adx_value is not None:
            parts.append(f"ADX={snap.adx_value:.1f}")
        if snap.atr is not None:
            parts.append(f"ATR={snap.atr:.4f}")
        return ", ".join(parts)

    def _calculate_risk_levels(
        self,
        signal_type: SignalType,
        entry_price: float,
        atr_value: Optional[float],
        account_equity: float,
    ) -> tuple[Optional[float], Optional[float], float]:
        """Calculate stop-loss, take-profit, and position size."""
        stop_distance = (
            atr_value * self._config["atr_stop_multiplier"]
            if atr_value and atr_value > 0
            else entry_price * 0.02  # fallback 2% stop
        )

        if signal_type == SignalType.BUY:
            stop_loss = entry_price - stop_distance
        elif signal_type == SignalType.SELL:
            stop_loss = entry_price + stop_distance
        else:
            return (None, None, 0.0)

        if stop_loss is not None and stop_loss <= 0:
            return (None, None, 0.0)

        take_profit = calculate_take_profit(
            entry_price,
            stop_loss,
            signal_type.value,
            self._config["reward_risk_ratio"],  # type: ignore
        )
        position_size = atr_position_size(
            account_equity,
            self._config["risk_percent"],  # type: ignore
            atr_value if atr_value and atr_value > 0 else stop_distance,
            self._config["atr_stop_multiplier"],  # type: ignore
        )

        return (stop_loss, take_profit, position_size if position_size is not None else 0.0)
