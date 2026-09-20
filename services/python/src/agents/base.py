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
        """Analyse detected events into a structured, evidence-weighted view.

        Sharpened reasoning (v2):

        * each event carries an **evidence weight** (trend > momentum > extreme);
        * a **conflict** is flagged when bullish and bearish evidence coexist;
        * **regime** (from ``market_state``) moderates the read — e.g. an
          oscillator extreme is discounted in a strong trend;
        * historical **pattern memory** nudges confidence (±0.15 max) and adds
          an evidence-backed reasoning line — advisory only.
        """
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
                "event_count": 0,
            }

        # --- Weighted evidence scoring -----------------------------------
        # Trend evidence is the strongest signal; momentum supports it; raw
        # overbought/oversold extremes are the weakest (and often contrarian).
        bull_score = 0.0
        bear_score = 0.0
        bull_ev: list[str] = []
        bear_ev: list[str] = []
        for e in events:
            et = e.event_type.value
            if et.startswith("TREND_BULLISH") or et == "BREAKOUT":
                bull_score += 1.0
                bull_ev.append(et)
            elif et.startswith("TREND_BEARISH") or et == "BREAKDOWN":
                bear_score += 1.0
                bear_ev.append(et)
            elif et.startswith("MOMENTUM_BULLISH") or et == "EMA_CROSSOVER":
                bull_score += 0.6
                bull_ev.append(et)
            elif et.startswith("MOMENTUM_BEARISH") or et == "MACD_CROSSOVER":
                bear_score += 0.6
                bear_ev.append(et)
            elif et in ("RSI_OVERSOLD", "STOCH_OVERSOLD"):
                # Oversold leans bullish but only weakly (can be a falling knife).
                bull_score += 0.3
                bull_ev.append(et)
            elif et in ("RSI_OVERBOUGHT", "STOCH_OVERBOUGHT"):
                bear_score += 0.3
                bear_ev.append(et)

        total = bull_score + bear_score
        net = bull_score - bear_score

        # --- Regime moderation -------------------------------------------
        regime = "unknown"
        trend_strength = 0.0
        if market_state is not None:
            regime = self._regime_of(market_state)
            try:
                trend_strength = float(getattr(market_state, "adx_value", 0.0) or 0.0)
            except (TypeError, ValueError):
                trend_strength = 0.0
            # In a strong trend, discount weak counter-trend oscillator reads.
            if trend_strength >= 25 and regime.startswith("trend"):
                if regime == "trend_up" and bear_score and bear_score < bull_score:
                    bear_score *= 0.5
                elif regime == "trend_down" and bull_score and bull_score < bear_score:
                    bull_score *= 0.5
                net = bull_score - bear_score
                total = bull_score + bear_score
                reasons.append(
                    f"Strong {regime.replace('trend_', '')} trend (ADX {trend_strength:.0f}) — "
                    "counter-trend reads discounted"
                )

        # --- Decide + conflict detection ---------------------------------
        conflict = bull_score > 0 and bear_score > 0 and abs(net) < 0.5 * max(total, 1e-9)
        if net > 0:
            signal = "BULLISH"
        elif net < 0:
            signal = "BEARISH"

        if total > 0:
            # Confidence scales with how decisive the evidence split is.
            dominance = abs(net) / total  # 0..1
            confidence = min(0.5 + dominance * 0.45, 0.95)

        if conflict:
            confidence *= 0.6
            reasons.append(
                f"Conflicting evidence (bull {bull_score:.1f} vs bear {bear_score:.1f}) — "
                "reduced conviction"
            )
        if bull_ev:
            reasons.append(f"Bullish evidence: {', '.join(sorted(set(bull_ev)))}")
        if bear_ev:
            reasons.append(f"Bearish evidence: {', '.join(sorted(set(bear_ev)))}")

        # --- Pattern memory (advisory) -----------------------------------
        try:
            from .agent_memory import get_agent_memory

            memory = get_agent_memory()
            adjusted, note = memory.adjust_confidence(self.name, regime, confidence)
            if note:
                reasons.append(note)
            confidence = adjusted
        except Exception:  # noqa: BLE001 - memory must never break analysis
            pass

        if market_state is not None:
            reasons.append(f"Regime: {regime}")
            if trend_strength:
                reasons.append(f"ADX: {trend_strength:.1f}")

        return {
            "agent": self.name,
            "signal": signal,
            "confidence": round(confidence, 4),
            "reasons": reasons,
            "regime": regime,
            "conflict": conflict,
            "evidence": {
                "bull_score": round(bull_score, 3),
                "bear_score": round(bear_score, 3),
                "net": round(net, 3),
            },
            "event_count": len(events),
        }

    @staticmethod
    def _regime_of(market_state: Any) -> str:
        """Derive a coarse regime label from a market_state object."""
        direction = str(getattr(market_state, "trend_direction", "") or "").lower()
        if "up" in direction or "bull" in direction:
            return "trend_up"
        if "down" in direction or "bear" in direction:
            return "trend_down"
        if direction in ("range", "ranging", "sideways"):
            return "range"
        return "unknown"


class FundamentalAnalystAgent(BaseAgent):
    """Fundamental analyst agent — honest UNSUPPORTED stub (PRD_V2 §25).

    Fundamental data feeds (economic calendar, earnings) are not wired yet.
    Rather than fabricate a neutral recommendation that looks like real
    analysis, this agent returns an explicit ``UNSUPPORTED`` status with
    ``confidence`` 0.0 so the Supervisor and downstream consumers can tell the
    difference between "no signal" and "not implemented".
    """

    def __init__(self) -> None:
        super().__init__(
            name="fundamental_analyst",
            agent_type="fundamental",
            description="Fundamental analysis agent (UNSUPPORTED — data feeds not wired)",
            priority=AgentPriority.NORMAL,
        )
        self.capabilities = [
            AgentCapability("economic_calendar", "Monitors economic events"),
            AgentCapability("earnings_analysis", "Analyzes corporate earnings"),
        ]

    def analyze(self, context: dict[str, Any]) -> dict[str, Any]:
        """Return an explicit UNSUPPORTED result (no fabricated analysis)."""
        return {
            "agent": self.name,
            "status": "UNSUPPORTED",
            "supported": False,
            "signal": "NEUTRAL",
            "confidence": 0.0,
            "reasons": ["Fundamental analysis is not implemented"],
            "event_count": len(context.get("detected_events", []) or []),
        }


class SentimentAnalystAgent(BaseAgent):
    """Sentiment analyst agent — honest UNSUPPORTED stub (PRD_V2 §25).

    News/social sentiment feeds are not wired yet. Returns an explicit
    ``UNSUPPORTED`` status instead of fabricated neutral data.
    """

    def __init__(self) -> None:
        super().__init__(
            name="sentiment_analyst",
            agent_type="sentiment",
            description="Sentiment analysis agent (UNSUPPORTED — data feeds not wired)",
            priority=AgentPriority.NORMAL,
        )
        self.capabilities = [
            AgentCapability("news_sentiment", "Analyzes news sentiment"),
            AgentCapability("social_sentiment", "Monitors social media sentiment"),
        ]

    def analyze(self, context: dict[str, Any]) -> dict[str, Any]:
        """Return an explicit UNSUPPORTED result (no fabricated analysis)."""
        return {
            "agent": self.name,
            "status": "UNSUPPORTED",
            "supported": False,
            "signal": "NEUTRAL",
            "confidence": 0.0,
            "reasons": ["Sentiment analysis is not implemented"],
            "event_count": len(context.get("detected_events", []) or []),
        }
