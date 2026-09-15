# -*- coding: utf-8 -*-
"""Model routing policy — PRD_V2 §22 Model Routing.

The :class:`ModelRouter` picks a primary model and a fallback chain from the
:class:`~llm.registry.ModelRegistry` using a deterministic policy derived from:

* task complexity (LOW / MEDIUM / HIGH),
* event priority,
* risk level (a HIGH risk gate forbids free/cheap models),
* conflict severity,
* remaining budget (a hard cost ceiling), and
* provider health (from ``ModelRegistry.health()``).

Every routing decision is logged with the chosen model, the reason, the
fallback chain and cost/latency placeholders. Given identical inputs the router
always returns the identical decision (no randomness, no time dependence in the
*selection* logic).

The router is intentionally a thin policy layer: it only *chooses* models. The
:class:`~llm.nine_router.NineRouterClient` remains responsible for actually
calling the gateway (the router's ``primary``/``fallbacks`` can be passed to
``client.generate(model=...)``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from .base import ModelInfo
from .registry import ModelRegistry

logger = logging.getLogger(__name__)

__all__ = [
    "Complexity",
    "Priority",
    "RiskLevel",
    "RoutingDecision",
    "ModelRouter",
]


class Complexity(str, Enum):
    """Task complexity tiers that drive the base model tier (§22)."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class Priority(str, Enum):
    """Event priority tiers (§15 / §22)."""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    NORMAL = "NORMAL"
    LOW = "LOW"
    BACKGROUND = "BACKGROUND"


class RiskLevel(str, Enum):
    """Risk level attached to a routing request.

    A ``HIGH`` risk level forbids free/cheap models — the routing policy prefers
    a capable paid model even when a free model is available (safety over cost).
    """

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


# Base tier preference by complexity. Names are matched against the registry;
# the router degrades gracefully to whatever is available.
_TIER_BY_COMPLEXITY: dict[Complexity, str] = {
    Complexity.LOW: "free",
    Complexity.MEDIUM: "cheap",
    Complexity.HIGH: "strong",
}


