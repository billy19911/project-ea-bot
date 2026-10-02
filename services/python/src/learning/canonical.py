# -*- coding: utf-8 -*-
"""Canonical learning & research records (Phase 5).
Immutable, JSONL-persistable dataclasses that make the learning pipeline
traceable end-to-end:
    DecisionSnapshot → TradeReview / DecisionReview → CounterfactualReview
    → PatternObservation → HypothesisRecord → ExperimentRecord
    → WalkForwardRecord → StrategyCandidateRecord → PromotionRecord
    → NegativeKnowledgeRecord
Safety rules enforced here:
* ``DecisionSnapshot`` is frozen and enforces
  ``information_timestamp <= decision_timestamp`` (§3) — future data can never
  be used to reconstruct a past decision input.
* No record can mutate a live strategy; StrategyCandidateRecord/PromotionRecord
  are proposals/decisions only (manual approval required).
* Nothing here touches RiskGate / MoneyManager / ExecutionEngine / MT5.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

__all__ = [
    "DecisionSnapshot",
    "TradeReview",
    "DecisionReview",
    "CounterfactualReview",
    "PatternObservation",
    "HypothesisRecord",
    "ExperimentRecord",
    "WalkForwardRecord",
    "StrategyCandidateRecord",
    "PromotionRecord",
    "NegativeKnowledgeRecord",
    # outcome taxonomies
    "OUTCOME_CLASSES",
    "COUNTERFACTUAL_OUTCOMES",
    "KNOWLEDGE_STATES",
    "HYPOTHESIS_STATUSES",
]
# Decision-quality × outcome taxonomy (§4).
OUTCOME_CLASSES = (
    "GOOD_DECISION_LOSS",
    "BAD_DECISION_LOSS",
    "GOOD_DECISION_WIN",
    "BAD_DECISION_WIN",
    "BREAKEVEN",
)
# Counterfactual outcomes (§6).
COUNTERFACTUAL_OUTCOMES = (
    "WOULD_HAVE_WON",
    "WOULD_HAVE_LOST",
    "WOULD_HAVE_BEEN_BREAKEVEN",
    "WOULD_NOT_HAVE_TRIGGERED",
    "INSUFFICIENT_FUTURE_DATA",
    "INVALID_COUNTERFACTUAL",
)
# Negative-knowledge states (§24).
KNOWLEDGE_STATES = ("KNOWN_FALSE", "KNOWN_UNCERTAIN", "KNOWN_SUPPORTED")
# Hypothesis statuses (§10).
HYPOTHESIS_STATUSES = (
    "DRAFT",
    "TESTABLE",
    "TESTING",
    "SUPPORTED",
    "WEAK",
    "REJECTED",
    "SUPERSEDED",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_ts(value: Any) -> float:
    """Best-effort epoch seconds from ISO string / number (0.0 on failure)."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        s = str(value).replace("Z", "+00:00")
        return datetime.fromisoformat(s).timestamp()
    except (ValueError, TypeError):
        return 0.0


