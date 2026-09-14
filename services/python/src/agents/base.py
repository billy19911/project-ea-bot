# -*- coding: utf-8 -*-
"""EA Bot AI Agent Framework — registry, base agent, supervisor skeleton.

Provides a plugin-style agent registry so that specialized agents (Technical,
Fundamental, Sentiment, Risk, Execution) can be discovered and orchestrated
by the Supervisor.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Agent severity / priority helpers
# ---------------------------------------------------------------------------


class AgentPriority(int, Enum):
    """Agent dispatch priority (higher = called first in routing)."""

    CRITICAL = 100
    HIGH = 75
    NORMAL = 50
    LOW = 25
    BACKGROUND = 10


# ---------------------------------------------------------------------------
# AgentRegistry
# ---------------------------------------------------------------------------


class AgentRegistry:
    """Singleton registry for all active agents.

    Agents are registered by name and type.  The registry exposes
    ``get``, ``list``, and ``route`` for supervisor dispatch.
    """

    _instance: Optional["AgentRegistry"] = None

    def __new__(cls) -> "AgentRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._agents: dict[str, "BaseAgent"] = {}
            cls._instance._by_type: dict[str, list[str]] = {}
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton (useful in tests)."""
        cls._instance = None

    def register(self, agent: "BaseAgent") -> None:
        """Register an agent instance."""
        name = agent.name
        agent_type = agent.agent_type
        if name in self._agents:
            raise ValueError(f"Agent '{name}' already registered")
        self._agents[name] = agent
        self._by_type.setdefault(agent_type, []).append(name)

    def unregister(self, name: str) -> bool:
        """Unregister an agent by name.  Returns True if removed."""
        agent = self._agents.pop(name, None)
        if agent is None:
            return False
        self._by_type.get(agent.agent_type, []).remove(name)
        return True

    def get(self, name: str) -> Optional["BaseAgent"]:
        """Get an agent by name."""
        return self._agents.get(name)

    def list(self) -> list["BaseAgent"]:
        """List all registered agents."""
        return list(self._agents.values())

    def get_by_type(self, agent_type: str) -> list["BaseAgent"]:
        """Get all agents of a given type."""
        names = self._by_type.get(agent_type, [])
        return [self._agents[n] for n in names if n in self._agents]

    def get_by_role(self, role: str) -> list["BaseAgent"]:
        """Get all agents whose ``role`` equals ``role``."""
        return [agent for agent in self._agents.values() if agent.role == role]

    def get_by_permission(self, permission: str) -> list["BaseAgent"]:
        """Get all agents that list ``permission`` in ``permissions``."""
        return [agent for agent in self._agents.values() if permission in agent.permissions]

    def export_metadata(self) -> dict[str, dict[str, Any]]:
        """Export full metadata dict keyed by agent name."""
        return {name: agent.to_dict() for name, agent in self._agents.items()}

    def validate_permissions(self, name: str, required: list[str]) -> bool:
        """Check that registered agent ``name`` has all ``required`` permissions."""
        agent = self.get(name)
        if agent is None:
            return False
        perms = set(agent.permissions)
        return all(p in perms for p in required)

    def count(self) -> int:
        """Number of registered agents."""
        return len(self._agents)

    def route(
        self,
        event_type: str,
        context: Optional[dict[str, Any]] = None,
    ) -> list[BaseAgent]:
        """Route an event to eligible agents.

        Returns agents whose ``can_handle`` returns True, sorted by
        priority descending.
        """
        candidates: list[BaseAgent] = []
        for agent in self._agents.values():
            if agent.can_handle(event_type, context or {}):
                candidates.append(agent)
        candidates.sort(key=lambda a: a.priority.value, reverse=True)
        return candidates


# ---------------------------------------------------------------------------
# BaseAgent ABC + TechnicalAnalystAgent
# ---------------------------------------------------------------------------


@dataclass
class AgentCapability:
    """A single capability an agent advertises."""

    name: str
    description: str
    event_types: list[str] = field(default_factory=list)


class BaseAgent(ABC):
    """Abstract base for all EA Bot agents.

    Subclasses must implement ``analyze`` and may override ``can_handle``
    and ``priority``.
    """

    def __init__(
        self,
        name: str,
        agent_type: str,
        description: str = "",
        priority: AgentPriority = AgentPriority.NORMAL,
        role: str = "",
        permissions: list[str] | None = None,
        dependencies: list[str] | None = None,
        model_policy: dict[str, str] | None = None,
        timeout_seconds: int = 30,
    ) -> None:
        self.name = name
        self.agent_type = agent_type
        self.description = description
        self.priority = priority
        self.role = role
        self.permissions = permissions or []
        self.dependencies = dependencies or []
        self.model_policy = model_policy or {}
        self.timeout_seconds = timeout_seconds
        self.capabilities: list[AgentCapability] = []
        self.created_at = datetime.now(timezone.utc).isoformat()

    @abstractmethod
    def analyze(self, context: dict[str, Any]) -> dict[str, Any]:
        """Run agent analysis and return a result dict.

        Args:
            context: Event context (symbol, market_state, detected_events, etc.)

        Returns:
            Arbitrary result dict — the supervisor collects these from
            all routed agents.
        """
        ...

    def can_handle(self, event_type: str, context: dict[str, Any]) -> bool:
        """Check if this agent can handle a given event type.

        Default: True for all events (agents decide internally).
        Override for selective routing.
        """
        return True

    def to_dict(self) -> dict:
        """Serialise agent metadata (for health endpoints)."""
        return {
            "name": self.name,
            "agent_type": self.agent_type,
            "description": self.description,
            "priority": self.priority.value,
            "role": self.role,
            "permissions": self.permissions,
            "dependencies": self.dependencies,
            "model_policy": self.model_policy,
            "timeout_seconds": self.timeout_seconds,
            "capabilities": [c.name for c in self.capabilities],
            "created_at": self.created_at,
        }


