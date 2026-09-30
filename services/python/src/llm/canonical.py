# -*- coding: utf-8 -*-
"""Phase 6 canonical model-orchestration objects.

Frozen, auditable dataclasses that make every AI request traceable and bounded:
task taxonomy, risk tiers, complexity, effort, budget ledger, routing policy
version, prompt version, model decision record, snapshot-safe cache key.

Safety spine: none of these carry authority over RiskGate / MoneyManager /
ExecutionEngine / TriggerEngine / strategy activation. They only describe and
shape AI work.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

__all__ = [
    "TaskType",
    "RiskTier",
    "Complexity",
    "Effort",
    "ModelRequest",
    "RoutingPolicyVersion",
    "PromptVersion",
    "ModelDecisionRecord",
    "BudgetLedger",
    "CacheKey",
    "FORBIDDEN_AUTHORITY_FIELDS",
    "TASK_TYPES",
]


# ── Task taxonomy (§5) ──────────────────────────────────────────────────
class TaskType:
    FAST_CLASSIFICATION = "FAST_CLASSIFICATION"
    MARKET_SUMMARY = "MARKET_SUMMARY"
    STRUCTURE_ANALYSIS = "STRUCTURE_ANALYSIS"
    LIQUIDITY_ANALYSIS = "LIQUIDITY_ANALYSIS"
    MOMENTUM_ANALYSIS = "MOMENTUM_ANALYSIS"
    VOLATILITY_ANALYSIS = "VOLATILITY_ANALYSIS"
    NEWS_MACRO_ANALYSIS = "NEWS_MACRO_ANALYSIS"
    ENTRY_ANALYSIS = "ENTRY_ANALYSIS"
    CHALLENGE = "CHALLENGE"
    SUPERVISOR_SYNTHESIS = "SUPERVISOR_SYNTHESIS"
    RESEARCH_REVIEW = "RESEARCH_REVIEW"
    HYPOTHESIS_GENERATION = "HYPOTHESIS_GENERATION"
    RESEARCH_SUMMARY = "RESEARCH_SUMMARY"
    PATTERN_EXPLANATION = "PATTERN_EXPLANATION"
    CODE_ENGINEERING = "CODE_ENGINEERING"


TASK_TYPES = (
    TaskType.FAST_CLASSIFICATION,
    TaskType.MARKET_SUMMARY,
    TaskType.STRUCTURE_ANALYSIS,
    TaskType.LIQUIDITY_ANALYSIS,
    TaskType.MOMENTUM_ANALYSIS,
    TaskType.VOLATILITY_ANALYSIS,
    TaskType.NEWS_MACRO_ANALYSIS,
    TaskType.ENTRY_ANALYSIS,
    TaskType.CHALLENGE,
    TaskType.SUPERVISOR_SYNTHESIS,
    TaskType.RESEARCH_REVIEW,
    TaskType.HYPOTHESIS_GENERATION,
    TaskType.RESEARCH_SUMMARY,
    TaskType.PATTERN_EXPLANATION,
    TaskType.CODE_ENGINEERING,
)

# Task → default (risk_tier, complexity) — deterministic base mapping (§5–§7).
TASK_DEFAULTS: dict[str, tuple[str, str]] = {
    TaskType.FAST_CLASSIFICATION: ("T0", "LOW"),
    TaskType.MARKET_SUMMARY: ("T0", "LOW"),
    TaskType.STRUCTURE_ANALYSIS: ("T1", "MEDIUM"),
    TaskType.LIQUIDITY_ANALYSIS: ("T1", "MEDIUM"),
    TaskType.MOMENTUM_ANALYSIS: ("T1", "MEDIUM"),
    TaskType.VOLATILITY_ANALYSIS: ("T1", "LOW"),
    TaskType.NEWS_MACRO_ANALYSIS: ("T1", "MEDIUM"),
    TaskType.ENTRY_ANALYSIS: ("T2", "MEDIUM"),
    TaskType.CHALLENGE: ("T3", "HIGH"),
    TaskType.SUPERVISOR_SYNTHESIS: ("T2", "HIGH"),
    TaskType.RESEARCH_REVIEW: ("T0", "MEDIUM"),
    TaskType.HYPOTHESIS_GENERATION: ("T4", "HIGH"),
    TaskType.RESEARCH_SUMMARY: ("T0", "LOW"),
    TaskType.PATTERN_EXPLANATION: ("T0", "MEDIUM"),
    TaskType.CODE_ENGINEERING: ("T0", "HIGH"),
}


class RiskTier:
    """AI-orchestration risk tier (NOT RiskGate risk) (§6)."""

    T0 = "T0"  # informational / non-trading
    T1 = "T1"  # analysis
    T2 = "T2"  # decision-support
    T3 = "T3"  # pre-entry / challenge
    T4 = "T4"  # high-consequence research/promotion support


_RISK_ORDER = ("T0", "T1", "T2", "T3", "T4")


class Complexity:
    """Complexity tiers (§7)."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


_COMPLEXITY_ORDER = ("LOW", "MEDIUM", "HIGH", "CRITICAL")