@dataclass(frozen=True)
class DecisionSnapshot:
    """Immutable point-in-time record of a decision's inputs (§3).
    ``information_timestamp`` MUST be <= ``decision_timestamp``: a snapshot may
    never embed data known only after the decision. Enforced in ``__post_init__``
    (raise on violation) — this is the anti-lookahead spine.
    """

    snapshot_id: str
    event_id: str
    decision_timestamp: str
    decision_state: str = ""
    direction: str = ""
    setup_id: str = ""
    trigger_id: str = ""
    market_snapshot_id: str = ""
    information_timestamp: str = ""
    strategy_version: str = ""
    config_version: str = ""
    evidence_refs: list[str] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)
    risk_decision: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.information_timestamp:
            object.__setattr__(self, "information_timestamp", self.decision_timestamp)
        info_ts = _parse_ts(self.information_timestamp)
        dec_ts = _parse_ts(self.decision_timestamp)
        if info_ts and dec_ts and info_ts > dec_ts:
            raise ValueError(
                "DecisionSnapshot violates point-in-time: information_timestamp "
                f"({self.information_timestamp}) > decision_timestamp "
                f"({self.decision_timestamp})"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TradeReview:
    """Post-trade review separating outcome from decision quality (§4)."""

    review_id: str
    trade_id: str
    setup_id: str = ""
    setup_identity: str = ""
    trigger_id: str = ""
    strategy_version: str = ""
    entry_timestamp: str = ""
    exit_timestamp: str = ""
    entry_price: float = 0.0
    exit_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    planned_risk: float = 0.0
    realized_risk: float = 0.0
    planned_r: float = 0.0
    realized_r: float = 0.0
    gross_pnl: float = 0.0
    net_pnl: float = 0.0
    commission: float = 0.0
    spread_cost: float = 0.0
    slippage: float = 0.0
    mae: float = 0.0
    mfe: float = 0.0
    holding_duration_s: float = 0.0
    zone_type: str = ""
    trigger_type: str = ""
    mitigation_state: str = ""
    retest_count: int = 0
    regime: str = ""
    session: str = ""
    volatility_state: str = ""
    news_state: str = ""
    decision_quality: float = 0.0
    entry_quality: float = 0.0
    risk_quality: float = 0.0
    execution_quality: float = 0.0
    outcome_class: str = ""
    reason_codes: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DecisionReview:
    """Review of a NON-trade decision (WAIT/NO_TRADE/REJECTED/EXPIRED/INVALID) (§5)."""

    review_id: str
    event_id: str
    decision_timestamp: str
    decision_state: str  # WAIT / NO_TRADE / REJECTED / EXPIRED / INVALIDATED
    direction: str = ""
    setup_id: str = ""
    setup_identity: str = ""
    zone_type: str = ""
    trigger_type: str = ""
    reason_codes: list[str] = field(default_factory=list)
    blocking_conditions: list[str] = field(default_factory=list)
    missing_conditions: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    risk_decision: dict[str, Any] = field(default_factory=dict)
    strategy_version: str = ""
    created_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CounterfactualReview:
    """Point-in-time-safe counterfactual of a skipped decision (§6).
    ``entry_reference_price`` MUST be the price known at ``decision_timestamp``,
    never a later best price. Outcome is one of COUNTERFACTUAL_OUTCOMES.
    """

    counterfactual_id: str
    review_id: str
    setup_id: str = ""
    direction: str = ""
    decision_timestamp: str = ""
    entry_reference_price: float = 0.0
    hypothetical_sl: float = 0.0
    hypothetical_tp: float = 0.0
    outcome: str = "INVALID_COUNTERFACTUAL"
    realized_move_r: float = 0.0
    future_data_used_up_to: str = ""
    reason_codes: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=_now_iso)

    def __post_init__(self) -> None:
        if self.outcome not in COUNTERFACTUAL_OUTCOMES:
            raise ValueError(f"invalid counterfactual outcome {self.outcome!r}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PatternObservation:
    """Statistical observation over a grouping (observation, NOT strategy) (§7)."""

    pattern_id: str
    grouping: dict[str, Any]  # symbol/direction/zone_type/trigger_type/regime/...
    sample_size: int = 0
    wins: int = 0
    losses: int = 0
    breakevens: int = 0
    average_r: float = 0.0
    median_r: float = 0.0
    expectancy: float = 0.0
    profit_factor: float = 0.0
    avg_mae: float = 0.0
    avg_mfe: float = 0.0
    max_drawdown: float = 0.0
    uncertainty: float = 0.0
    status: str = "INSUFFICIENT_SAMPLE"  # INSUFFICIENT_SAMPLE | OBSERVED
    created_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HypothesisRecord:
    """A testable, falsifiable hypothesis with lineage (§10)."""

    hypothesis_id: str
    statement: str
    source_pattern_ids: list[str] = field(default_factory=list)
    source_review_ids: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    variables: list[str] = field(default_factory=list)
    expected_effect: str = ""
    falsification_condition: str = ""
    status: str = "DRAFT"
    created_at: str = field(default_factory=_now_iso)

    def __post_init__(self) -> None:
        if self.status not in HYPOTHESIS_STATUSES:
            raise ValueError(f"invalid hypothesis status {self.status!r}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExperimentRecord:
    """A reproducible experiment definition (§11). Never overwritten."""

    experiment_id: str
    hypothesis_id: str
    strategy_version_baseline: str = ""
    parameter_overrides: dict[str, Any] = field(default_factory=dict)
    dataset_id: str = ""
    data_window: str = ""
    symbol_scope: list[str] = field(default_factory=list)
    timeframe_scope: list[str] = field(default_factory=list)
    cost_model: dict[str, Any] = field(default_factory=dict)
    slippage_model: dict[str, Any] = field(default_factory=dict)
    random_seed: int = 0
    status: str = "pending"
    created_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WalkForwardRecord:
    """Walk-forward validation record with TRAIN < VALIDATION < TEST (§14)."""

    run_id: str
    strategy_version: str = ""
    train_window: str = ""
    validation_window: str = ""
    test_window: str = ""
    folds: int = 0
    parameter_selection_method: str = ""
    per_fold_results: list[dict[str, Any]] = field(default_factory=list)
    aggregate_results: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StrategyCandidateRecord:
    """A candidate strategy proposal — NEVER auto-activated (§16)."""

    candidate_id: str
    parent_strategy_version: str = ""
    hypothesis_ids: list[str] = field(default_factory=list)
    experiment_ids: list[str] = field(default_factory=list)
    parameter_set: dict[str, Any] = field(default_factory=dict)
    logic_version: str = ""
    trigger_version: str = ""
    backtest_results: dict[str, Any] = field(default_factory=dict)
    walkforward_results: dict[str, Any] = field(default_factory=dict)
    paper_results: dict[str, Any] = field(default_factory=dict)
    demo_results: dict[str, Any] = field(default_factory=dict)
    status: str = "DRAFT"
    created_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        """Serialise; includes a hard non-activation marker for safety audits."""
        data = asdict(self)
        data["activation"] = "PROPOSAL_ONLY"
        data["requires_manual_approval"] = True
        return data


@dataclass(frozen=True)
class PromotionRecord:
    """Deterministic promotion decision record — requires human approval (§17–§18)."""

    promotion_id: str
    candidate_id: str
    from_status: str = ""
    to_status: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    gate_passed: bool = False
    approval_required: bool = True
    approved_by: str = ""  # empty until a human approves
    decision: str = "PENDING"  # PENDING / APPROVED / REJECTED
    reason_codes: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class NegativeKnowledgeRecord:
    """Explicit KNOWN_FALSE / KNOWN_UNCERTAIN / KNOWN_SUPPORTED ledger (§24)."""

    record_id: str
    subject_type: str  # hypothesis | pattern | experiment | candidate
    subject_id: str
    state: str
    detail: str = ""
    created_at: str = field(default_factory=_now_iso)

    def __post_init__(self) -> None:
        if self.state not in KNOWLEDGE_STATES:
            raise ValueError(f"invalid knowledge state {self.state!r}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
