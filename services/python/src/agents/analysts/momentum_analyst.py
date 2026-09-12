# -*- coding: utf-8 -*-
"""Momentum Analyst Agent.

Analyzes momentum: RSI, MACD, Stochastic, velocity, divergences.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from trading.indicators import macd, rsi, stochastic

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
            AgentCapability("rsi_analysis", "Analyzes RSI levels and centerline crosses"),
            AgentCapability("macd_analysis", "Assesses MACD line, signal line, and histogram"),
            AgentCapability("stochastic_analysis", "Evaluates Stochastic %K/%D positioning"),
            AgentCapability("velocity_calculation", "Measures price velocity and rate of change"),
            AgentCapability(
                "divergence_detection", "Identifies regular bullish/bearish divergences"
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

    def _detect_rsi_divergences(
        self, prices: list[float], lookback: int = 20
    ) -> list[DivergenceResult]:
        """Detect simple regular divergences between price and RSI over a lookback window."""
        divergences: list[DivergenceResult] = []
        if len(prices) < lookback + 15:
            return divergences

        # Calculate rolling RSI for the last lookback bars
        rsi_series: list[float] = []
        for i in range(len(prices) - lookback, len(prices) + 1):
            subset = prices[:i]
            r = rsi(subset, period=14)
            if r is not None:
                rsi_series.append(r)
            else:
                rsi_series.append(50.0)

        if len(rsi_series) < lookback:
            return divergences

        price_sub = prices[-lookback:]

        # Find local troughs/peaks in price and RSI
        # Bullish divergence: price makes Lower Low, RSI makes Higher Low
        if len(price_sub) >= 10:
            half = len(price_sub) // 2
            p_low1 = min(price_sub[:half])
            p_low2 = min(price_sub[half:])
            r_low1 = min(rsi_series[:half])
            r_low2 = min(rsi_series[half:])

            if p_low2 < p_low1 and r_low2 > r_low1:
                divergences.append(
                    DivergenceResult(
                        indicator="RSI",
                        divergence_type="bullish",
                        start_bar=0,
                        end_bar=lookback - 1,
                        strength=0.75,
                    )
                )

            # Bearish divergence: price makes Higher High, RSI makes Lower High
            p_high1 = max(price_sub[:half])
            p_high2 = max(price_sub[half:])
            r_high1 = max(rsi_series[:half])
            r_high2 = max(rsi_series[half:])

            if p_high2 > p_high1 and r_high2 < r_high1:
                divergences.append(
                    DivergenceResult(
                        indicator="RSI",
                        divergence_type="bearish",
                        start_bar=0,
                        end_bar=lookback - 1,
                        strength=0.75,
                    )
                )

        return divergences

    def analyze(self, context: dict[str, Any]) -> dict[str, Any]:
        """Run deterministic momentum analysis and return results."""
        try:
            prices = context.get("prices", context.get("close_prices", []))
            highs = context.get("highs", [])
            lows = context.get("lows", [])

            if not prices or len(prices) < 15:
                return self._create_fallback_result(
                    prices, "Insufficient price data for momentum analysis"
                )

            if not highs:
                highs = prices
            if not lows:
                lows = prices

            min_len = min(len(prices), len(highs), len(lows))
            prices = prices[:min_len]
            highs = highs[:min_len]
            lows = lows[:min_len]

            # 1. RSI (14)
            rsi_val = rsi(prices, 14)

            # 2. MACD (12, 26, 9)
            macd_res = macd(prices, 12, 26, 9)
            macd_dict: Optional[dict[str, float]] = None
            if macd_res:
                macd_dict = {
                    "macd_line": round(macd_res.macd_line, 6),
                    "signal_line": round(macd_res.signal_line, 6),
                    "histogram": round(macd_res.histogram, 6),
                }

            # 3. Stochastic (14, 3)
            stoch_res = stochastic(highs, lows, prices, 14, 3)
            stoch_dict: Optional[dict[str, float]] = None
            if stoch_res:
                stoch_dict = {
                    "k": round(stoch_res.k, 2),
                    "d": round(stoch_res.d, 2),
                }

            # 4. Velocity (5 bars)
            velocity = self._calculate_velocity(prices, 5)

            # 5. Divergences
            divergences = self._detect_rsi_divergences(prices)

            # Scoring algorithm for deterministic signal & confidence
            bull_score = 0.0
            bear_score = 0.0
            reasons: list[str] = []

            # Evaluate RSI
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

            # Evaluate MACCD
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

            # Evaluate Stochastic
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

            # Evaluate Velocity
            if velocity > 1.0:
                bull_score += 0.5
                reasons.append(f"Positive velocity (+{velocity:.2f}%)")
            elif velocity < -1.0:
                bear_score += 0.5
                reasons.append(f"Negative velocity ({velocity:.2f}%)")

            # Evaluate Divergences
            for div in divergences:
                if div.divergence_type == "bullish":
                    bull_score += 1.5
                    reasons.append(f"Regular bullish divergence detected on {div.indicator}")
                elif div.divergence_type == "bearish":
                    bear_score += 1.5
                    reasons.append(f"Regular bearish divergence detected on {div.indicator}")

            # Determine aggregate signal and confidence
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

            div_dicts = [
                {
                    "indicator": d.indicator,
                    "divergence_type": d.divergence_type,
                    "strength": d.strength,
                    "start_bar": d.start_bar,
                    "end_bar": d.end_bar,
                }
                for d in divergences
            ]

            return {
                "agent": self.name,
                "signal": signal,
                "confidence": round(confidence, 2),
                "reasoning": "; ".join(reasons) if reasons else "Neutral momentum conditions",
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
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            }

        except Exception as e:
            return self._create_fallback_result(context.get("prices", []), str(e))

    def _create_fallback_result(self, prices: list[float], reason: str) -> dict[str, Any]:
        """Create a fallback result on error or insufficient data."""
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
                "current_price": prices[-1] if prices else None,
                "bar_count": len(prices) if prices else 0,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        }
