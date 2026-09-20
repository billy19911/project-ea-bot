# -*- coding: utf-8 -*-
"""Strategy Lifecycle Governance — PRD_V2 §44.

Enforces the strategy lifecycle state machine and gates production promotion so
that **no AI can change production status on its own**. An AI (or operator) may
*propose* a promotion; only a fully-satisfied evidence + risk + test + audit
checklist actually performs it.

State machine (PRD §44)::

    DRAFT → EXPERIMENT → BACKTESTED → WALK_FORWARD_PASSED → PAPER → DEMO
          → CANDIDATE → APPROVED → PRODUCTION

Failure branch: any state → REJECTED → ARCHIVED.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

__all__ = [
    "LifecycleState",
    "StrategyVersion",
    "LifecycleGovernor",
    "PromotionProposal",
    "PromotionResult",
]


class LifecycleState(str, Enum):
    """Lifecycle states in forward progression order (PRD §44)."""

    DRAFT = "DRAFT"
    EXPERIMENT = "EXPERIMENT"
    BACKTESTED = "BACKTESTED"
    WALK_FORWARD_PASSED = "WALK_FORWARD_PASSED"
    PAPER = "PAPER"
    DEMO = "DEMO"
    CANDIDATE = "CANDIDATE"
    APPROVED = "APPROVED"
    PRODUCTION = "PRODUCTION"
    REJECTED = "REJECTED"
    ARCHIVED = "ARCHIVED"


# Forward progression order (REJECTED/ARCHIVED handled separately).
_FORWARD = [
    LifecycleState.DRAFT,
    LifecycleState.EXPERIMENT,
    LifecycleState.BACKTESTED,
    LifecycleState.WALK_FORWARD_PASSED,
    LifecycleState.PAPER,
    LifecycleState.DEMO,
    LifecycleState.CANDIDATE,
    LifecycleState.APPROVED,
    LifecycleState.PRODUCTION,
]

_TERMINAL = {LifecycleState.REJECTED, LifecycleState.ARCHIVED}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class StrategyVersion:
    """A governed strategy version (PRD §44 StrategyVersion object)."""

    strategy_id: str
    version: int
    parameters: dict[str, Any] = field(default_factory=dict)
    risk_policy_id: str = ""
    created_from: Optional[str] = None
    evidence: dict[str, str] = field(default_factory=dict)
    status: str = LifecycleState.DRAFT.value
    audit: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "version": self.version,
            "parameters": dict(self.parameters),
            "risk_policy_id": self.risk_policy_id,
            "created_from": self.created_from,
            "evidence": dict(self.evidence),
            "status": self.status,
            "created_at": self.created_at,
            "audit": list(self.audit),
        }


@dataclass
class PromotionProposal:
    """A proposal (possibly AI-generated) to advance a strategy version."""

    strategy_id: str
    version: int
    target: str
    proposed_by: str = "ai"
    reasons: str = ""


@dataclass
class PromotionResult:
    """Outcome of a promotion attempt."""

    approved: bool
    from_state: str
    to_state: str
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "approved": self.approved,
            "from_state": self.from_state,
            "to_state": self.to_state,
            "reasons": list(self.reasons),
        }


# States requiring the full promotion checklist.
_PRODUCTION_STATES = {LifecycleState.APPROVED, LifecycleState.PRODUCTION}
# Evidence keys needed before production promotion.
_REQUIRED_EVIDENCE = ("backtest", "walk_forward", "monte_carlo", "paper", "demo")


class LifecycleGovernor:
    """Governs strategy-version lifecycles with hard promotion gates (PRD §44)."""

    def __init__(self) -> None:
        self._versions: dict[tuple[str, int], StrategyVersion] = {}

    # ------------------------------------------------------------------
    # Registry
    # ------------------------------------------------------------------
    def register(self, version: StrategyVersion) -> StrategyVersion:
        """Register a new strategy version in DRAFT state."""
        key = (version.strategy_id, version.version)
        if key in self._versions:
            raise ValueError(f"Version {version.strategy_id} v{version.version} already exists")
        version.status = LifecycleState.DRAFT.value
        self._versions[key] = version
        return version

    def get(self, strategy_id: str, version: int) -> Optional[StrategyVersion]:
        return self._versions.get((strategy_id, version))

    # ------------------------------------------------------------------
    # Transitions
    # ------------------------------------------------------------------
    def advance(
        self,
        strategy_id: str,
        version: int,
        evidence: Optional[dict[str, str]] = None,
        actor: str = "system",
    ) -> StrategyVersion:
        """Advance a version one step along the forward state machine.

        Records an audit entry on every transition. Cannot advance beyond
        CANDIDATE without an explicit, gated promotion (see :meth:`propose`).
        """
        sv = self._require(strategy_id, version)
        if sv.status in (s.value for s in _TERMINAL):
            raise RuntimeError(f"Cannot advance a {sv.status} version.")
        current = LifecycleState(sv.status)
        idx = _FORWARD.index(current)
        if idx >= len(_FORWARD) - 1:
            raise RuntimeError("Already at PRODUCTION — cannot advance further.")
        if current in _PRODUCTION_STATES or _FORWARD[idx + 1] in _PRODUCTION_STATES:
            raise RuntimeError(
                "Advancing into APPROVED/PRODUCTION requires a gated promotion (propose())."
            )
        if evidence:
            sv.evidence.update(evidence)
        sv.status = _FORWARD[idx + 1].value
        self._audit(sv, f"advance to {sv.status}", actor)
        return sv

    def reject(
        self, strategy_id: str, version: int, reason: str, actor: str = "system"
    ) -> StrategyVersion:
        """Reject a version (any state → REJECTED)."""
        sv = self._require(strategy_id, version)
        sv.status = LifecycleState.REJECTED.value
        self._audit(sv, f"rejected: {reason}", actor)
        return sv

    def archive(self, strategy_id: str, version: int, actor: str = "system") -> StrategyVersion:
        """Archive a rejected version (REJECTED → ARCHIVED)."""
        sv = self._require(strategy_id, version)
        if sv.status != LifecycleState.REJECTED.value:
            raise RuntimeError("Only REJECTED versions can be archived.")
        sv.status = LifecycleState.ARCHIVED.value
        self._audit(sv, "archived", actor)
        return sv

    # ------------------------------------------------------------------
    # Gated production promotion
    # ------------------------------------------------------------------
    def propose(self, proposal: PromotionProposal) -> PromotionResult:
        """Evaluate a promotion *proposal* against the hard checklist.

        AI may propose, but the promotion only happens when ALL of the
        following hold (PRD §44):

        * validation evidence present (backtest, walk-forward, monte-carlo,
          paper, demo),
        * risk compatibility (a ``risk_policy_id`` is set),
        * test evidence present,
        * an audit record exists.

        A proposal that comes from ``ai`` with any missing item is refused —
        AI cannot change production status alone.
        """
        sv = self._require(proposal.strategy_id, proposal.version)
        target = proposal.target
        reasons: list[str] = []

        if target not in {s.value for s in _PRODUCTION_STATES}:
            # Non-production targets use the normal advance path.
            return PromotionResult(
                approved=False,
                from_state=sv.status,
                to_state=sv.status,
                reasons=["target is not a production state; use advance() instead"],
            )

        # Checklist evaluation.
        missing_evidence = [k for k in _REQUIRED_EVIDENCE if not sv.evidence.get(k)]
        if missing_evidence:
            reasons.append(f"missing evidence: {', '.join(missing_evidence)}")
        if not sv.risk_policy_id:
            reasons.append("missing risk compatibility (risk_policy_id)")
        if not sv.evidence.get("test"):
            reasons.append("missing test evidence")
        if not sv.audit:
            reasons.append("missing audit record")

        if reasons:
            # Record the refused proposal for auditability.
            self._audit(
                sv,
                f"promotion refused ({proposal.proposed_by}): {'; '.join(reasons)}",
                proposal.proposed_by,
            )
            return PromotionResult(
                approved=False, from_state=sv.status, to_state=sv.status, reasons=reasons
            )

        from_state = sv.status
        sv.status = target
        self._audit(
            sv, f"promotion approved ({proposal.proposed_by}) to {target}", proposal.proposed_by
        )
        return PromotionResult(
            approved=True,
            from_state=from_state,
            to_state=target,
            reasons=["all promotion checks passed"],
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _require(self, strategy_id: str, version: int) -> StrategyVersion:
        sv = self._versions.get((strategy_id, version))
        if sv is None:
            raise ValueError(f"Unknown strategy version {strategy_id} v{version}")
        return sv

    @staticmethod
    def _audit(sv: StrategyVersion, action: str, actor: str) -> None:
        sv.audit.append({"action": action, "actor": actor, "timestamp": _now()})
