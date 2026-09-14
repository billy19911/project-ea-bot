# -*- coding: utf-8 -*-
"""SupervisorAgent — routes events to registered agents and aggregates results.

Uses a routing table mapping event-type patterns to agent names.

Phase 7 enhancements:
  - Priority sorting of matched agents (higher priority first).
  - Context-based agent filtering (market state, symbol, etc.).
  - Concurrency control via ``max_concurrency`` (ThreadPoolExecutor).
  - Token-budget tracking with per-agent estimation and skipping.
  - Routing policies: ``first_match`` (default), ``all_match``,
    ``priority_based``.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Optional

from .base import AgentCapability, AgentPriority, BaseAgent

logger = logging.getLogger(__name__)

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

# Default per-agent token estimate used when the caller does not supply one.
DEFAULT_TOKEN_ESTIMATE: int = 200


class SupervisorAgent(BaseAgent):
    """Orchestrator agent that routes incoming events to specialised agents.

    On ``analyze``, the supervisor:
    1. Looks up the event type in the routing table.
    2. Sorts matched agents by priority (higher first).
    3. Filters agents by context (symbol, market_state, etc.).
    4. Applies the routing policy to select the final agent list.
    5. Invokes selected agents' ``analyze`` methods concurrently (bounded by
       ``max_concurrency``) while respecting the ``token_budget``.
    6. Aggregates results into a single assessment dict.

    Phase 7 parameters (``max_concurrency``, ``token_budget``,
    ``routing_policy``) are all backward compatible: omitting them preserves
    the original synchronous single-pass behaviour.
    """

    def __init__(
        self,
        routing_table: Optional[dict[str, list[str]]] = None,
        max_concurrency: int = 3,
        token_budget: int = 8000,
        routing_policy: str = "first_match",
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
            AgentCapability("priority_sorting", "Orders agents by priority before dispatch"),
            AgentCapability("context_filtering", "Excludes agents based on context"),
            AgentCapability("concurrency_control", "Bounds parallel agent execution"),
            AgentCapability("token_budgeting", "Tracks and enforces token usage"),
        ]

        # Phase 7 configuration (backward compatible defaults).
        self.max_concurrency: int = max_concurrency
        self.token_budget: int = token_budget
        self.routing_policy: str = routing_policy
        self.token_used: int = 0
        # Registry reference for priority lookups; populated per-call from
        # context so the registry stays the source of truth.
        self._registry_cache: Optional[Any] = None

    # ------------------------------------------------------------------
    # Phase 7: configuration setters (backward compatible)
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Phase 7: priority sorting
    # ------------------------------------------------------------------

    def sort_agents_by_priority(self, agent_names: list[str]) -> list[str]:
        """Sort agent names by AgentPriority (higher first).

        Agents without a known priority fall back to ``AgentPriority.NORMAL``
        so they sort in the middle, preserving a stable order.
        """

        def _priority_of(name: str) -> int:
            agent = self._lookup_agent(name)
            if agent is not None and agent.priority:
                return int(agent.priority.value)
            return int(AgentPriority.NORMAL.value)

        return sorted(agent_names, key=_priority_of, reverse=True)

    # ------------------------------------------------------------------
    # Phase 7: context filtering
    # ------------------------------------------------------------------

    def filter_agents(
        self,
        agent_names: list[str],
        context: dict[str, Any],
    ) -> list[str]:
        """Filter out agents that cannot handle the current context.

        Uses each agent's ``can_handle`` method against the event type and
        the full context dict, so agents can exclude themselves based on
        symbol, market state, account balance, or any other context field.
        """
        event_type = context.get("event_type", "UNKNOWN")
        filtered: list[str] = []
        for name in agent_names:
            agent = self._lookup_agent(name)
            if agent is None:
                # Unknown agent — keep it so the registry lookup in ``analyze``
                # reports the "not registered" status consistently.
                filtered.append(name)
                continue
            if agent.can_handle(event_type, context):
                filtered.append(name)
        return filtered

    # ------------------------------------------------------------------
    # Phase 7: token budget tracking
    # ------------------------------------------------------------------

    def check_token_budget(
        self,
        agent_name: str,
        estimated_tokens: int = DEFAULT_TOKEN_ESTIMATE,
    ) -> bool:
        """Check whether ``agent_name`` can run within the remaining budget.

        If sufficient budget remains, the estimate is committed to
        ``self.token_used`` and ``True`` is returned.  Otherwise ``False``
        is returned and no tokens are consumed.
        """
        if self.token_used + estimated_tokens > self.token_budget:
            logger.debug(
                "Agent '%s' skipped: token budget exceeded " "(used=%d, budget=%d, est=%d)",
                agent_name,
                self.token_used,
                self.token_budget,
                estimated_tokens,
            )
            return False
        self.token_used += estimated_tokens
        return True

    def reset_token_budget(self) -> None:
        """Reset the token counter to zero (e.g. per analysis cycle)."""
        self.token_used = 0

    # ------------------------------------------------------------------
    # Phase 7: routing policies
    # ------------------------------------------------------------------

    def _apply_policy(
        self,
        agent_names: list[str],
        context: dict[str, Any],
    ) -> list[str]:
        """Apply the configured routing policy to the agent list.

        Policies:
          * ``first_match``     – keep only the first agent (default).
          * ``all_match``       – keep all agents.
          * ``priority_based``  – sort by priority then keep all.
        """
        policy = self.routing_policy
        if policy == "first_match":
            return agent_names[:1] if agent_names else []
        if policy == "all_match":
            return list(agent_names)
        if policy == "priority_based":
            return self.sort_agents_by_priority(agent_names)
        logger.warning("Unknown routing_policy '%s'; falling back to all_match", policy)
        return list(agent_names)

    # ------------------------------------------------------------------
    # Registry helper
    # ------------------------------------------------------------------

    def _lookup_agent(self, name: str) -> Optional[BaseAgent]:
        """Look up an agent by name from the registry (if available)."""
        registry = self._registry_cache
        if registry is None:
            return None
        try:
            return registry.get(name)
        except Exception:  # pragma: no cover - defensive
            return None

    # ------------------------------------------------------------------
    # Phase 7: analyze with concurrency + token budget
    # ------------------------------------------------------------------

    def analyze(self, context: dict[str, Any]) -> dict[str, Any]:
        """Route the event and aggregate agent results.

        Args:
            context: Must contain ``event_type`` (str), and optionally
                ``detected_events``, ``market_state``, ``agents`` (a list of
                BaseAgent instances to dispatch to), and ``registry`` (an
                AgentRegistry instance).

        Returns:
            Aggregated result dict with per-agent breakdowns.
        """
        event_type = context.get("event_type", "UNKNOWN")
        agent_list: list[BaseAgent] = context.get("agents", [])

        # Reset token budget at the start of each analysis cycle so each
        # ``analyze`` call starts fresh (caller may override by setting
        # ``token_used`` beforehand).
        if context.get("reset_budget", True):
            self.reset_token_budget()

        # Cache the registry (if provided) for priority lookups and filtering.
        registry = context.get("registry")
        self._registry_cache = registry

        if agent_list:
            # Use provided agents if available
            target_names = [a.name for a in agent_list]
            # If the provided list contains department leads, route through them
            # instead of directly invoking specialists.
            lead_names = [
                a.name for a in agent_list if getattr(a, "agent_type", "") == "department_lead"
            ]
            if lead_names:
                target_names = lead_names
            # Build a name->agent map for direct invocation.
            agent_map: dict[str, BaseAgent] = {a.name: a for a in agent_list}
        else:
            # EPIC 01: when department leads are registered, Supervisor delegates
            # to leads first and never directly to specialists. If no leads are
            # available, preserve the legacy routing-table behaviour.
            lead_names: list[str] = []
            if registry is not None:
                try:
                    lead_names = [
                        agent.name
                        for agent in registry.get_by_type("department_lead")
                        if agent.can_handle(event_type, context)
                    ]
                except Exception:  # pragma: no cover - defensive fallback
                    lead_names = []
            target_names = lead_names if lead_names else self.match_routes(event_type)
            agent_map = {}

        # ── Phase 7: sort, filter, apply policy ────────────────────────
        target_names = self.sort_agents_by_priority(target_names)
        target_names = self.filter_agents(target_names, context)
        target_names = self._apply_policy(target_names, context)

        # ── Phase 7: dispatch with concurrency + token budget ──────────
        results: dict[str, Any] = {}
        summary_reasons: list[str] = []
        overall_signal = "NEUTRAL"
        overall_confidence = 0.0
        skipped: list[str] = []

        def _run_agent(agent_name: str) -> tuple[str, dict[str, Any], bool]:
            """Execute a single agent; returns (name, result, within_budget)."""
            estimate = context.get("token_estimates", {}).get(agent_name, DEFAULT_TOKEN_ESTIMATE)
            if not self.check_token_budget(agent_name, estimate):
                return agent_name, {}, False
            agent = agent_map.get(agent_name)
            if agent is None and registry is not None:
                agent = registry.get(agent_name)
            if agent is not None:
                try:
                    result = agent.analyze(context)
                except Exception as exc:  # pragma: no cover - defensive
                    result = {
                        "agent": agent_name,
                        "signal": "NEUTRAL",
                        "confidence": 0.0,
                        "reasons": [f"Error running agent: {exc}"],
                    }
                return agent_name, result, True
            # Fallback: agent not registered
            result = {
                "agent": agent_name,
                "signal": "NEUTRAL",
                "confidence": 0.0,
                "reasons": [f"Agent '{agent_name}' not registered"],
            }
            return agent_name, result, True

        # Decide concurrency: if max_concurrency <= 1, run sequentially to
        # preserve the original (deterministic) ordering of results.
        if self.max_concurrency <= 1:
            for name in target_names:
                agent_name, result, within = _run_agent(name)
                if not within:
                    skipped.append(agent_name)
                    continue
                results[agent_name] = result
                summary_reasons.append(
                    f"{agent_name}: {result.get('signal', 'NEUTRAL')} "
                    f"(conf={result.get('confidence', 0):.2f})"
                )
                if result.get("confidence", 0) > overall_confidence:
                    overall_confidence = result["confidence"]
                    overall_signal = result.get("signal", "NEUTRAL")
        else:
            with ThreadPoolExecutor(max_workers=self.max_concurrency) as executor:
                future_to_name = {executor.submit(_run_agent, name): name for name in target_names}
                # Preserve submission order via as_completed would shuffle;
                # instead we collect and then sort results by original order.
                collected: dict[str, tuple[dict, bool]] = {}
                for future in as_completed(future_to_name):
                    agent_name = future_to_name[future]
                    try:
                        name, result, within = future.result()
                    except Exception as exc:  # pragma: no cover - defensive
                        results[agent_name] = {
                            "agent": agent_name,
                            "signal": "NEUTRAL",
                            "confidence": 0.0,
                            "reasons": [f"Error running agent: {exc}"],
                        }
                        summary_reasons.append(f"{agent_name}: NEUTRAL (conf=0.00)")
                        continue
                    collected[name] = (result, within)

                # Emit in the original (sorted/policy-filtered) order.
                for name in target_names:
                    entry = collected.get(name)
                    if entry is None:
                        continue
                    result, within = entry
                    if not within:
                        skipped.append(name)
                        continue
                    results[name] = result
                    summary_reasons.append(
                        f"{name}: {result.get('signal', 'NEUTRAL')} "
                        f"(conf={result.get('confidence', 0):.2f})"
                    )
                    if result.get("confidence", 0) > overall_confidence:
                        overall_confidence = result["confidence"]
                        overall_signal = result.get("signal", "NEUTRAL")

        return {
            "agent": self.name,
            "event_type": event_type,
            "overall_signal": overall_signal,
            "overall_confidence": overall_confidence,
            "agent_results": results,
            "summary": "; ".join(summary_reasons),
            "skipped_agents": skipped,
            "token_used": self.token_used,
            "token_budget": self.token_budget,
        }
