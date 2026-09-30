# -*- coding: utf-8 -*-
"""Canonical decision objects for Phase 2 (Evidence → Assessment → Candidate → State).

This module defines the structured evidence model that replaces the previous
ad-hoc signal/confidence outputs. Every agent result must be traceable to an
EvidenceItem; these form MarketAssessments, which produce SetupCandidates and
EntryAssessments; ultimately a DecisionState is synthesized with explicit
conflict/challenge handling before passing to Risk Gate.

Non-goal: Do not redesign trading strategy logic here. Only establish the
orchestration architecture through which future strategy logic will operate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

# ────────────────────────────────────────────────────────────────────────────
# Canonical evidence model (§8) — reuse and extend existing EvidenceItem
# ────────────────────────────────────────────────────────────────────────────


class EvidenceKind(str, Enum):
    """Classification of an evidence item."""

    FACT = "FACT"
    INTERPRETATION = "INTERPRETATION"
    RECOMMENDATION = "RECOMMENDATION"


class Freshness(str, Enum):
    """Coarse freshness buckets derived from age."""

    FRESH = "fresh"
    STALE = "stale"

    @classmethod
    def from_age(cls, age_seconds: Optional[float], fresh_threshold: float = 300.0) -> "Freshness":
        if age_seconds is None:
            return cls.FRESH
        return cls.FRESH if age_seconds <= fresh_threshold else cls.STALE


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class EvidenceItem:
    """A single validated piece of evidence with provenance & quality.

    Attributes:
        kind: FACT/INTERPRETATION/RECOMMENDATION.
        content: Human-readable claim or observation.
        source: Agent/specialist name that produced this evidence.
        timestamp: ISO UTC timestamp of generation.
        timeframe: Timeframe associated with this evidence (e.g., "M15").
        quality: Confidence score in [0, 1]. Higher means more trustworthy.
        freshness: Derived from age_seconds or FRESH when unknown.
        age_seconds: Seconds since generation; None if unknown.
        metric_name: Optional metric name (e.g., "atr", "volume").
        metric_value: Optional numeric metric value.
        domain: Logical domain (e.g., "regime", "structure", "momentum").

    Validation occurs in ``__post_init__``.
    """

    kind: EvidenceKind
    content: str
    source: str
    timestamp: str = field(default_factory=_now_iso)
    timeframe: str = ""
    quality: float = 0.5
    freshness: Freshness = Freshness.FRESH
    age_seconds: Optional[float] = None
    metric_name: Optional[str] = None
    metric_value: Optional[float] = None
    domain: str = ""
    # Provenance (Phase 3 §14): enables detecting correlated, NOT-independent
    # evidence (e.g. five agents re-deriving the same indicator fact).
    source_id: str = ""
    source_type: str = ""
    derived_from: str = ""

    def __post_init__(self) -> None:
        # Coerce string kind to enum.
        if not isinstance(self.kind, EvidenceKind):
            try:
                object.__setattr__(self, "kind", EvidenceKind(str(self.kind).upper()))
            except ValueError as exc:
                raise ValueError(f"Invalid evidence kind: {self.kind!r}") from exc

        if not self.content or not str(self.content).strip():
            raise ValueError("EvidenceItem content must be non-empty")

        if not (0.0 <= float(self.quality) <= 1.0):
            raise ValueError(f"EvidenceItem quality must be in [0, 1], got {self.quality}")
        object.__setattr__(self, "quality", float(self.quality))

        if self.age_seconds is not None:
            object.__setattr__(self, "freshness", Freshness.from_age(self.age_seconds))

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "content": self.content,
            "source": self.source,
            "timestamp": self.timestamp,
            "timeframe": self.timeframe,
            "quality": self.quality,
            "freshness": self.freshness.value,
            "age_seconds": self.age_seconds,
            "metric": (
                {"name": self.metric_name, "value": self.metric_value}
                if self.metric_name is not None
                else None
            ),
            "domain": self.domain,
            "provenance": {
                "source_id": self.source_id,
                "source_type": self.source_type,
                "derived_from": self.derived_from,
            },
        }


@dataclass
class EvidenceBundle:
    """An ordered collection of :class:`EvidenceItem` records."""

    _items: list[EvidenceItem] = field(default_factory=list)
    _id: str = field(default="")

    def __post_init__(self) -> None:
        if not self._id:
            object.__setattr__(self, "_id", f"bundle_{id(self):x}")

    def add(self, item: EvidenceItem) -> "EvidenceBundle":
        if not isinstance(item, EvidenceItem):
            raise TypeError("EvidenceBundle.add expects an EvidenceItem")
        self._items.append(item)
        return self

    def items(self) -> list[EvidenceItem]:
        return list(self._items)

    def filter(self, kind: EvidenceKind) -> list[EvidenceItem]:
        if not isinstance(kind, EvidenceKind):
            kind = EvidenceKind(str(kind).upper())
        return [item for item in self._items if item.kind == kind]

    def facts(self) -> list[EvidenceItem]:
        return self.filter(EvidenceKind.FACT)

    def interpretations(self) -> list[EvidenceItem]:
        return self.filter(EvidenceKind.INTERPRETATION)

    def recommendations(self) -> list[EvidenceItem]:
        return self.filter(EvidenceKind.RECOMMENDATION)

    def is_empty(self) -> bool:
        return len(self._items) == 0

    def __len__(self) -> int:
        return len(self._items)

    def is_stale(self, max_age: float) -> bool:
        for item in self._items:
            if item.age_seconds is None:
                continue
            if item.age_seconds > max_age:
                return True
        return False

    @property
    def id(self) -> str:
        return self._id or f"bundle_{id(self)}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "count": len(self._items),
            "items": [item.to_dict() for item in self._items],
        }


# ────────────────────────────────────────────────────────────────────────────
# Conflict model (§14)
# ────────────────────────────────────────────────────────────────────────────


@dataclass
class Conflict:
    """A structural conflict between evidence domains.

    Attributes:
        id: Unique ID for tracking resolution.
        severity: LOW/MEDIUM/HIGH/CRITICAL.
        description: Human-readable explanation.
        domains: List of conflicting domains (e.g., ["structure", "momentum"]).
        evidence_refs: References to evidence items causing conflict.
        resolution_status: UNRESOLVED / SECOND_OPINION / RESOLVED.
        secondary_evidence_ref: Ref to follow-up evidence if available.
    """

    id: str
    severity: str
    description: str
    domains: list[str]
    evidence_refs: list[str]
    resolution_status: str = "UNRESOLVED"
    secondary_evidence_ref: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "severity": self.severity,
            "description": self.description,
            "domains": self.domains,
            "evidence_refs": self.evidence_refs,
            "resolution_status": self.resolution_status,
            "secondary_evidence_ref": self.secondary_evidence_ref,
        }


# ────────────────────────────────────────────────────────────────────────────
# MarketAssessment (§7)
# ────────────────────────────────────────────────────────────────────────────


@dataclass
class MarketAssessment:
    """Canonical market assessment (describes the market, does NOT execute).

    Fields capture regime, structure, liquidity, momentum, volatility, news
    with explicit evidence backing and conflict tracking.
    """

    assessment_id: str
    trace_id: str
    symbol: str
    timestamp: str = field(default_factory=_now_iso)
    regime: str = "UNKNOWN"
    regime_strength: float = 0.0
    structure: str = "UNKNOWN"
    liquidity: str = "UNKNOWN"
    momentum: str = "UNKNOWN"
    volatility: str = "UNKNOWN"
    news: str = "UNKNOWN"
    evidence_bundle: Optional[EvidenceBundle] = None
    conflicts: list[Conflict] = field(default_factory=list)
    higher_timeframe_bias: str = "NEUTRAL"
    data_quality: float = 0.0
    data_freshness: Freshness = Freshness.FRESH

    def __post_init__(self) -> None:
        if self.evidence_bundle is None:
            object.__setattr__(self, "evidence_bundle", EvidenceBundle())

    def add_conflict(self, c: Conflict) -> None:
        self.conflicts.append(c)

    def mark_resolved(self, conflict_id: str, secondary_ref: Optional[str] = None) -> None:
        for c in self.conflicts:
            if c.id == conflict_id:
                object.__setattr__(c, "resolution_status", "RESOLVED")
                if secondary_ref:
                    object.__setattr__(c, "secondary_evidence_ref", secondary_ref)
                break

    def is_consistent(self) -> bool:
        unresolved = [c for c in self.conflicts if c.resolution_status != "RESOLVED"]
        return not unresolved

    def has_critical_conflicts(self) -> bool:
        return any(
            c.severity in ("HIGH", "CRITICAL") and c.resolution_status != "RESOLVED"
            for c in self.conflicts
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "assessment_id": self.assessment_id,
            "trace_id": self.trace_id,
            "symbol": self.symbol,
            "timestamp": self.timestamp,
            "regime": self.regime,
            "regime_strength": self.regime_strength,
            "structure": self.structure,
            "liquidity": self.liquidity,
            "momentum": self.momentum,
            "volatility": self.volatility,
            "news": self.news,
            "higher_timeframe_bias": self.higher_timeframe_bias,
            "data_quality": self.data_quality,
            "data_freshness": self.data_freshness.value,
            "conflicts": [c.to_dict() for c in self.conflicts],
            "has_consistent_state": self.is_consistent(),
            "has_critical_conflicts": self.has_critical_conflicts(),
        }


# ────────────────────────────────────────────────────────────────────────────
# SetupCandidate (§8)
# ────────────────────────────────────────────────────────────────────────────


@dataclass
class SetupCandidate:
    """A hypothesis setup that may become an entry opportunity.

    Not an order; just a candidate requiring further validation.
    """

    setup_id: str
    assessment_id: str
    symbol: str
    direction: str
    setup_type: str
    timeframe: str
    entry_context: str = ""
    invalidation: str = ""
    target_context: str = ""
    required_conditions: list[str] = field(default_factory=list)
    met_conditions: list[str] = field(default_factory=list)
    missing_conditions: list[str] = field(default_factory=list)
    supporting_evidence_refs: list[str] = field(default_factory=list)
    contradicting_evidence_refs: list[str] = field(default_factory=list)
    setup_quality: float = 0.0
    status: str = "DETECTED"
    created_at: str = field(default_factory=_now_iso)
    expires_at: Optional[str] = None
    challenges: list[str] = field(default_factory=list)

    def add_supporting(self, ref: str) -> None:
        self.supporting_evidence_refs.append(ref)

    def add_contradicting(self, ref: str) -> None:
        self.contradicting_evidence_refs.append(ref)

    def mark_met_condition(self, cond: str) -> None:
        if cond not in self.met_conditions:
            self.met_conditions.append(cond)
        if cond in self.missing_conditions:
            self.missing_conditions.remove(cond)

    def mark_missing_condition(self, cond: str) -> None:
        if cond not in self.missing_conditions:
            self.missing_conditions.append(cond)
        if cond in self.met_conditions:
            self.met_conditions.remove(cond)

    def challenge(self, reason: str) -> None:
        self.challenges.append(reason)
        self.status = "CHALLENGED"

    def validate_all(self) -> bool:
        return not self.missing_conditions

    def is_ready_for_entry(self) -> bool:
        return self.status == "READY_FOR_ENTRY" and self.validate_all()

    def to_dict(self) -> dict[str, Any]:
        return {
            "setup_id": self.setup_id,
            "assessment_id": self.assessment_id,
            "symbol": self.symbol,
            "direction": self.direction,
            "setup_type": self.setup_type,
            "timeframe": self.timeframe,
            "entry_context": self.entry_context,
            "invalidation": self.invalidation,
            "target_context": self.target_context,
            "required_conditions": self.required_conditions,
            "met_conditions": self.met_conditions,
            "missing_conditions": self.missing_conditions,
            "supporting_evidence_refs": self.supporting_evidence_refs,
            "contradicting_evidence_refs": self.contradicting_evidence_refs,
            "setup_quality": self.setup_quality,
            "status": self.status,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "challenges": self.challenges,
        }


# ────────────────────────────────────────────────────────────────────────────
# EntryAssessment (§9)
# ────────────────────────────────────────────────────────────────────────────


@dataclass
class EntryAssessment:
    """Evaluation of entry conditions for a specific setup (Phase 4 extended)."""

    entry_assessment_id: str
    setup_id: str
    symbol: str
    direction: str
    entry_zone_type: str = "ORDER_BLOCK"
    zone_touched: bool = False
    trigger_required: str = ""
    trigger_status: str = "MISSING"
    entry_quality: float = 0.0
    invalidation: str = ""
    expiry: Optional[str] = None
    supporting_evidence_refs: list[str] = field(default_factory=list)
    contradicting_evidence_refs: list[str] = field(default_factory=list)
    # Phase 4 section 23: explicit condition tracking (met/missing/blocking).
    triggers_detected: list[str] = field(default_factory=list)
    missing_triggers: list[str] = field(default_factory=list)
    blocking_conditions: list[str] = field(default_factory=list)
    trigger_time_ts: float = 0.0
    trigger_price: float = 0.0
    # Phase 4.5 §2 canonical entry contract (additive, back-compat defaults).
    zone_id: str = ""
    trigger_id: str = ""
    trigger_type: str = ""
    trigger_confirmed: bool = False
    evaluation_ts: float = 0.0
    fresh: bool = True
    expired: bool = False
    invalidated: bool = False
    mitigation_state: str = "FRESH"
    retest_count: int = 0
    timeframe_context: str = "M15"
    timeframe_trigger: str = "M5"
    timeframe_micro: str = "M1"
    evidence_refs: list[str] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_assessment_id": self.entry_assessment_id,
            "setup_id": self.setup_id,
            "symbol": self.symbol,
            "direction": self.direction,
            "entry_zone_type": self.entry_zone_type,
            "zone_touched": self.zone_touched,
            "trigger_status": self.trigger_status,
            "entry_quality": self.entry_quality,
            "triggers_detected": list(self.triggers_detected),
            "missing_triggers": list(self.missing_triggers),
            "blocking_conditions": list(self.blocking_conditions),
            "trigger_time_ts": self.trigger_time_ts,
            "trigger_price": self.trigger_price,
            "zone_id": self.zone_id,
            "trigger_id": self.trigger_id,
            "trigger_type": self.trigger_type,
            "trigger_confirmed": self.trigger_confirmed,
            "evaluation_ts": self.evaluation_ts,
            "fresh": self.fresh,
            "expired": self.expired,
            "invalidated": self.invalidated,
            "mitigation_state": self.mitigation_state,
            "retest_count": self.retest_count,
            "timeframe_context": self.timeframe_context,
            "timeframe_trigger": self.timeframe_trigger,
            "timeframe_micro": self.timeframe_micro,
            "evidence_refs": list(self.evidence_refs),
            "reason_codes": list(self.reason_codes),
        }


# ----------------------------------------------------------------------------
# ──────────────────────────────────────────
# Challenge model (§15)
# ────────────────────────────────────────────────────────────────────────────


@dataclass
class Challenge:
    """A targeted challenge to resolve a conflict or test a assumption.

    Attributes:
        challenge_id: Unique ID.
        setup_id: Setup being challenged.
        issue: What is being questioned.
        evidence_requested: Specific evidence needed from second opinion.
        assigned_to: Agent/specialist name to request second opinion.
        outcome: PENDING / PASSED / FAILED / UNSATISFACTORY.
        secondary_evidence_ref: Reference to follow-up evidence.
    """

    challenge_id: str
    setup_id: str
    issue: str
    evidence_requested: str
    assigned_to: str
    outcome: str = "PENDING"
    secondary_evidence_ref: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "challenge_id": self.challenge_id,
            "setup_id": self.setup_id,
            "issue": self.issue,
            "outcome": self.outcome,
            "assigned_to": self.assigned_to,
        }


# ────────────────────────────────────────────────────────────────────────────
# DecisionState (§10) — augmented with canonical fields
# ────────────────────────────────────────────────────────────────────────────


@dataclass
class DecisionState:
    """Authoritative AI decision state before Risk Gate.

    States: DETECTED, ANALYZING, CANDIDATE, VALIDATED, ARMED, WAITING_TRIGGER,
            EXECUTING, OPEN, MANAGING, CLOSED, REJECTED, EXPIRED.
    Pre-execution focus: DETECTED..WAITING_TRIGGER; no EXECUTING until actual
    execution lifecycle begins.
    """

    decision_id: str
    trace_id: str
    assessment_id: str
    setup_id: Optional[str]
    entry_assessment_id: Optional[str]
    symbol: str
    timestamp: str = field(default_factory=_now_iso)

    # Decision dimensions (canonical split from old bias/action)
    market_bias: str = "NEUTRAL"
    setup_type: str = "NONE"
    action: str = "WAIT"

    # Quality/separation dimensions (confidence semantics §11)
    evidence_quality: float = 0.0
    setup_quality: float = 0.0
    entry_quality: float = 0.0
    data_quality: float = 0.0
    risk_quality: float = 0.0
    legacy_confidence: float = 0.0

    rationale: str = ""
    evidence_bundle_ref: Optional[str] = None
    strategy_version: str = ""

    # Conflict & challenge tracking
    conflicts: list[Conflict] = field(default_factory=list)
    challenges: list[Challenge] = field(default_factory=list)

    # Lifecycle
    current_state: str = "DETECTED"

    # Required setup enforcement
    require_setup: bool = False

    def __post_init__(self) -> None:
        # No-op: objects are born in DETECTED; no transition required.
        pass

    def transition_to(self, new_state: str) -> bool:
        """Attempt state transition; reject invalid transitions."""
        valid = {
            "DETECTED": ["ANALYZING", "REJECTED"],
            "ANALYZING": ["CANDIDATE", "REJECTED"],
            "CANDIDATE": ["VALIDATED", "REJECTED"],
            "VALIDATED": ["ARMED", "REJECTED"],
            "ARMED": ["WAITING_TRIGGER", "EXPIRED"],
            "WAITING_TRIGGER": ["EXECUTING", "EXPIRED"],
            "EXECUTING": ["OPEN"],
            "OPEN": ["MANAGING"],
            "MANAGING": ["CLOSED"],
            "CLOSED": [],  # terminal
            "REJECTED": [],  # terminal
            "EXPIRED": [],  # terminal
        }
        allowed = valid.get(self.current_state, [])
        if new_state not in allowed:
            return False
        object.__setattr__(self, "current_state", new_state)
        return True

    def is_valid_transition(self, new_state: str) -> bool:
        if new_state == self.current_state:
            return True
        valid = {
            "DETECTED": ["ANALYZING", "REJECTED"],
            "ANALYZING": ["CANDIDATE", "REJECTED"],
            "CANDIDATE": ["VALIDATED", "REJECTED"],
            "VALIDATED": ["ARMED", "REJECTED"],
            "ARMED": ["WAITING_TRIGGER", "EXPIRED"],
            "WAITING_TRIGGER": ["EXECUTING", "EXPIRED"],
            "EXECUTING": ["OPEN"],
            "OPEN": ["MANAGING"],
            "MANAGING": ["CLOSED"],
            "CLOSED": [],
            "REJECTED": [],
            "EXPIRED": [],
        }
        return new_state in valid.get(self.current_state, [])

    def state_machine_valid_transition(self, new_state: str) -> None:
        if not self.is_valid_transition(new_state):
            raise ValueError(f"Invalid transition {self.current_state} → {new_state}")

    def add_conflict(self, c: Conflict) -> None:
        self.conflicts.append(c)

    def add_challenge(self, ch: Challenge) -> None:
        self.challenges.append(ch)

    def mark_rejected(self, reason: str) -> None:
        object.__setattr__(self, "rationale", reason)
        self.transition_to("REJECTED")

    def mark_expired(self, reason: str = "") -> None:
        object.__setattr__(self, "rationale", reason)
        self.transition_to("EXPIRED")

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "trace_id": self.trace_id,
            "assessment_id": self.assessment_id,
            "setup_id": self.setup_id,
            "entry_assessment_id": self.entry_assessment_id,
            "symbol": self.symbol,
            "timestamp": self.timestamp,
            "market_bias": self.market_bias,
            "setup_type": self.setup_type,
            "action": self.action,
            "evidence_quality": self.evidence_quality,
            "setup_quality": self.setup_quality,
            "entry_quality": self.entry_quality,
            "data_quality": self.data_quality,
            "risk_quality": self.risk_quality,
            "legacy_confidence": self.legacy_confidence,
            "rationale": self.rationale,
            "evidence_bundle_ref": self.evidence_bundle_ref,
            "strategy_version": self.strategy_version,
            "conflicts": [c.to_dict() for c in self.conflicts],
            "challenges": [ch.to_dict() for ch in self.challenges],
            "current_state": self.current_state,
            "require_setup": self.require_setup,
        }
