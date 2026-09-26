# -*- coding: utf-8 -*-
"""Momentum Analyst Agent.

Analyzes momentum: RSI, MACD, Stochastic, velocity, divergences.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from trading.indicators import adx, macd, macd_series, rsi, rsi_series, stochastic

from ..base import AgentCapability, AgentPriority, BaseAgent


class MomentumSignal(str, Enum):
    """Momentum signal classification."""

    STRONG_BULLISH = "STRONG_BULLISH"
    BULLISH = "BULLISH"
    NEUTRAL = "NEUTRAL"
    BEARISH = "BEARISH"
    STRONG_BEARISH = "STRONG_BEARISH"


@dataclass
class DivergenceResult:
    """Detected price-indicator divergence."""

    indicator: str  # "RSI", "MACD", etc.
    divergence_type: str  # "bullish" (price LL, ind HL) or "bearish" (price HH, ind LH)
    start_bar: int
    end_bar: int
    strength: float  # 0.0 to 1.0


@dataclass
class MomentumOutput:
    """Output from Momentum Analyst analysis."""

    signal: str
    confidence: float
    reasoning: str
    rsi_value: Optional[float]
    macd_data: Optional[dict[str, float]]
    stoch_data: Optional[dict[str, float]]
    divergences: list[dict[str, Any]]
    velocity: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MomentumInput:
    """Input schema for Momentum Analyst."""

    prices: list[float]  # Close prices, oldest first
    highs: Optional[list[float]] = None
    lows: Optional[list[float]] = None
    timestamp: Optional[str] = None


class MomentumAnalystAgent(BaseAgent):
    """Momentum Analyst — assesses market momentum indicators and divergences.

    Detects:
    - RSI overbought/oversold and momentum
    - MACD trend, histogram expansion/contraction, line crosses
    - Stochastic %K/%D momentum
    - Price velocity (rate of change)
    - Bullish and bearish regular divergences
    """

    SYSTEM_PROMPT = """You are the Momentum Analyst Agent for an automated trading system.