class TechnicalAnalystAgent(BaseAgent):
    """A technical-analysis agent that interprets indicator-based events.

    Handles: TREND_*, MOMENTUM_*, RSI_*, STOCH_*, EMA_CROSSOVER, MACD_CROSSOVER,
    BREAKOUT, BREAKDOWN, REVERSAL.
    """

    DEFAULT_EVENT_TYPES = [
        "TREND_BULLISH",
        "TREND_BEARISH",
        "TREND_NEUTRAL",
        "TREND_STRENGTHENING",
        "TREND_WEAKENING",
        "MOMENTUM_BULLISH",
        "MOMENTUM_BEARISH",
        "RSI_OVERBOUGHT",
        "RSI_OVERSOLD",
        "STOCH_OVERBOUGHT",
        "STOCH_OVERSOLD",
        "EMA_CROSSOVER",
        "MACD_CROSSOVER",
        "BREAKOUT",
        "BREAKDOWN",
        "REVERSAL",
    ]

    def __init__(self) -> None:
        super().__init__(
            name="technical_analyst",
            agent_type="technical",
            description="Technical analysis agent — interprets price action and indicator events",
            priority=AgentPriority.HIGH,
        )
        self.capabilities = [
            AgentCapability("trend_analysis", "Identifies and rates trend direction/strength"),
            AgentCapability("momentum_analysis", "Assesses momentum via MACD histogram"),
            AgentCapability("overbought_oversold", "Flags RSI/Stochastic extremes"),
            AgentCapability("crossover_detection", "Detects EMA and MACD crossovers"),
            AgentCapability("breakout_recognition", "Recognises BB breakouts and breakdowns"),
        ]

    def can_handle(self, event_type: str, context: dict[str, Any]) -> bool:
        return event_type in self.DEFAULT_EVENT_TYPES

    def analyze(self, context: dict[str, Any]) -> dict[str, Any]:
        """Analyse detected events and produce a technical assessment."""
        events = context.get("detected_events", [])
        market_state = context.get("market_state")

        signal = "NEUTRAL"
        confidence = 0.0
        reasons: list[str] = []

        if not events:
            return {
                "agent": self.name,
                "signal": signal,
                "confidence": confidence,
                "reasons": ["No events to analyse"],
            }

        # Use event type for proper comparison
        bullish_count = sum(
            1
            for e in events
            if e.event_type.value.startswith("TREND_BULLISH")
            or e.event_type.value.startswith("MOMENTUM_BULLISH")
            or e.event_type == "BREAKOUT"
        )
        bearish_count = sum(
            1
            for e in events
            if e.event_type.value.startswith("TREND_BEARISH")
            or e.event_type.value.startswith("MOMENTUM_BEARISH")
            or e.event_type == "BREAKDOWN"
        )

        if bullish_count > bearish_count:
            signal = "BULLISH"
            confidence = min(0.5 + bullish_count * 0.1, 0.95)
            reasons.append(f"Bullish events dominate ({bullish_count} vs {bearish_count})")
        elif bearish_count > bullish_count:
            signal = "BEARISH"
            confidence = min(0.5 + bearish_count * 0.1, 0.95)
            reasons.append(f"Bearish events dominate ({bearish_count} vs {bullish_count})")
        else:
            reasons.append("Events are balanced")

        if market_state and market_state.trend_direction:
            reasons.append(f"Trend: {market_state.trend_direction}")
            reasons.append(
                f"ADX: {market_state.adx_value:.1f}" if market_state.adx_value else "ADX: N/A"
            )

        return {
            "agent": self.name,
            "signal": signal,
            "confidence": confidence,
            "reasons": reasons,
            "event_count": len(events),
        }


class FundamentalAnalystAgent(BaseAgent):
    """Placeholder fundamental analyst agent — skeleton for Phase 4."""

    def __init__(self) -> None:
        super().__init__(
            name="fundamental_analyst",
            agent_type="fundamental",
            description="Fundamental analysis agent (skeleton — Phase 4)",
            priority=AgentPriority.NORMAL,
        )
        self.capabilities = [
            AgentCapability("economic_calendar", "Monitors economic events"),
            AgentCapability("earnings_analysis", "Analyzes corporate earnings"),
        ]

    def analyze(self, context: dict[str, Any]) -> dict[str, Any]:
        return {
            "agent": self.name,
            "signal": "NEUTRAL",
            "confidence": 0.0,
            "reasons": ["Fundamental agent not yet implemented"],
            "event_count": context.get("detected_events", []),
        }


class SentimentAnalystAgent(BaseAgent):
    """Placeholder sentiment analyst agent — skeleton for Phase 4."""

    def __init__(self) -> None:
        super().__init__(
            name="sentiment_analyst",
            agent_type="sentiment",
            description="Sentiment analysis agent (skeleton — Phase 4)",
            priority=AgentPriority.NORMAL,
        )
        self.capabilities = [
            AgentCapability("news_sentiment", "Analyzes news sentiment"),
            AgentCapability("social_sentiment", "Monitors social media sentiment"),
        ]

    def analyze(self, context: dict[str, Any]) -> dict[str, Any]:
        return {
            "agent": self.name,
            "signal": "NEUTRAL",
            "confidence": 0.0,
            "reasons": ["Sentiment agent not yet implemented"],
            "event_count": context.get("detected_events", []),
        }