class Effort:
    """Normalized reasoning effort (§10)."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    MAX = "MAX"


# Forbidden authority fields an LLM must never be trusted with (§18).
FORBIDDEN_AUTHORITY_FIELDS = (
    "final_volume",
    "lot",
    "lot_size",
    "volume",
    "risk_override",
    "spread_override",
    "bypass_risk",
    "execute_mt5",
    "send_order",
    "place_order",
    "force_entry",
    "activate_strategy",
    "promote_live",
    "modify_risk_gate",
    "modify_execution",
    "risk_gate",
    "execution_engine",
    "max_exposure",
    "max_position_size",
    "active_strategy",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ModelRequest:
    """Structured request handed to the canonical ModelRouter (§1)."""

    request_id: str
    agent_role: str = ""
    task_type: str = TaskType.FAST_CLASSIFICATION
    risk_tier: str = ""
    complexity: str = ""
    urgency: str = "NORMAL"
    symbol: str = ""
    trading_context: dict[str, Any] = field(default_factory=dict)
    input_context: dict[str, Any] = field(default_factory=dict)
    required_capabilities: list[str] = field(default_factory=list)
    preferred_model: str = ""
    max_cost: Optional[float] = None
    max_tokens: int = 1024
    max_latency_s: float = 30.0
    allowed_providers: list[str] = field(default_factory=list)
    allow_escalation: bool = True
    effort_preference: str = ""
    cache_policy: str = "NO_CACHE"  # NO_CACHE | SNAPSHOT_SAFE
    cycle_id: str = ""
    parent_task_id: str = ""
    strategy_version: str = ""
    snapshot_version: str = ""

    def resolved_risk_tier(self) -> str:
        if self.risk_tier:
            return self.risk_tier
        return TASK_DEFAULTS.get(self.task_type, ("T0", "LOW"))[0]

    def resolved_complexity(self) -> str:
        if self.complexity:
            return self.complexity
        return TASK_DEFAULTS.get(self.task_type, ("T0", "LOW"))[1]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RoutingPolicyVersion:
    """Immutable routing policy version (§29, §47)."""

    policy_version: str
    created_at: str = field(default_factory=_now_iso)
    rules_hash: str = ""
    model_registry_version: str = "defaults"
    budget_policy_version: str = "v1"
    status: str = "ACTIVE"  # ACTIVE | SHADOW | RETIRED


@dataclass(frozen=True)
class PromptVersion:
    """Immutable prompt version (§21) — never overwritten."""

    prompt_id: str
    prompt_version: str
    agent_role: str = ""
    created_at: str = field(default_factory=_now_iso)
    hash: str = ""
    content: str = ""


@dataclass(frozen=True)
class ModelDecisionRecord:
    """Per-request AI provenance record (§30). UNKNOWN stays UNKNOWN."""

    request_id: str
    cycle_id: str = ""
    task_id: str = ""
    agent_role: str = ""
    provider: str = ""
    model_id: str = ""
    routing_policy_version: str = ""
    prompt_version: str = ""
    effort: str = ""
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cost: Optional[float] = None
    latency_s: Optional[float] = None
    retry_count: int = 0
    fallback_used: bool = False
    escalation_level: int = 0
    output_status: str = "UNKNOWN"  # VALID | INVALID | UNKNOWN | FAILED
    evidence_refs: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BudgetLedger:
    """Hierarchical token/cost budget with reservation (§11–§12)."""

    max_tokens: Optional[int] = None
    max_cost: Optional[float] = None
    reserved_tokens: int = 0
    reserved_cost: float = 0.0
    used_tokens: int = 0
    used_cost: float = 0.0
    # UNKNOWN cost is preserved as no-cost-limit rather than faked to 0 (§11).
    cost_known: bool = True

    def can_reserve(self, tokens: int, cost: Optional[float]) -> bool:
        if self.max_tokens is not None and self.reserved_tokens + tokens > self.max_tokens:
            return False
        if cost is not None and self.max_cost is not None and self.cost_known:
            if self.reserved_cost + cost > self.max_cost:
                return False
        return True

    def reserve(self, tokens: int, cost: Optional[float]) -> bool:
        if not self.can_reserve(tokens, cost):
            return False
        self.reserved_tokens += int(tokens)
        if cost is not None and self.cost_known:
            self.reserved_cost += float(cost)
        return True

    def commit(self, tokens: int, cost: Optional[float]) -> None:
        """Move a reservation into used; refund the difference."""
        self.reserved_tokens = max(0, self.reserved_tokens - int(tokens))
        self.used_tokens += int(tokens)
        if cost is not None and self.cost_known:
            self.reserved_cost = max(0.0, self.reserved_cost - float(cost))
            self.used_cost += float(cost)

    def remaining_tokens(self) -> Optional[int]:
        if self.max_tokens is None:
            return None
        return max(0, self.max_tokens - self.used_tokens - self.reserved_tokens)

    def snapshot(self) -> dict[str, Any]:
        return {
            "max_tokens": self.max_tokens,
            "max_cost": self.max_cost,
            "reserved_tokens": self.reserved_tokens,
            "used_tokens": self.used_tokens,
            "used_cost": self.used_cost,
            "cost_known": self.cost_known,
            "remaining_tokens": self.remaining_tokens(),
        }


@dataclass(frozen=True)
class CacheKey:
    """Snapshot-safe cache key (§25–§26). Includes snapshot version so a new
    market snapshot can never reuse a stale answer."""

    model_id: str
    prompt_version: str
    input_hash: str
    snapshot_version: str = ""
    strategy_version: str = ""

    def as_str(self) -> str:
        return "|".join(
            [
                self.model_id,
                self.prompt_version,
                self.input_hash,
                self.snapshot_version,
                self.strategy_version,
            ]
        )