@dataclass
class RoutingDecision:
    """Result of a routing decision.

    Attributes:
        model: Chosen primary model name.
        fallback_chain: Ordered fallback model names (excludes the primary).
        reason: Human-readable rationale for the choice.
        complexity: The complexity that drove the decision.
        priority: The event priority that drove the decision.
        risk_level: The risk level that drove the decision.
        health_state: The gateway health state observed at decision time.
        cost_estimate: Placeholder estimated cost in USD for this call.
        latency_ms_budget: Placeholder latency budget in milliseconds.
    """

    model: str
    fallback_chain: list[str] = field(default_factory=list)
    reason: str = ""
    complexity: Complexity = Complexity.LOW
    priority: Priority = Priority.NORMAL
    risk_level: RiskLevel = RiskLevel.LOW
    health_state: str = "DISCONNECTED"
    cost_estimate: float = 0.0
    latency_ms_budget: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Serialise the decision to a JSON-friendly dict."""
        return {
            "model": self.model,
            "fallback_chain": list(self.fallback_chain),
            "reason": self.reason,
            "complexity": self.complexity.value,
            "priority": self.priority.value,
            "risk_level": self.risk_level.value,
            "health_state": self.health_state,
            "cost_estimate": self.cost_estimate,
            "latency_ms_budget": self.latency_ms_budget,
        }


# Latency budgets (ms) per complexity — placeholders for observability (§22).
_LATENCY_BUDGET_MS: dict[Complexity, int] = {
    Complexity.LOW: 2_000,
    Complexity.MEDIUM: 5_000,
    Complexity.HIGH: 15_000,
}


class ModelRouter:
    """Deterministic model selection policy (§22).

    Args:
        registry: The :class:`ModelRegistry` describing available models.
        default_expected_tokens: Token volume assumed when a caller does not
            supply ``expected_tokens`` (used for the budget ceiling check).
    """

    def __init__(
        self,
        registry: ModelRegistry,
        default_expected_tokens: int = 2_000,
    ) -> None:
        self.registry = registry
        self.default_expected_tokens = default_expected_tokens
        self._log: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def route(
        self,
        complexity: Complexity = Complexity.LOW,
        priority: Priority = Priority.NORMAL,
        risk_level: RiskLevel = RiskLevel.LOW,
        conflict_severity: float = 0.0,
        budget_remaining_usd: Optional[float] = None,
        expected_tokens: Optional[int] = None,
        role: Optional[str] = None,
    ) -> RoutingDecision:
        """Choose a model + fallback chain for a single task.

        The selection is a pure function of the arguments and the current
        registry contents / health — repeated calls with the same inputs return
        the same model (deterministic).

        Args:
            complexity: Task complexity tier.
            priority: Event priority tier.
            risk_level: Risk level; ``HIGH`` forbids free models.
            conflict_severity: 0.0–1.0 conflict intensity (higher favors strong).
            budget_remaining_usd: Hard cost ceiling for the call; ``None``
                means unbounded.
            expected_tokens: Expected total tokens for a cost estimate.
            role: Optional role override (supervisor/market/risk/research/review).

        Returns:
            A :class:`RoutingDecision`.
        """
        health_state = str(self.registry.health().get("state", "DISCONNECTED"))
        tokens = expected_tokens if expected_tokens is not None else self.default_expected_tokens

        free_forbidden = risk_level is RiskLevel.HIGH
        # A HIGH conflict supervisor synthesis also favors capable models.
        prefer_strong = conflict_severity >= 0.7 or priority is Priority.CRITICAL

        tier = _TIER_BY_COMPLEXITY[complexity]
        if prefer_strong and tier == "free":
            tier = "cheap"

        candidates = self._candidates(tier, free_forbidden)

        reason = self._reason(complexity, risk_level, priority, tier, health_state)

        affordable = self._affordable(candidates, budget_remaining_usd, tokens)

        if affordable:
            primary = affordable[0].name
            chain = [m.name for m in affordable[1:]]
        elif free_forbidden:
            # HIGH risk and nothing affordable → deterministic refusal: pick the
            # cheapest paid model (never a free model) so the caller must decide
            # to abort rather than silently downgrade safety.
            paid = self._candidates("strong", free_forbidden=True)
            if not paid:
                paid = [m for m in self.registry.list_models() if not m.is_free]
            primary = paid[0].name if paid else ""
            chain = [m.name for m in paid[1:]] if paid else []
            reason += " | budget exhausted; high-risk forbids free models"
        else:
            # Over budget but free models are allowed → degrade to a free model
            # (fail-safe: cheapest routing that still fits the ceiling).
            free = [m for m in self.registry.list_models() if m.is_free]
            if free:
                primary = free[0].name
                chain = [m.name for m in free[1:]]
            else:
                primary = ""
                chain = []
            reason += " | over budget; degrading to free tier"

        cost_estimate = self.registry.calculate_cost(primary, tokens // 2, tokens // 2)
        decision = RoutingDecision(
            model=primary,
            fallback_chain=chain,
            reason=reason,
            complexity=complexity,
            priority=priority,
            risk_level=risk_level,
            health_state=health_state,
            cost_estimate=cost_estimate,
            latency_ms_budget=_LATENCY_BUDGET_MS[complexity],
        )
        self._record(decision, tokens, role)
        return decision

    def primary_and_fallbacks(self, **kwargs: Any) -> tuple[str, list[str]]:
        """Convenience: return ``(primary, fallbacks)`` for a routing request."""
        decision = self.route(**kwargs)
        return decision.model, decision.fallback_chain

    def log(self) -> list[dict[str, Any]]:
        """Return the recorded per-call routing log entries."""
        return list(self._log)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _candidates(self, tier: str, free_forbidden: bool) -> list[ModelInfo]:
        """Return ordered candidate models for a tier.

        Ordering is deterministic: the registry's insertion order, filtered by
        affordability/tier. Under ``free_forbidden`` free models are dropped.
        """
        models = self.registry.list_models()
        if free_forbidden:
            models = [m for m in models if not m.is_free]

        if tier == "free":
            preferred = [m for m in models if m.is_free]
            others = [m for m in models if not m.is_free]
            return preferred + others

        if tier == "strong":
            # Prefer reasoning-capable then most expensive (capable) paid models.
            paid = [m for m in models if not m.is_free]
            reasoning = [m for m in paid if "reasoning" in m.capabilities]
            rest = [m for m in paid if m not in reasoning]
            # Within each group, sort by cost descending (strongest first).
            reasoning.sort(key=lambda m: -(m.cost_per_completion_token + m.cost_per_prompt_token))
            rest.sort(key=lambda m: -(m.cost_per_completion_token + m.cost_per_prompt_token))
            ordered = reasoning + rest
            if not ordered:
                ordered = [m for m in models if m.is_free]
            return ordered

        # tier == "cheap": prefer cheapest paid, then most capable free.
        paid = [m for m in models if not m.is_free]
        paid.sort(key=lambda m: (m.cost_per_completion_token + m.cost_per_prompt_token))
        free = [m for m in models if m.is_free]
        return paid + free

    def _affordable(
        self,
        candidates: list[ModelInfo],
        budget_remaining_usd: Optional[float],
        tokens: int,
    ) -> list[ModelInfo]:
        """Filter candidates that fit within the budget ceiling."""
        if budget_remaining_usd is None:
            return list(candidates)
        result: list[ModelInfo] = []
        for model in candidates:
            cost = self.registry.calculate_cost(model.name, tokens // 2, tokens // 2)
            if model.is_free or cost <= budget_remaining_usd:
                result.append(model)
        return result

    @staticmethod
    def _reason(
        complexity: Complexity,
        risk_level: RiskLevel,
        priority: Priority,
        tier: str,
        health_state: str,
    ) -> str:
        return (
            f"complexity={complexity.value} risk={risk_level.value} "
            f"priority={priority.value} tier={tier} health={health_state}"
        )

    def _record(self, decision: RoutingDecision, tokens: int, role: Optional[str]) -> None:
        """Append a structured, loggable routing record (§22 logging)."""
        entry = {
            "model": decision.model,
            "reason": decision.reason,
            "fallback_chain": list(decision.fallback_chain),
            "role": role,
            "complexity": decision.complexity.value,
            "priority": decision.priority.value,
            "risk_level": decision.risk_level.value,
            "health_state": decision.health_state,
            "expected_tokens": tokens,
            "cost_estimate": decision.cost_estimate,
            "latency_ms_budget": decision.latency_ms_budget,
        }
        self._log.append(entry)
        logger.info(
            "model_route model=%s fallback=%s reason=%s cost_est=%.6f latency_budget_ms=%d",
            decision.model,
            decision.fallback_chain,
            decision.reason,
            decision.cost_estimate,
            decision.latency_ms_budget,
        )