Your role is to evaluate momentum dynamics across multiple time horizons.
Key focus areas:
1. RSI levels (overbought > 70, oversold < 30, baseline momentum 50-centerline cross).
2. MACD histogram expansion/contraction, MACD line vs Signal line crosses.
3. Stochastic oscillator %K/%D positioning and overbought/oversold turns.
4. Price velocity (rate of change over N bars).
5. Bullish and bearish divergences between price action and momentum oscillators.
Output a clear directional signal (BULLISH, BEARISH, NEUTRAL), confidence score (0.0 to 1.0),
and detailed deterministic reasoning."""

    def __init__(self) -> None:
        super().__init__(
            name="momentum_analyst",
            agent_type="momentum",
            description="Analyzes momentum: RSI, MACD, Stochastic, velocity, divergences",
            priority=AgentPriority.HIGH,
        )
        self.capabilities = [
            AgentCapability(
                "rsi_analysis", "Analyzes RSI levels and centerline crosses"
            ),
            AgentCapability(
                "macd_analysis", "Assesses MACD line, signal line, and histogram"
            ),
            AgentCapability(
                "stochastic_analysis", "Evaluates Stochastic %K/%D positioning"
            ),
            AgentCapability(
                "velocity_calculation", "Measures price velocity and rate of change"
            ),
            AgentCapability(
                "divergence_detection",
                "Identifies regular and hidden bullish/bearish divergences",
            ),
            AgentCapability(
                "self_improvement",
                "Calibrates confidence using AgentPatternMemory",
            ),
        ]

    def can_handle(self, event_type: str, context: dict[str, Any]) -> bool:
        """Handle momentum-related events."""
        return (
            event_type
            in (
                "MOMENTUM_ANALYSIS",
                "RSI_CHECK",
                "MACD_CHECK",
                "OSCILLATOR_SCAN",
                "DIVERGENCE_DETECT",
            )
            or event_type.startswith("MOMENTUM_")
            or event_type.startswith("RSI_")
            or (event_type.startswith("STOCH_"))
        )

    def _calculate_velocity(self, prices: list[float], period: int = 5) -> float:
        """Calculate normalized price velocity (Rate of Change % over period)."""
        if len(prices) < period + 1 or prices[-period - 1] == 0:
            return 0.0
        return ((prices[-1] - prices[-period - 1]) / prices[-period - 1]) * 100.0

    @staticmethod
    def _confirmed_pivots(
        prices: list[float], lookback: int = 40, width: int = 1
    ) -> tuple[list[int], list[int]]:
        """Return confirmed local highs and lows within a bounded lookback."""
        start = max(width, len(prices) - lookback)
        highs: list[int] = []
        lows: list[int] = []
        for index in range(start, len(prices) - width):
            window = prices[index - width : index + width + 1]
            if prices[index] > max(window[:width] + window[width + 1 :]):
                highs.append(index)
            elif prices[index] < min(window[:width] + window[width + 1 :]):
                lows.append(index)
        return highs, lows

    @staticmethod
    def _divergence_type(
        previous_price: float,
        latest_price: float,
        previous_oscillator: float,
        latest_oscillator: float,
        pivot_kind: str,
    ) -> Optional[str]:
        """Classify regular or hidden divergence for two confirmed pivots."""
        if pivot_kind == "low":
            if (
                latest_price < previous_price
                and latest_oscillator > previous_oscillator
            ):
                return "regular_bullish"
            if (
                latest_price > previous_price
                and latest_oscillator < previous_oscillator
            ):
                return "hidden_bullish"
        else:
            if (
                latest_price > previous_price
                and latest_oscillator < previous_oscillator
            ):
                return "regular_bearish"
            if (
                latest_price < previous_price
                and latest_oscillator > previous_oscillator
            ):
                return "hidden_bearish"
        return None

    def _detect_divergences(
        self, prices: list[float], lookback: int = 40
    ) -> list[DivergenceResult]:
        """Detect regular and hidden divergences from the latest two confirmed pivots."""
        if len(prices) < 15:
            return []
        highs, lows = self._confirmed_pivots(prices, lookback=lookback)
        rsi_values = rsi_series(prices, 14)
        macd_values = macd_series(prices, 12, 26, 9)[0]
        divergences: list[DivergenceResult] = []

        for indicator, values in (("RSI", rsi_values), ("MACD", macd_values)):
            for pivots, pivot_kind in ((lows, "low"), (highs, "high")):
                if len(pivots) < 2:
                    continue
                previous, latest = pivots[-2:]
                previous_value = values[previous] if previous < len(values) else None
                latest_value = values[latest] if latest < len(values) else None
                if previous_value is None or latest_value is None:
                    continue
                divergence_type = self._divergence_type(
                    prices[previous],
                    prices[latest],
                    previous_value,
                    latest_value,
                    pivot_kind,
                )
                if divergence_type is None:
                    continue
                divergences.append(
                    DivergenceResult(
                        indicator=indicator,
                        divergence_type=divergence_type,
                        start_bar=previous,
                        end_bar=latest,
                        strength=0.75,
                    )
                )
        return divergences

    def _detect_rsi_divergences(
        self, prices: list[float], lookback: int = 20
    ) -> list[DivergenceResult]:
        """Detect RSI divergences using confirmed pivots."""
        return [
            divergence
            for divergence in self._detect_divergences(prices, lookback=lookback)
            if divergence.indicator == "RSI"
        ]

    def _analyze_prices(
        self,
        prices: list[float],
        highs: Optional[list[float]] = None,
        lows: Optional[list[float]] = None,
    ) -> dict[str, Any]:
        """Run the core momentum routine for one price series."""
        if not isinstance(prices, list) or len(prices) < 15:
            raise ValueError("Insufficient price data for momentum analysis")
        if any(
            isinstance(value, bool) or not isinstance(value, (int, float))
            for value in prices
        ):
            raise ValueError("prices must contain numeric values")
        prices = [float(value) for value in prices]

        ohlc_supplied = highs is not None or lows is not None
        if ohlc_supplied:
            if not isinstance(highs, list) or not isinstance(lows, list):
                raise ValueError("highs and lows must be lists when supplied")
            if len(highs) != len(prices) or len(lows) != len(prices):
                raise ValueError("prices, highs, and lows must have equal lengths")
            series = highs + lows
            if any(
                isinstance(value, bool) or not isinstance(value, (int, float))
                for value in series
            ):
                raise ValueError("highs and lows must contain numeric values")
            highs = [float(value) for value in highs]
            lows = [float(value) for value in lows]
        else:
            highs = prices
            lows = prices

        adx_val: Optional[float] = None
        adx_regime = "unavailable"
        if ohlc_supplied:
            adx_val = adx(highs, lows, prices, period=14)
            if adx_val is None:
                raise ValueError(
                    "ADX calculation failed: insufficient bars or invalid data for ADX"
                )
            if adx_val >= 25.0:
                adx_regime = "strong_trend"
            elif adx_val >= 20.0:
                adx_regime = "developing"
            else:
                adx_regime = "weak_range"

        rsi_val = rsi(prices, 14)
        macd_res = macd(prices, 12, 26, 9)
        macd_dict: Optional[dict[str, float]] = None
        if macd_res:
            macd_dict = {
                "macd_line": round(macd_res.macd_line, 6),
                "signal_line": round(macd_res.signal_line, 6),
                "histogram": round(macd_res.histogram, 6),
            }

        stoch_res = stochastic(highs, lows, prices, 14, 3)
        stoch_dict: Optional[dict[str, float]] = None
        if stoch_res:
            stoch_dict = {"k": round(stoch_res.k, 2), "d": round(stoch_res.d, 2)}

        velocity = self._calculate_velocity(prices, 5)
        divergences = self._detect_divergences(prices)

        bull_score = 0.0
        bear_score = 0.0
        reasons: list[str] = []

        if rsi_val is not None:
            if rsi_val > 70:
                bear_score += 1.0
                reasons.append(f"RSI is overbought at {rsi_val:.1f}")
            elif rsi_val < 30:
                bull_score += 1.0
                reasons.append(f"RSI is oversold at {rsi_val:.1f}")
            elif rsi_val >= 55:
                bull_score += 0.8
                reasons.append(f"RSI bullish above centerline at {rsi_val:.1f}")
            elif rsi_val <= 45:
                bear_score += 0.8
                reasons.append(f"RSI bearish below centerline at {rsi_val:.1f}")
            else:
                reasons.append(f"RSI neutral at {rsi_val:.1f}")

        if macd_res:
            if macd_res.histogram > 0:
                bull_score += 1.0
                reasons.append(f"MACD histogram positive ({macd_res.histogram:.4f})")
            elif macd_res.histogram < 0:
                bear_score += 1.0
                reasons.append(f"MACD histogram negative ({macd_res.histogram:.4f})")
            if macd_res.macd_line > macd_res.signal_line:
                bull_score += 0.5
            else:
                bear_score += 0.5

        if stoch_res:
            if stoch_res.k < 20 and stoch_res.d < 20:
                bull_score += 0.8
                reasons.append(
                    f"Stochastic oversold (K:{stoch_res.k:.1f}, D:{stoch_res.d:.1f})"
                )
            elif stoch_res.k > 80 and stoch_res.d > 80:
                bear_score += 0.8
                reasons.append(
                    f"Stochastic overbought (K:{stoch_res.k:.1f}, D:{stoch_res.d:.1f})"
                )
            elif stoch_res.k > stoch_res.d:
                bull_score += 0.4
            elif stoch_res.k < stoch_res.d:
                bear_score += 0.4

        if velocity > 1.0:
            bull_score += 0.5
            reasons.append(f"Positive velocity (+{velocity:.2f}%)")
        elif velocity < -1.0:
            bear_score += 0.5
            reasons.append(f"Negative velocity ({velocity:.2f}%)")

        for divergence in divergences:
            score = 1.5
            label = divergence.divergence_type.replace("_", " ").title()
            if "bullish" in divergence.divergence_type:
                bull_score += score
            else:
                bear_score += score
            reasons.append(f"{label} on {divergence.indicator}")

        diff = bull_score - bear_score
        if diff >= 2.0:
            signal = "STRONG_BULLISH"
            confidence = min(0.60 + (diff * 0.08), 0.95)
        elif diff > 0.5:
            signal = "BULLISH"
            confidence = min(0.50 + (diff * 0.08), 0.85)
        elif diff <= -2.0:
            signal = "STRONG_BEARISH"
            confidence = min(0.60 + (abs(diff) * 0.08), 0.95)
        elif diff < -0.5:
            signal = "BEARISH"
            confidence = min(0.50 + (abs(diff) * 0.08), 0.85)
        else:
            signal = "NEUTRAL"
            confidence = 0.50

        if adx_regime == "strong_trend":
            confidence = min(confidence + 0.03, 0.95)
        elif adx_regime == "weak_range":
            confidence = min(confidence, 0.50)

        div_dicts = [
            {
                "indicator": divergence.indicator,
                "divergence_type": divergence.divergence_type,
                "strength": divergence.strength,
                "start_bar": divergence.start_bar,
                "end_bar": divergence.end_bar,
            }
            for divergence in divergences
        ]
        return {
            "agent": self.name,
            "signal": signal,
            "confidence": confidence,
            "reasoning": (
                "; ".join(reasons) if reasons else "Neutral momentum conditions"
            ),
            "rsi_value": round(rsi_val, 2) if rsi_val is not None else None,
            "macd_data": macd_dict,
            "stoch_data": stoch_dict,
            "divergences": div_dicts,
            "velocity": round(velocity, 4),
            "metadata": {
                "bull_score": round(bull_score, 2),
                "bear_score": round(bear_score, 2),
                "bar_count": len(prices),
                "current_price": prices[-1],
                "adx_value": round(adx_val, 2) if adx_val is not None else None,
                "adx_regime": adx_regime,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        }

    def _analyze_timeframes(self, timeframe_prices: Any) -> dict[str, str]:
        if not isinstance(timeframe_prices, dict) or not timeframe_prices:
            raise ValueError("timeframe_prices must be a non-empty mapping")
        signals: dict[str, str] = {}
        for timeframe, prices in timeframe_prices.items():
            if not isinstance(timeframe, str) or not timeframe.strip():
                raise ValueError("timeframe_prices keys must be non-empty strings")
            if not isinstance(prices, list) or len(prices) < 15:
                raise ValueError(f"timeframe {timeframe} requires at least 15 prices")
            signals[timeframe] = self._analyze_prices(prices)["signal"]
        return signals

    @staticmethod
    def _timeframe_consensus(signals: dict[str, str]) -> bool:
        bull_count = sum("BULLISH" in signal for signal in signals.values())
        bear_count = sum("BEARISH" in signal for signal in signals.values())
        conflict = bull_count > 0 and bear_count > 0
        return not conflict and (bull_count >= 2 or bear_count >= 2)

    def _apply_memory_adjustment(
        self, signal: str, confidence: float, context: dict[str, Any], reasoning: str
    ) -> tuple[float, str]:
        agent_memory = context.get("agent_memory")
        if agent_memory is None:
            try:
                from ..agent_memory import get_agent_memory

                agent_memory = get_agent_memory()
            except Exception:
                agent_memory = None

        final_reasoning = reasoning
        final_conf = confidence

        if agent_memory is not None and hasattr(agent_memory, "adjust_confidence"):
            try:
                regime = (
                    "TRENDING"
                    if ("BULLISH" in signal or "BEARISH" in signal)
                    else "RANGING"
                )
                adjusted_conf, mem_note = agent_memory.adjust_confidence(
                    self.name, regime, confidence
                )
                if mem_note:
                    final_reasoning = f"{reasoning} [Memory: {mem_note}]"
                final_conf = max(0.0, min(1.0, adjusted_conf))
            except Exception:
                pass

        return final_conf, final_reasoning

    def analyze(self, context: dict[str, Any]) -> dict[str, Any]:
        """Run deterministic momentum analysis and return results."""
        prices: Any = []
        try:
            prices = context.get("prices", context.get("close_prices", []))
            highs = context.get("highs")
            lows = context.get("lows")
            result = self._analyze_prices(prices, highs=highs, lows=lows)

            timeframe_prices = context.get("timeframe_prices")
            if timeframe_prices is None:
                timeframe_signals: dict[str, str] = {}
                consensus: Optional[bool] = None
            else:
                timeframe_signals = self._analyze_timeframes(timeframe_prices)
                consensus = self._timeframe_consensus(timeframe_signals)
            result["metadata"].update(
                {
                    "timeframe_signals": timeframe_signals,
                    "multi_timeframe_consensus": consensus,
                }
            )

            conf, reasoning = self._apply_memory_adjustment(
                result["signal"], result["confidence"], context, result["reasoning"]
            )
            result["confidence"] = round(conf, 2)
            result["reasoning"] = reasoning
            return result
        except Exception as exc:
            return self._create_fallback_result(prices, str(exc))

    def _create_fallback_result(self, prices: Any, reason: str) -> dict[str, Any]:
        """Create a fallback result on error or insufficient data."""
        clean_prices = (
            [p for p in prices if isinstance(p, (int, float))]
            if isinstance(prices, list)
            else []
        )
        return {
            "agent": self.name,
            "signal": "NEUTRAL",
            "confidence": 0.0,
            "reasoning": reason,
            "rsi_value": None,
            "macd_data": None,
            "stoch_data": None,
            "divergences": [],
            "velocity": 0.0,
            "metadata": {
                "current_price": clean_prices[-1] if clean_prices else None,
                "bar_count": len(clean_prices),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "adx_value": None,
                "adx_regime": "unavailable",
                "timeframe_signals": {},
                "multi_timeframe_consensus": None,
            },
        }
