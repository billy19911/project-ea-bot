# -*- coding: utf-8 -*-
"""Structure Analyst Agent.

Analyzes market structure: support/resistance, swing highs/lows, trendlines,
order blocks/liquidity levels, Fair Value Gaps (FVG), Break of Structure (BOS),
Change of Character (CHoCH), and integrates self-improvement lessons.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from trading.indicators import adx, bollinger_bands, ema

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
    """Deterministic market-structure analysis agent with self-improvement.

    Detects:
    - Support / Resistance clusters with multi-touch strength
    - Fractal Swing Highs & Lows (Higher Highs, Lower Lows)
    - Break of Structure (BOS) & Change of Character (CHoCH)
    - Liquidity Sweeps / Stop Hunts
    - Fair Value Gaps (FVG) / Imbalance Zones
    - ADX Trend Strength confirmation
    - Historical Lessons & Confidence Calibration (Self-Improvement)
    """

    SYSTEM_PROMPT = (
        "Analyze market structure deterministically. Identify confirmed swing highs and lows, "
        "support/resistance, liquidity zones, Break of Structure (BOS), "
        "Change of Character (CHoCH), "
        "Fair Value Gaps (FVG), and moving-average trend alignment. Calibrate confidence with past "
        "trading lessons."
    )

    def __init__(self) -> None:
        super().__init__(
            name="structure_analyst",
            agent_type="structural",
            description=(
                "Analyzes market structure: support/resistance, swing "
                "highs/lows, BOS, CHoCH, FVG, order blocks, and applies past lessons"
            ),
            priority=AgentPriority.HIGH,
        )
        self.capabilities = [
            AgentCapability(
                "support_resistance", "Identifies key support/resistance levels"
            ),
            AgentCapability("swing_detection", "Detects swing highs and lows"),
            AgentCapability(
                "trend_identification",
                "Identifies trend direction from price-MA relationship",
            ),
            AgentCapability(
                "order_block_analysis", "Finds order blocks and liquidity zones"
            ),
            AgentCapability(
                "market_structure_patterns",
                "Detects BOS, CHoCH, FVG, and liquidity sweeps",
            ),
            AgentCapability(
                "self_improvement",
                "Calibrates signal and confidence using past trade lessons",
            ),
        ]

    def can_handle(self, event_type: str, context: dict[str, Any]) -> bool:
        """Handle structure-related events."""
        return event_type in (
            "STRUCTURE_ANALYSIS",
            "PRICE_ACTION",
            "TREND_DETECT",
            "LEVEL_SCAN",
            "MARKET_STRUCTURE",
        ) or event_type.startswith("MARKET_")

    def _detect_swing_points(
        self, highs: list[float], lows: list[float], lookback: int = 5
    ) -> tuple[Optional[float], Optional[float]]:
        """Detect most recent swing high and swing low."""
        if len(highs) < lookback * 2 + 1 or len(lows) < lookback * 2 + 1:
            return None, None

        start_idx = len(highs) - lookback - 1
        end_idx = len(highs) - lookback
        swing_high = max(highs[start_idx:end_idx]) if start_idx >= 0 else None
        swing_low = min(lows[start_idx:end_idx]) if start_idx >= 0 else None

        return swing_high, swing_low

    def _detect_market_structure_pattern(
        self, highs: list[float], lows: list[float], prices: list[float]
    ) -> dict[str, Any]:
        """Detect advanced SMC patterns: BOS, CHoCH, HH/HL/LH/LL sequence."""
        if len(prices) < 15:
            return {
                "structure_type": "INSUFFICIENT_DATA",
                "bos": None,
                "choch": None,
                "hh_hl": False,
                "lh_ll": False,
                "sweep": None,
            }

        # 3-fractal swing sequence for structural trend
        recent_highs = [highs[-i] for i in range(1, min(16, len(highs)), 5)]
        recent_lows = [lows[-i] for i in range(1, min(16, len(lows)), 5)]

        hh_hl = False
        lh_ll = False
        if len(recent_highs) >= 2 and len(recent_lows) >= 2:
            hh_hl = (
                recent_highs[0] > recent_highs[1] and recent_lows[0] > recent_lows[1]
            )
            lh_ll = (
                recent_highs[0] < recent_highs[1] and recent_lows[0] < recent_lows[1]
            )

        # Break of Structure (BOS) / Change of Character (CHoCH)
        prior_swing_high = max(highs[-15:-5]) if len(highs) >= 15 else highs[0]
        prior_swing_low = min(lows[-15:-5]) if len(lows) >= 15 else lows[0]
        current_price = prices[-1]

        bos = None
        choch = None
        if current_price > prior_swing_high:
            bos = "BULLISH_BOS"
            if lh_ll:  # Was making lower lows, now broke prior swing high -> Reversal!
                choch = "BULLISH_CHOCH"
        elif current_price < prior_swing_low:
            bos = "BEARISH_BOS"
            if hh_hl:  # Was making higher highs, now broke prior swing low -> Reversal!
                choch = "BEARISH_CHOCH"

        # Liquidity sweep (Stop hunt): spike above prior high but close below it, or vice versa
        sweep = None
        if highs[-1] > prior_swing_high and current_price < prior_swing_high:
            sweep = "BEARISH_SWEEP"
        elif lows[-1] < prior_swing_low and current_price > prior_swing_low:
            sweep = "BULLISH_SWEEP"

        structure_type = (
            "TRENDING_UP" if hh_hl else ("TRENDING_DOWN" if lh_ll else "RANGING")
        )

        return {
            "structure_type": structure_type,
            "bos": bos,
            "choch": choch,
            "hh_hl": hh_hl,
            "lh_ll": lh_ll,
            "sweep": sweep,
            "prior_swing_high": prior_swing_high,
            "prior_swing_low": prior_swing_low,
        }

    def _detect_fvg(
        self, highs: list[float], lows: list[float], prices: list[float]
    ) -> list[dict[str, Any]]:
        """Detect Fair Value Gaps (FVG) / Imbalances in recent candles."""
        fvgs: list[dict[str, Any]] = []
        if len(prices) < 4:
            return fvgs

        lookback = min(10, len(prices) - 2)
        for i in range(len(prices) - lookback, len(prices) - 1):
            if i > 0 and i < len(highs) - 1:
                # Bullish FVG: Bar i-1 high < Bar i+1 low
                if lows[i + 1] > highs[i - 1]:
                    fvgs.append(
                        {
                            "type": "BULLISH_FVG",
                            "top": lows[i + 1],
                            "bottom": highs[i - 1],
                            "mid": (lows[i + 1] + highs[i - 1]) / 2.0,
                        }
                    )
                # Bearish FVG: Bar i-1 low > Bar i+1 high
                elif highs[i + 1] < lows[i - 1]:
                    fvgs.append(
                        {
                            "type": "BEARISH_FVG",
                            "top": lows[i - 1],
                            "bottom": highs[i + 1],
                            "mid": (lows[i - 1] + highs[i + 1]) / 2.0,
                        }
                    )

        return fvgs[-3:]

    def _calculate_support_resistance(
        self, lows: list[float], highs: list[float], prices: list[float]
    ) -> tuple[list[KeyLevel], list[KeyLevel]]:
        """Calculate support and resistance levels from pivots and BB."""
        supports: list[KeyLevel] = []
        resistances: list[KeyLevel] = []

        if len(prices) < 10:
            return supports, resistances

        pivot_count = max(3, len(prices) // 10)
        recent_prices = prices[-pivot_count * 2 :]

        price_counts: dict[float, int] = {}
        for p in recent_prices:
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

    def _apply_self_improvement(
        self, signal: str, confidence: float, context: dict[str, Any]
    ) -> tuple[float, str]:
        """Calibrate signal and confidence using historical lessons and memory."""
        adjustment_note = ""
        calibrated_conf = confidence

        # 1. Check lesson store if available
        lesson_store = context.get("lesson_store")
        if not lesson_store:
            try:
                from .review_agent import get_lesson_store

                lesson_store = get_lesson_store()
            except ImportError:
                lesson_store = None

        if lesson_store and hasattr(lesson_store, "all_lessons"):
            lessons = lesson_store.all_lessons()
            false_breakouts = [
                lesson
                for lesson in lessons
                if "breakout" in str(lesson).lower()
                or "structure" in str(lesson).lower()
            ]
            if len(false_breakouts) >= 2:
                calibrated_conf = max(0.1, calibrated_conf - 0.1)
                adjustment_note = (
                    f" [Self-Improvement: {len(false_breakouts)} past structure/breakout "
                    f"failures noted - confidence adjusted -0.10]"
                )

        # 2. Check agent memory accuracy if provided
        agent_memory = context.get("agent_memory")
        if agent_memory and hasattr(agent_memory, "adjust_confidence"):
            regime = context.get(
                "regime",
                (
                    "TRENDING"
                    if ("BULLISH" in signal or "BEARISH" in signal)
                    else "RANGING"
                ),
            )
            calibrated_conf, mem_note = agent_memory.adjust_confidence(
                self.name, regime, calibrated_conf
            )
            if "confidence" in mem_note:
                adjustment_note += f" [Memory: {mem_note}]"

        return round(calibrated_conf, 3), adjustment_note

    def analyze(self, context: dict[str, Any]) -> dict[str, Any]:
        """Run structure analysis with advanced patterns & self-improvement."""
        try:
            prices = context.get("prices", context.get("close_prices", []))
            highs = context.get("highs", [])
            lows = context.get("lows", [])

            if not prices or len(prices) < 10:
                return self._create_fallback_result(
                    prices, "Insufficient price data for structure analysis"
                )

            if not highs:
                highs = prices
            if not lows:
                lows = prices

            min_len = min(len(prices), len(highs), len(lows))
            prices = prices[:min_len]
            highs = highs[:min_len]
            lows = lows[:min_len]

            # 1. Moving Averages
            ema_fast = ema(prices, 20)
            ema_slow = ema(prices, 50)
            ema_100 = ema(prices, 100)

            # 2. ADX Trend Strength Confirmation
            adx_val = None
            if len(prices) >= 15:
                try:
                    adx_val = adx(highs, lows, prices, period=14)
                except Exception:
                    adx_val = None

            # 3. Detect Swing Points & SMC Patterns
            swing_high, swing_low = self._detect_swing_points(highs, lows)
            pattern_info = self._detect_market_structure_pattern(highs, lows, prices)
            fvgs = self._detect_fvg(highs, lows, prices)

            # 4. S/R Levels
            supports, resistances = self._calculate_support_resistance(
                lows, highs, prices
            )
            trend = (
                self._determine_trend(prices, ema_fast, ema_slow)
                if ema_fast and ema_slow
                else "NEUTRAL"
            )
            order_blocks = self._detect_order_blocks(prices, highs, lows)

            # 5. Build Key Levels Output
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
            for ob in order_blocks:
                key_levels.append(ob)

            # 6. Confluence Scoring & Direction Decision
            price = prices[-1]
            confidence = 0.5
            bullish_factors: list[str] = []
            bearish_factors: list[str] = []

            # MA trend
            if trend == "BULLISH":
                bullish_factors.append("EMA20>50")
            elif trend == "BEARISH":
                bearish_factors.append("EMA20<50")

            # BOS / CHoCH confluence
            if pattern_info["bos"] == "BULLISH_BOS":
                bullish_factors.append("BOS-Bullish")
            elif pattern_info["bos"] == "BEARISH_BOS":
                bearish_factors.append("BOS-Bearish")

            if pattern_info["choch"] == "BULLISH_CHOCH":
                bullish_factors.append("CHoCH-Reversal-Bullish")
            elif pattern_info["choch"] == "BEARISH_CHOCH":
                bearish_factors.append("CHoCH-Reversal-Bearish")

            # Sweep / Stop Hunt confluence
            if pattern_info["sweep"] == "BULLISH_SWEEP":
                bullish_factors.append("LiquiditySweep-Bullish")
            elif pattern_info["sweep"] == "BEARISH_SWEEP":
                bearish_factors.append("LiquiditySweep-Bearish")

            # Structure HH/HL or LH/LL
            if pattern_info["hh_hl"]:
                bullish_factors.append("HH-HL-Sequence")
            elif pattern_info["lh_ll"]:
                bearish_factors.append("LH-LL-Sequence")

            # ADX trend confirmation
            is_trending = adx_val is not None and adx_val > 25.0
            is_ranging = adx_val is not None and adx_val < 20.0

            # Weigh factors
            if len(bullish_factors) > len(bearish_factors):
                signal = "BULLISH"
                base_conf = 0.6 + (0.05 * len(bullish_factors))
                if is_trending:
                    base_conf += 0.1
                elif is_ranging:
                    base_conf -= 0.15
                confidence = min(0.95, base_conf)
                adx_desc = (
                    "Trending"
                    if is_trending
                    else ("Ranging" if is_ranging else "Neutral")
                )
                adx_str = f"{adx_val:.1f}" if adx_val is not None else "N/A"
                sw_str = f"{swing_low:.4f}" if swing_low is not None else "N/A"
                reasoning = (
                    f"Bullish structure confirmed ({', '.join(bullish_factors)}). "
                    f"ADX: {adx_str} ({adx_desc}). "
                    f"Swing low: {sw_str}"
                )
            elif len(bearish_factors) > len(bullish_factors):
                signal = "BEARISH"
                base_conf = 0.6 + (0.05 * len(bearish_factors))
                if is_trending:
                    base_conf += 0.1
                elif is_ranging:
                    base_conf -= 0.15
                confidence = min(0.95, base_conf)
                adx_desc = (
                    "Trending"
                    if is_trending
                    else ("Ranging" if is_ranging else "Neutral")
                )
                adx_str = f"{adx_val:.1f}" if adx_val is not None else "N/A"
                sw_str = f"{swing_high:.4f}" if swing_high is not None else "N/A"
                reasoning = (
                    f"Bearish structure confirmed ({', '.join(bearish_factors)}). "
                    f"ADX: {adx_str} ({adx_desc}). "
                    f"Swing high: {sw_str}"
                )
            else:
                signal = "NEUTRAL"
                confidence = 0.4
                adx_str = f"{adx_val:.1f}" if adx_val is not None else "N/A"
                reasoning = (
                    f"Market structure balanced/ranging. "
                    f"ADX: {adx_str}. "
                    f"Key levels tracked: {len(key_levels)}"
                )

            # 7. Apply Self-Improvement Calibration
            confidence, self_improve_note = self._apply_self_improvement(
                signal, confidence, context
            )
            reasoning += self_improve_note

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
                    "adx": adx_val,
                    "current_price": price,
                    "bar_count": len(prices),
                    "structure_pattern": pattern_info,
                    "fvg_count": len(fvgs),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            }

        except Exception as e:
            return self._create_fallback_result(context.get("prices", []), str(e))

    def _create_fallback_result(
        self, prices: list[float], reason: str
    ) -> dict[str, Any]:
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
