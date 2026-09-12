# -*- coding: utf-8 -*-
"""SupervisorAgent — routes events to registered agents and aggregates results.

Uses a routing table mapping event-type patterns to agent names.
"""

from __future__ import annotations

from typing import Any, Optional

from .base import AgentCapability, AgentPriority, BaseAgent

# ── Default routing table ────────────────────────────────────────────────────
# Keys are event-type substrings; values are agent names (registered in registry).
# The supervisor matches an incoming event against this table and dispatches to
# the corresponding agent(s).  Agents not in the table are still discovered via
# ``can_handle`` for ad-hoc routing.

DEFAULT_ROUTING_TABLE: dict[str, list[str]] = {
    # Trend events → technical analyst
    "TREND_": ["technical_analyst"],
    "MOMENTUM_": ["technical_analyst"],
    "EMA_CROSSOVER": ["technical_analyst"],
    "MACD_CROSSOVER": ["technical_analyst"],
    "BREAKOUT": ["technical_analyst"],
    "BREAKDOWN": ["technical_analyst"],
    "REVERSAL": ["technical_analyst"],
    # RSI / Stochastic extremes
    "RSI_": ["technical_analyst"],
    "STOCH_": ["technical_analyst"],
    # Fundamental events (Phase 4)
    "EARNINGS_": ["fundamental_analyst"],
    "ECONOMIC_": ["fundamental_analyst"],
    # Sentiment events (Phase 4)
    "NEWS_": ["sentiment_analyst"],
    "SOCIAL_": ["sentiment_analyst"],
    # Risk events — handled by risk gate + supervisor
    "DRAWDOWN_": ["technical_analyst"],
    "EXPOSURE_": ["technical_analyst"],
    "LIQUIDITY_": ["technical_analyst"],
    # Gap / Doji — technical
    "GAP_": ["technical_analyst"],
    "DOJI": ["technical_analyst"],
    "VOLATILITY_": ["technical_analyst"],
}


class SupervisorAgent(BaseAgent):
    """Orchestrator agent that routes incoming events to specialised agents.

    On ``analyze``, the supervisor:
    1. Looks up the event type in the routing table.
    2. Invokes each matched agent's ``analyze`` method.
    3. Aggregates results into a single assessment dict.
    """

    def __init__(
        self,
        routing_table: Optional[dict[str, list[str]]] = None,
    ) -> None:
        super().__init__(
            name="supervisor",
            agent_type="supervisor",
            description="Event routing and agent orchestration supervisor",
            priority=AgentPriority.CRITICAL,
        )
        self.routing_table: dict[str, list[str]] = (
            routing_table if routing_table is not None else dict(DEFAULT_ROUTING_TABLE)
        )
        self.capabilities = [
            AgentCapability("event_routing", "Routes events to the correct agent"),
            AgentCapability("result_aggregation", "Aggregates multi-agent results"),
        ]

    def add_route(
        self,
        event_pattern: str,
        agent_names: list[str],
    ) -> None:
        """Add or override a routing entry."""
        self.routing_table[event_pattern] = agent_names

    def remove_route(self, event_pattern: str) -> bool:
        """Remove a routing entry. Returns True if removed."""
        if event_pattern in self.routing_table:
            del self.routing_table[event_pattern]
            return True
        return False

    def match_routes(self, event_type: str) -> list[str]:
        """Match an event type against the routing table.

        Returns agent names in order; the first match wins (prefix match).
        """
        matched: list[str] = []
        for pattern, agents in self.routing_table.items():
            if event_type.startswith(pattern.rstrip("_")) or event_type == pattern:
                matched.extend(agents)
        # Deduplicate preserving order
        seen: set[str] = set()
        unique: list[str] = []
        for name in matched:
            if name not in seen and name not in unique:
                seen.add(name)
                unique.append(name)
        return unique if unique else ["technical_analyst"]  # fallback

    def analyze(self, context: dict[str, Any]) -> dict[str, Any]:
        """Route the event and aggregate agent results.

        Args:
            context: Must contain ``event_type`` (str), and optionally
                ``detected_events``, ``market_state``, and ``agents``
                (a list of BaseAgent instances to dispatch to).

        Returns:
            Aggregated result dict with per-agent breakdowns.
        """
        event_type = context.get("event_type", "UNKNOWN")
        agent_list: list[BaseAgent] = context.get("agents", [])

        if agent_list:
            # Use provided agents if available
            target_names = [a.name for a in agent_list]
        else:
            target_names = self.match_routes(event_type)

        # Collect results from each target agent (simulate if agent not in registry)
        results: dict[str, Any] = {}
        summary_reasons: list[str] = []
        overall_signal = "NEUTRAL"
        overall_confidence = 0.0

        for agent_name in target_names:
            agent = context.get("registry").get(agent_name) if "registry" in context else None
            if agent is not None:
                result = agent.analyze(context)
                results[agent_name] = result
                summary_reasons.append(
                    f"{agent_name}: {result.get('signal', 'NEUTRAL')} "
                    f"(conf={result.get('confidence', 0):.2f})"
                )
                if result.get("confidence", 0) > overall_confidence:
                    overall_confidence = result["confidence"]
                    overall_signal = result.get("signal", "NEUTRAL")
            else:
                results[agent_name] = {
                    "agent": agent_name,
                    "signal": "NEUTRAL",
                    "confidence": 0.0,
                    "reasons": [f"Agent '{agent_name}' not registered"],
                }

        return {
            "agent": self.name,
            "event_type": event_type,
            "overall_signal": overall_signal,
            "overall_confidence": overall_confidence,
            "agent_results": results,
            "summary": "; ".join(summary_reasons),
        }
