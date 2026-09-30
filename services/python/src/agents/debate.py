# -*- coding: utf-8 -*-
"""Bounded debate engine (Phase 3 §8–§10, §23).

Implements a TARGETED, BOUNDED debate loop:

    INITIAL_ANALYSIS → HYPOTHESIS → CONFLICT_DETECTION → TARGETED_CHALLENGE
    → SPECIALIST_RESPONSE → RESOLUTION

Rules:
* Only the RELEVANT specialists are re-queried for a given conflict (never the
  whole committee).
* ``max_rounds`` (default 2) bounds the loop — no infinite LLM/agent loops.
* Termination outcomes: RESOLVED / WAIT / INVALID / EXPIRED / DATA_UNAVAILABLE.
* Conflict severity: LOW=observation, MEDIUM=challenge recommended,
  HIGH=challenge required, CRITICAL=trade blocked unless resolved.
* FAIL-CLOSED: a failure to resolve a HIGH/CRITICAL conflict yields WAIT
  (never an automatic trade).
* This engine never votes and never executes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from .canonical import Challenge, Conflict, SetupCandidate
from .roles import CHALLENGE_FAILED, CHALLENGE_PASSED, CHALLENGE_UNRESOLVED, ChallengerRole

logger = logging.getLogger(__name__)

__all__ = [
    "DebateRecord",
    "DebateOutcome",
    "DebateConfig",
    "DebateEngine",
]

# Termination outcomes (§10).
OUTCOME_RESOLVED = "RESOLVED"
OUTCOME_WAIT = "WAIT"
OUTCOME_INVALID = "INVALID"
OUTCOME_EXPIRED = "EXPIRED"
OUTCOME_DATA_UNAVAILABLE = "DATA_UNAVAILABLE"

# Conflict severities (§11).
SEV_LOW = "LOW"
SEV_MEDIUM = "MEDIUM"
SEV_HIGH = "HIGH"
SEV_CRITICAL = "CRITICAL"

# Severities that REQUIRE a challenge before progression.
_CHALLENGE_REQUIRED = (SEV_HIGH, SEV_CRITICAL)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    import uuid

    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@dataclass
class DebateConfig:
    """Centralized committee/debate limits (Phase 3 §17)."""

    max_rounds: int = 2
    max_challenges_per_cycle: int = 3
    max_specialists_per_cycle: int = 6
    max_total_calls: int = 12
    max_cycle_duration_s: float = 30.0


@dataclass
class DebateRecord:
    """A durable, traceable record of one debate round (§23)."""

    debate_id: str
    setup_id: str
    round: int
    trigger: str
    hypothesis: str
    challenge: str
    challenger: str
    response: str
    evidence_refs: list[str] = field(default_factory=list)
    conflict_refs: list[str] = field(default_factory=list)
    outcome: str = ""
    timestamp: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "debate_id": self.debate_id,
            "setup_id": self.setup_id,
            "round": self.round,
            "trigger": self.trigger,
            "hypothesis": self.hypothesis,
            "challenge": self.challenge,
            "challenger": self.challenger,
            "response": self.response,
            "evidence_refs": list(self.evidence_refs),
            "conflict_refs": list(self.conflict_refs),
            "outcome": self.outcome,
            "timestamp": self.timestamp,
        }


@dataclass
class DebateOutcome:
    """Result of a debate run."""

    outcome: str
    rounds: int
    records: list[DebateRecord] = field(default_factory=list)
    unresolved_conflicts: list[Conflict] = field(default_factory=list)
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "rounds": self.rounds,
            "records": [r.to_dict() for r in self.records],
            "unresolved_conflicts": [c.to_dict() for c in self.unresolved_conflicts],
            "rationale": self.rationale,
        }


class DebateEngine:
    """Runs a bounded, targeted debate to resolve conflicts for a setup."""

    def __init__(
        self,
        config: Optional[DebateConfig] = None,
        challenger: Optional[ChallengerRole] = None,
        specialist_runner: Optional[Callable[[str, dict[str, Any]], Any]] = None,
    ) -> None:
        """
        Args:
            config: Committee/debate limits.
            challenger: Challenger role (defaults to a fresh ChallengerRole).
            specialist_runner: Optional ``(role, context) -> RoleOutput`` used to
                fetch a TARGETED second opinion from a specific specialist. When
                None, targeted re-analysis is recorded but not auto-run.
        """
        self.config = config or DebateConfig()
        self.challenger = challenger or ChallengerRole()
        self.specialist_runner = specialist_runner

    def run(
        self,
        setup: SetupCandidate,
        conflicts: list[Conflict],
        *,
        hypothesis_direction: str = "",
        role_outputs: Optional[dict[str, Any]] = None,
        context: Optional[dict[str, Any]] = None,
    ) -> DebateOutcome:
        """Run the bounded debate loop for ``setup`` given ``conflicts``."""
        records: list[DebateRecord] = []
        role_outputs = role_outputs or {}
        context = dict(context or {})
        context.setdefault(
            "setup",
            {
                "direction": setup.direction,
                "missing_conditions": setup.missing_conditions,
                "invalidation": setup.invalidation,
                "supporting_evidence_refs": setup.supporting_evidence_refs,
            },
        )
        context.setdefault("hypothesis_direction", hypothesis_direction or setup.direction)
        context.setdefault("role_outputs", role_outputs)

        # Only HIGH/CRITICAL (and optionally MEDIUM) conflicts trigger debate.
        actionable = [c for c in conflicts if c.resolution_status != "RESOLVED"]
        challenge_needed = [c for c in actionable if c.severity in _CHALLENGE_REQUIRED]
        medium = [c for c in actionable if c.severity == SEV_MEDIUM]

        # No conflicts → trivially resolved.
        if not actionable:
            return DebateOutcome(
                outcome=OUTCOME_RESOLVED,
                rounds=0,
                rationale="No unresolved conflicts.",
            )

        max_rounds = max(1, int(self.config.max_rounds))
        max_challenges = max(1, int(self.config.max_challenges_per_cycle))
        challenges_run = 0
        current = challenge_needed or medium
        outcome = OUTCOME_WAIT

        for round_no in range(1, max_rounds + 1):
            if challenges_run >= max_challenges:
                break
            if not current:
                break

            # Targeted challenge against the most severe conflict.
            target = sorted(current, key=lambda c: _severity_rank(c.severity), reverse=True)[0]
            challenge_run_record = self._run_one(
                setup, target, round_no, hypothesis_direction, role_outputs, context
            )
            records.append(challenge_run_record)
            challenges_run += 1

            # Interpret the challenger outcome.
            ch_outcome = challenge_run_record.outcome
            if ch_outcome == CHALLENGE_FAILED:
                # Hypothesis refuted → INVALID.
                setup.status = "INVALID"
                outcome = OUTCOME_INVALID
                return DebateOutcome(
                    outcome=outcome,
                    rounds=round_no,
                    records=records,
                    unresolved_conflicts=[target],
                    rationale=f"Challenger refuted hypothesis: {challenge_run_record.challenge}",
                )
            if ch_outcome == CHALLENGE_PASSED:
                # This conflict survived the challenge → mark resolved.
                target.resolution_status = "RESOLVED"
                current = [c for c in current if c is not target]
                if not current:
                    outcome = OUTCOME_RESOLVED
                    break
            else:
                # UNRESOLVED → record and (bounded) re-challenge the next round.
                target.resolution_status = "SECOND_OPINION"

        # Loop ended with remaining conflicts → WAIT (fail-closed).
        unresolved = [c for c in conflicting_list(actionable) if c.resolution_status != "RESOLVED"]
        if outcome == OUTCOME_RESOLVED and not unresolved:
            return DebateOutcome(
                outcome=OUTCOME_RESOLVED,
                rounds=len(records),
                records=records,
                rationale="All actionable conflicts resolved by targeted challenge.",
            )
        return DebateOutcome(
            outcome=OUTCOME_WAIT,
            rounds=len(records),
            records=records,
            unresolved_conflicts=unresolved,
            rationale=(
                f"Debate reached max_rounds={max_rounds} with "
                f"{len(unresolved)} unresolved conflict(s) → WAIT."
            ),
        )

    # ------------------------------------------------------------------
    def _run_one(
        self,
        setup: SetupCandidate,
        conflict: Conflict,
        round_no: int,
        hypothesis_direction: str,
        role_outputs: dict[str, Any],
        context: dict[str, Any],
    ) -> DebateRecord:
        """Run ONE targeted challenge round and record it."""
        # Target the OPPOSING domain's specialist if known.
        opposing = conflict.domains[0] if conflict.domains else "structure"
        issue = conflict.description

        ch_context = dict(context)
        ch_context["setup"] = {
            "direction": setup.direction,
            "missing_conditions": setup.missing_conditions,
            "invalidation": setup.invalidation,
            "supporting_evidence_refs": setup.supporting_evidence_refs,
        }
        ch_context["hypothesis_direction"] = hypothesis_direction or setup.direction
        ch_context["role_outputs"] = role_outputs

        ch_output = self.challenger.analyze(ch_context)
        outcome = str(ch_output.role_specific.get("outcome", CHALLENGE_UNRESOLVED))

        # Targeted second opinion, if a runner is wired.
        response = ""
        if self.specialist_runner is not None and outcome == CHALLENGE_UNRESOLVED:
            try:
                follow_up = self.specialist_runner(opposing, ch_context)
                response = getattr(follow_up, "signal", "") or ""
            except Exception as exc:  # noqa: BLE001 - debate must never break
                logger.warning("Second-opinion runner failed: %s", exc)

        Challenge(
            challenge_id=_new_id("chl"),
            setup_id=setup.setup_id,
            issue=issue,
            evidence_requested=(
                f"Is {opposing} evidence strong enough to overturn the "
                f"{setup.direction} hypothesis?"
            ),
            assigned_to=opposing,
            outcome=outcome,
        )
        setup.challenge(issue)

        return DebateRecord(
            debate_id=_new_id("dbt"),
            setup_id=setup.setup_id,
            round=round_no,
            trigger=conflict.severity,
            hypothesis=f"{setup.direction} {setup.setup_type}",
            challenge=issue,
            challenger=self.challenger.role,
            response=response,
            evidence_refs=list(conflict.evidence_refs),
            conflict_refs=[conflict.id],
            outcome=outcome,
        )


def _severity_rank(severity: str) -> int:
    return {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}.get(str(severity).upper(), 0)


def conflicting_list(conflicts: list[Conflict]) -> list[Conflict]:
    """Return conflicts that are not yet RESOLVED."""
    return [c for c in conflicts if c.resolution_status != "RESOLVED"]
