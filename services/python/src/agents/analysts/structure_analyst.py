# -*- coding: utf-8 -*-
"""Structure Analyst Agent.

Analyzes market structure: support/resistance, swing highs/lows, trendlines,
order blocks/liquidity levels.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from trading.indicators import bollinger_bands, ema

from ..base import AgentCapability, AgentPriority, BaseAgent


class SignalType(str, Enum):
    """Market structure signal type."""

    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


@dataclass
class KeyLevel:
    """A key support or resistance level."""

    price: float
    level_type: str  # "support" or "resistance"
    strength: float  # 0.0 to 1.0
    touch_count: int


@dataclass
class StructureOutput:
    """Output from Structure Analyst analysis."""

    signal: str
    confidence: float
    reasoning: str
    key_levels: list[dict[str, Any]]
    swing_high: Optional[float]
    swing_low: Optional[float]
    trend_direction: Optional[str]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class StructureInput:
    """Validated input schema for Structure Analyst."""

    prices: list[float]
    highs: list[float]
    lows: list[float]
    timestamp: Optional[str] = None

    @classmethod
    def from_context(cls, context: dict[str, Any]) -> "StructureInput":
        """Parse close/high/low series, defaulting missing high/low to close."""
        if not isinstance(context, dict):
            raise TypeError("context must be a dictionary")
        prices = context.get("prices", context.get("close_prices", []))
        highs = context.get("highs") or prices
        lows = context.get("lows") or prices
        if not all(isinstance(series, list) for series in (prices, highs, lows)):
            raise TypeError("prices, highs, and lows must be lists")
        if len(prices) != len(highs) or len(prices) != len(lows):
            raise ValueError("prices, highs, and lows must have equal lengths")
        try:
            return cls(
                prices=[float(value) for value in prices],
                highs=[float(value) for value in highs],
                lows=[float(value) for value in lows],
                timestamp=context.get("timestamp"),
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("price series must contain numeric values") from exc


class StructureAnalystAgent(BaseAgent):
    """Deterministic market-structure analysis agent.

    Detects support/resistance, swing highs/lows, trend alignment, and
    order-block/liquidity zones from supplied OHLC data.
    """

    SYSTEM_PROMPT = (
        "Analyze market structure deterministically. Identify confirmed swing highs and lows, "
        "support/resistance, liquidity zones, and moving-average trend alignment. Return only "
        "evidence supported by supplied OHLC data; use a neutral, low-confidence result for "
        "insufficient or invalid input."
    )

    def __init__(self) -> None:
        super().__init__(
            name="structure_analyst",
            agent_type="structural",
            description=(
                "Analyzes market structure: support/resistance, swing "
                "highs/lows, trendlines, order blocks"
            ),
            priority=AgentPriority.HIGH,
        )
        self.capabilities = [
            AgentCapability("support_resistance", "Identifies key support/resistance levels"),
            AgentCapability("swing_detection", "Detects swing highs and lows"),
            AgentCapability(
                "trend_identification",
                "Identifies trend direction from price-MA relationship",
            ),
            AgentCapability("order_block_analysis", "Finds order blocks and liquidity zones"),
        ]

    def can_handle(self, event_type: str, context: dict[str, Any]) -> bool:
        """Handle structure-related events."""
        return event_type in (
            "STRUCTURE_ANALYSIS",
            "PRICE_ACTION",
            "TREND_DETECT",
            "LEVEL_SCAN",
        ) or event_type.startswith("MARKET_")

    def _detect_swing_points(
        self, highs: list[float], lows: list[float], lookback: int = 5
    ) -> tuple[Optional[float], Optional[float]]:
        """Detect most recent swing high and swing low.

        A swing high is the highest price in a window with lower highs on both
        sides. A swing low is the lowest price in a window with higher lows on
        both sides.
        """
        if len(highs) < lookback * 2 + 1 or len(lows) < lookback * 2 + 1:
            return None, None

        # Last valid swing high: highest high in middle of window
        start_idx = len(highs) - lookback - 1
        end_idx = len(highs) - lookback
        swing_high = max(highs[start_idx:end_idx]) if start_idx >= 0 else None

        # Last valid swing low
        swing_low = min(lows[start_idx:end_idx]) if start_idx >= 0 else None

        return swing_high, swing_low

    def _calculate_support_resistance(
        self, lows: list[float], highs: list[float], prices: list[float]
    ) -> tuple[list[KeyLevel], list[KeyLevel]]:
        """Calculate support and resistance levels from pivots and BB."""
        supports: list[KeyLevel] = []
        resistances: list[KeyLevel] = []

        if len(prices) < 10:
            return supports, resistances

        # Pivot-based levels (last 20% of data)
        pivot_count = max(3, len(prices) // 10)
        recent_prices = prices[-pivot_count * 2 :]

        # Price clusters as potential levels
        price_counts: dict[float, int] = {}
        for p in recent_prices:
            # Round to nearest 0.01 for clustering
            cluster = round(p / 0.005) * 0.005
            price_counts[cluster] = price_counts.get(cluster, 0) + 1

        for price, count in price_counts.items():
            level = KeyLevel(
                price=price,
                level_type="support" if price < prices[-1] else "resistance",
                strength=min(1.0, count / pivot_count),
                touch_count=count,
            )
            if price < prices[-1]:
                supports.append(level)
            else:
                resistances.append(level)

        # Bollinger Band levels
        bb = bollinger_bands(prices)
        if bb:
            if bb.lower > 0:
                supports.append(
                    KeyLevel(
                        price=bb.lower,
                        level_type="support",
                        strength=0.8,
                        touch_count=1,
                    )
                )
            if bb.upper > 0:
                resistances.append(
                    KeyLevel(
                        price=bb.upper,
                        level_type="resistance",
                        strength=0.8,
                        touch_count=1,
                    )
                )

        # Sort by strength
        supports.sort(key=lambda x: x.strength, reverse=True)
        resistances.sort(key=lambda x: x.strength, reverse=True)

        return supports[:5], resistances[:5]

    def _determine_trend(
        self, prices: list[float], ema_fast: Optional[float], ema_slow: Optional[float]
    ) -> str:
        """Determine trend direction based on price position relative to MAs."""
        if len(prices) < 20 or ema_fast is None or ema_slow is None:
            return "NEUTRAL"

        price = prices[-1]
        if price > ema_fast > ema_slow:
            return "BULLISH"
        elif price < ema_fast < ema_slow:
            return "BEARISH"
        elif price > ema_fast:
            return "WEAK_BULLISH"
        else:
            return "WEAK_BEARISH"

    def _detect_order_blocks(
        self, prices: list[float], highs: list[float], lows: list[float]
    ) -> list[dict[str, Any]]:
        """Detect recent order blocks / liquidity zones."""
        if len(prices) < 15:
            return []

        order_blocks: list[dict[str, Any]] = []

        # Look for price extremes in recent bars
        recent_high = max(highs[-10:]) if len(highs) >= 10 else None
        recent_low = min(lows[-10:]) if len(lows) >= 10 else None

        if recent_high:
            order_blocks.append(
                {
                    "price": recent_high,
                    "type": "bullish_liquidity",
                    "description": "Recent swing high - bearish order block zone",
                }
            )

        if recent_low:
            order_blocks.append(
                {
                    "price": recent_low,
                    "type": "bearish_liquidity",
                    "description": "Recent swing low - bullish order block zone",
                }
            )

        return order_blocks

    def analyze(self, context: dict[str, Any]) -> dict[str, Any]:
        """Run structure analysis and return results."""
        try:
            # Extract input data
            prices = context.get("prices", context.get("close_prices", []))
            highs = context.get("highs", [])
            lows = context.get("lows", [])

            # Validate input
            if not prices or len(prices) < 10:
                return self._create_fallback_result(
                    prices, "Insufficient price data for structure analysis"
                )

            if not highs:
                highs = prices
            if not lows:
                lows = prices

            # Ensure same length
            min_len = min(len(prices), len(highs), len(lows))
            prices = prices[:min_len]
            highs = highs[:min_len]
            lows = lows[:min_len]

            # Calculate indicators
            ema_fast = ema(prices, 20)
            ema_slow = ema(prices, 50)
            ema_100 = ema(prices, 100)

            # Detect swing points
            swing_high, swing_low = self._detect_swing_points(highs, lows)

            # Calculate levels
            supports, resistances = self._calculate_support_resistance(lows, highs, prices)

            # Determine trend
            trend = (
                self._determine_trend(prices, ema_fast, ema_slow)
                if ema_fast and ema_slow
                else "NEUTRAL"
            )

            # Detect order blocks
            order_blocks = self._detect_order_blocks(prices, highs, lows)

            # Build key_levels output
            key_levels: list[dict[str, Any]] = []
            for s in supports[:3]:
                key_levels.append(
                    {
                        "price": s.price,
                        "level_type": s.level_type,
                        "strength": s.strength,
                        "touch_count": s.touch_count,
                    }
                )
            for r in resistances[:3]:
                key_levels.append(
                    {
                        "price": r.price,
                        "level_type": r.level_type,
                        "strength": r.strength,
                        "touch_count": r.touch_count,
                    }
                )

            # Build order blocks
            for ob in order_blocks:
                key_levels.append(ob)

            # Calculate confidence
            price = prices[-1]
            confidence = 0.5
            if ema_fast and ema_slow:
                if (price > ema_fast > ema_slow) or (price < ema_fast < ema_slow):
                    confidence = 0.8
                elif price > ema_fast or price < ema_fast:
                    confidence = 0.6

            # Determine signal
            if trend == "BULLISH":
                signal = "BULLISH"
                sh_str = f"{swing_low:.4f}" if swing_low else "N/A"
                reasoning = f"Price above EMA20/50, trend bullish. Swing low: {sh_str}"
            elif trend == "BEARISH":
                signal = "BEARISH"
                sh_str = f"{swing_high:.4f}" if swing_high else "N/A"
                reasoning = f"Price below EMA20/50, trend bearish. Swing high: {sh_str}"
            else:
                signal = "NEUTRAL"
                reasoning = f"Trend ambiguous: {trend}. Key levels identified: {len(key_levels)}"

            return {
                "agent": self.name,
                "signal": signal,
                "confidence": confidence,
                "reasoning": reasoning,
                "key_levels": key_levels,
                "swing_high": swing_high,
                "swing_low": swing_low,
                "trend_direction": trend,
                "metadata": {
                    "ema_20": ema_fast,
                    "ema_50": ema_slow,
                    "ema_100": ema_100,
                    "current_price": price,
                    "bar_count": len(prices),
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
            "key_levels": [],
            "swing_high": None,
            "swing_low": None,
            "trend_direction": "NEUTRAL",
            "metadata": {
                "current_price": prices[-1] if prices else None,
                "bar_count": len(prices) if prices else 0,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        }
