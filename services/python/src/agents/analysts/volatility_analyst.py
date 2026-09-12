# -*- coding: utf-8 -*-
"""Deterministic volatility analysis agent."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from math import sqrt
from statistics import pstdev
from typing import Any

from ..base import AgentCapability, AgentPriority, BaseAgent


@dataclass
class VolatilityInput:
    """Volatility inputs. Values use price units except ``returns``."""

    atr: float = 0.0
    price: float = 0.0
    bollinger_width: float = 0.0
    returns: list[float] = field(default_factory=list)
    high: float = 0.0
    low: float = 0.0
    periods_per_year: int = 252


@dataclass
class VolatilityOutput:
    """Stable volatility agent output schema."""

    signal: str
    confidence: float
    reasoning: list[str]
    metrics: dict[str, float]


class VolatilityAnalystAgent(BaseAgent):
    """Assess ATR, Bollinger width, historical volatility, and expected range."""

    SYSTEM_PROMPT = (
        "Analyze market volatility only. Use ATR, Bollinger width, historical volatility, "
        "and expected range. Never invent missing measurements."
    )

    def __init__(self) -> None:
        super().__init__(
            name="volatility_analyst",
            agent_type="volatility",
            description="Deterministic ATR, Bollinger, and historical volatility analyst",
            priority=AgentPriority.HIGH,
        )
        self.capabilities = [
            AgentCapability("atr_analysis", "Analyzes average true range"),
            AgentCapability("bollinger_squeeze", "Detects narrow and wide Bollinger bands"),
            AgentCapability("historical_volatility", "Calculates annualized return volatility"),
            AgentCapability("expected_range", "Estimates one-period expected price range"),
        ]

    def can_handle(self, event_type: str, context: dict[str, Any]) -> bool:
        return event_type.startswith("VOLATILITY_") or "volatility" in context

    @staticmethod
    def _input(context: dict[str, Any]) -> VolatilityInput:
        source = context.get("volatility", context)
        if isinstance(source, VolatilityInput):
            return source
        if source is None:
            return VolatilityInput()
        return VolatilityInput(
            atr=float(source.get("atr", 0) or 0),
            price=float(source.get("price", 0) or 0),
            bollinger_width=float(source.get("bollinger_width", source.get("bb_width", 0)) or 0),
            returns=[float(value) for value in source.get("returns", [])],
            high=float(source.get("high", 0) or 0),
            low=float(source.get("low", 0) or 0),
            periods_per_year=int(source.get("periods_per_year", 252) or 252),
        )

    def analyze(self, context: dict[str, Any]) -> dict[str, Any]:
        """Return a deterministic volatility assessment; degrade on bad input."""
        try:
            data = self._input(context)
            annualized = (
                pstdev(data.returns) * sqrt(data.periods_per_year) if len(data.returns) > 1 else 0.0
            )
            atr_percent = data.atr / data.price if data.price > 0 else 0.0
            expected_range = (
                data.atr
                if data.atr > 0
                else (
                    data.price * annualized / sqrt(data.periods_per_year)
                    if data.price > 0 and annualized > 0
                    else 0.0
                )
            )
            observed_range = max(data.high - data.low, 0.0)
            width = data.bollinger_width
            if data.bollinger_width:
                squeeze = 0 < width <= 0.02
                wide = width >= 0.08
            else:
                squeeze = False
                wide = False
            if squeeze:
                signal, confidence = "LOW", 0.78
            elif wide or atr_percent >= 0.03 or annualized >= 0.30:
                signal, confidence = "HIGH", 0.85
            elif atr_percent > 0 or annualized > 0 or width > 0:
                signal, confidence = "NORMAL", 0.62
            else:
                signal, confidence = "UNKNOWN", 0.0
            reasoning = [f"Volatility regime: {signal.lower()}"]
            if squeeze:
                reasoning.append("Bollinger bands indicate a squeeze")
            if wide:
                reasoning.append("Bollinger bands are wide")
            if not data.returns and annualized == 0:
                reasoning.append("Historical returns unavailable")
            metrics = {
                "atr": round(data.atr, 10),
                "atr_percent": round(atr_percent, 10),
                "bollinger_width": round(width, 10),
                "historical_volatility": round(annualized, 10),
                "expected_range": round(expected_range, 10),
                "observed_range": round(observed_range, 10),
                "squeeze": float(squeeze),
            }
            result = VolatilityOutput(signal, confidence, reasoning, metrics)
            return {"agent": self.name, **asdict(result)}
        except (TypeError, ValueError, ZeroDivisionError) as exc:
            return {
                "agent": self.name,
                "signal": "UNKNOWN",
                "confidence": 0.0,
                "reasoning": [f"Invalid volatility input: {exc}"],
                "metrics": {},
            }


VolatilityAnalyst = VolatilityAnalystAgent
