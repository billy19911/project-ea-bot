# -*- coding: utf-8 -*-
"""Production committee orchestrator (Phase 3 §16, §24–§25).
Ties the Phase 3 pieces into one traceable pipeline:
    EVENT → classify/dispatch → relevant ROLES → evidence →
    MarketAssessment → SetupCandidate → conflict detection →
    bounded DEBATE → DecisionState → (pipeline) Risk Gate → Execution.
Deterministic boundary: this orchestrator NEVER executes, NEVER sets volume,
and NEVER touches MT5. It produces canonical structure + a decision state that
the pipeline uses to *decide whether to build a proposal*. The Risk Gate
remains the sole authority on risk; the ExecutionEngine the sole authority on
execution.
The orchestrator is additive: existing supervisor/synthesis paths continue to
work. This provides the canonical committee path for the runtime to opt into.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .canonical import DecisionState, EntryAssessment, MarketAssessment, SetupCandidate
from .committee import CommitteeCoordinator
from .debate import OUTCOME_INVALID, OUTCOME_WAIT, DebateConfig, DebateEngine
from .event_dispatch import DispatchDecision, decide_dispatch
from .roles import (
    ROLE_CHALLENGER,
    ROLE_ENTRY,
    ROLE_LIQUIDITY,
    ROLE_MOMENTUM,
    ROLE_NEWS,
    ROLE_REGIME,
    ROLE_STRUCTURE,
    ROLE_VOLATILITY,
    EntryRole,
    RoleOutput,
)

logger = logging.getLogger(__name__)
__all__ = [
    "CommitteeResult",
    "CommitteeOrchestrator",
]
# Directional domains that feed bias.
_DIRECTIONAL = (ROLE_REGIME, ROLE_STRUCTURE, ROLE_LIQUIDITY, ROLE_MOMENTUM)
# Bias vocabulary → decision direction.
_BULL = {"BULLISH", "STRONG_BULLISH", "BUY", "TRENDING_UP", "UP"}
_BEAR = {"BEARISH", "STRONG_BEARISH", "SELL", "TRENDING_DOWN", "DOWN"}


@dataclass
class CommitteeResult:
    """Traceable result of one committee run (§24)."""

    dispatch: Optional[DispatchDecision] = None
    assessment: Optional[MarketAssessment] = None
    setup: Optional[SetupCandidate] = None
    entry: Optional[EntryAssessment] = None
    decision: Optional[DecisionState] = None
    debate: Optional[dict[str, Any]] = None
    role_outputs: dict[str, RoleOutput] = field(default_factory=dict)
    ran_committee: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "ran_committee": self.ran_committee,
            "dispatch": (
                {
                    "run": self.dispatch.run_committee,
                    "level": self.dispatch.level_name,
                    "roles": list(self.dispatch.roles),
                    "reason": self.dispatch.reason,
                }
                if self.dispatch
                else None
            ),
            "assessment": self.assessment.to_dict() if self.assessment else None,
            "setup": self.setup.to_dict() if self.setup else None,
            "entry": self.entry.to_dict() if self.entry else None,
            "decision": self.decision.to_dict() if self.decision else None,
            "debate": self.debate,
            "role_outputs": {k: v.to_dict() for k, v in self.role_outputs.items()},
        }


class CommitteeOrchestrator:
    """Runs the evidence-driven committee with bounded debate."""

    def __init__(
        self,
        roles: dict[str, Any],
        *,
        config: Optional[DebateConfig] = None,
        coordinator: Optional[CommitteeCoordinator] = None,
        challenger: Optional[Any] = None,
        specialist_runner: Optional[Callable[[str, dict[str, Any]], Any]] = None,
    ) -> None:
        """
        Args:
            roles: Mapping canonical role id → role object with ``.analyze(ctx)``.
            config: Committee/budget limits (Phase 3 §17).
            coordinator: CommitteeCoordinator for assessment/decision building.
            challenger: Challenger role (defaulted by DebateEngine when None).
            specialist_runner: optional targeted second-opinion runner.
        """
        self.roles = dict(roles or {})
        self.config = config or DebateConfig()
        self.coordinator = coordinator or CommitteeCoordinator()
        self.debate = DebateEngine(
            config=self.config, challenger=challenger, specialist_runner=specialist_runner
        )

    # ------------------------------------------------------------------
    def run(
        self,
        context: dict[str, Any],
        *,
        event_type: str = "",
        state_changed: bool = True,
        existing_setup: Optional[SetupCandidate] = None,
    ) -> CommitteeResult:
        """Run one committee cycle for ``context`` (never raises)."""
        try:
            return self._run(context, event_type, state_changed, existing_setup)
        except Exception as exc:  # noqa: BLE001 - committee must never break the loop
            logger.exception("Committee orchestrator failed: %s", exc)
            return CommitteeResult(ran_committee=False)

    def _run(
        self,
        context: dict[str, Any],
        event_type: str,
        state_changed: bool,
        existing_setup: Optional[SetupCandidate],
    ) -> CommitteeResult:
        symbol = str(context.get("symbol") or "")
        trace_id = str(context.get("trace_id") or context.get("event_id") or "")
        # ── Event dispatch (§15–§16) ────────────────────────────────────
        dispatch = decide_dispatch(
            event_type or str(context.get("event_type") or ""),
            state_changed=state_changed,
            has_setup=existing_setup is not None,
        )
        if not dispatch.run_committee:
            return CommitteeResult(dispatch=dispatch, ran_committee=False)
        # ── Level 1: relevant specialists only ──────────────────────────
        wanted_roles = dispatch.roles or (
            ROLE_REGIME,
            ROLE_STRUCTURE,
            ROLE_LIQUIDITY,
            ROLE_MOMENTUM,
            ROLE_VOLATILITY,
            ROLE_NEWS,
        )
        role_outputs: dict[str, RoleOutput] = {}
        for role_id in wanted_roles[: self.config.max_specialists_per_cycle]:
            if role_id == ROLE_CHALLENGER:
                continue
            role = self.roles.get(role_id)
            if role is None:
                continue
            role_outputs[role_id] = role.analyze(context)
        # News is always considered (UNKNOWN must be surfaced, §3.6/§11).
        if ROLE_NEWS not in role_outputs and ROLE_NEWS in self.roles:
            role_outputs[ROLE_NEWS] = self.roles[ROLE_NEWS].analyze(context)
        # ── Level 2: Market Lead → assessment ───────────────────────────
        agent_results = {rid: ro.to_dict() for rid, ro in role_outputs.items()}
        assessment = self.coordinator.build_assessment(symbol, trace_id, agent_results)
        # ── Setup candidate (only when evidence is directional) ─────────
        bias = self._derive_bias(role_outputs)
        setup = existing_setup
        if setup is None and bias in ("BULLISH", "BEARISH"):
            setup = self._build_setup(symbol, assessment, role_outputs, bias)
        # ── Level 3: conflict detection + bounded debate ────────────────
        debate_dict = None
        if setup is not None:
            conflicts = list(assessment.conflicts)
            if conflicts:
                outcome = self.debate.run(
                    setup,
                    conflicts,
                    hypothesis_direction=setup.direction,
                    role_outputs=role_outputs,
                    context=context,
                )
                debate_dict = outcome.to_dict()
                # Map debate outcome to assessment resolution.
                for c in outcome.unresolved_conflicts:
                    c.resolution_status = "UNRESOLVED"
                if outcome.outcome in (OUTCOME_INVALID, OUTCOME_WAIT):
                    # Fail-closed: do NOT promote to a tradeable validate.
                    setup.status = "CHALLENGED" if outcome.outcome == OUTCOME_WAIT else "INVALID"
        # ── Level 4: entry committee (only when setup exists) ───────────
        # Phase 4.5 §4: the deterministic Trigger Engine evaluates the zone
        # series FIRST; its TriggerResult is passed to EntryRole as the
        # authoritative `trigger_result`. EntryRole without it stays WAIT.
        entry = None
        entry_trigger_result: dict[str, Any] = {}
        if setup is not None and setup.status not in ("INVALID",):
            entry_trigger_result = self._evaluate_entry_triggers(symbol, setup, context)
            entry_role = self.roles.get(ROLE_ENTRY)
            if entry_role is None:
                entry_role = EntryRole()
            ctx = dict(context)
            ctx["setup"] = {
                "missing_conditions": setup.missing_conditions,
                "direction": setup.direction,
                "invalidation": setup.invalidation,
                "required_triggers": setup.required_conditions,
            }
            if entry_trigger_result:
                ctx["trigger_result"] = entry_trigger_result
                # Zone touch from the deterministic evaluation (not assertions).
                if entry_trigger_result.get("conditions_met", {}).get("zone_touch"):
                    ctx["zone_touched"] = True
            entry_out = entry_role.analyze(ctx)
            entry = EntryAssessment(
                entry_assessment_id=f"ent_{setup.setup_id}",
                setup_id=setup.setup_id,
                symbol=symbol,
                direction=setup.direction,
                entry_zone_type="ORDER_BLOCK",
                zone_touched=bool(entry_out.role_specific.get("zone_touched", False)),
                trigger_required=setup.required_conditions[0] if setup.required_conditions else "",
                trigger_status=entry_out.signal,
                entry_quality=entry_out.confidence_dimensions.get("evidence_quality", 0.0),
                invalidation=setup.invalidation,
            )
        # ── Decision state ──────────────────────────────────────────────
        # Debate gate (§10): an INVALID setup can NEVER yield an actionable
        # decision, and a WAIT outcome forces WAIT even with directional bias.
        from .debate import OUTCOME_INVALID as _INV
        from .debate import OUTCOME_WAIT as _W

        debate_outcome = (debate_dict or {}).get("outcome", "")
        if setup is not None and (setup.status == "INVALID" or debate_outcome == _INV):
            decision = self.coordinator.build_decision(
                assessment,
                setup=None,
                entry=None,
                evidence_quality=self._avg_evidence_quality(role_outputs),
                data_quality=assessment.data_quality,
            )
            decision.action = "WAIT"
            decision.rationale = "Debate invalidated the setup hypothesis (INVALID) — WAIT."
        else:
            decision = self.coordinator.build_decision(
                assessment,
                setup=setup,
                entry=entry,
                evidence_quality=self._avg_evidence_quality(role_outputs),
                setup_quality=setup.setup_quality if setup else 0.0,
                entry_quality=entry.entry_quality if entry else 0.0,
                data_quality=assessment.data_quality,
            )
            if debate_outcome == _W:
                decision.action = "WAIT"
                decision.rationale = "Debate ended WAIT (unresolved conflict) — no automatic trade."
        # Entry readiness gate: even a VALIDATED decision must not be
        # actionable unless the entry committee says ENTRY_READY (§20).
        if (
            decision is not None
            and entry is not None
            and entry.trigger_status not in ("ENTRY_READY",)
            and debate_outcome not in (_INV, _W)
        ):
            if decision.action in ("BUY", "SELL"):
                decision.action = "WAIT"
                decision.rationale = (
                    f"Entry committee: {entry.trigger_status} — "
                    f"not actionable (zone touch is not confirmation)."
                )
        return CommitteeResult(
            dispatch=dispatch,
            assessment=assessment,
            setup=setup,
            entry=entry,
            decision=decision,
            debate=debate_dict,
            role_outputs=role_outputs,
            ran_committee=True,
        )

    # ------------------------------------------------------------------
    @staticmethod
    def _evaluate_entry_triggers(
        symbol: str,
        setup: SetupCandidate,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Run the deterministic Trigger Engine for a setup (Phase 4.5 §4).
        Returns the TriggerResult as a plain dict (or {} on insufficient data
        or error — fail-closed, EntryRole then yields WAIT_TRIGGER).
        """
        try:
            from trading.trigger_engine import evaluate_triggers

            zone = context.get("zone") or {}
            zone_top = float(zone.get("top") or context.get("zone_top") or 0.0)
            zone_bottom = float(zone.get("bottom") or context.get("zone_bottom") or 0.0)
            opens = list(context.get("trigger_opens") or context.get("opens") or [])
            highs = list(context.get("trigger_highs") or context.get("highs") or [])
            lows = list(context.get("trigger_lows") or context.get("lows") or [])
            closes = list(context.get("trigger_closes") or context.get("closes") or [])
            atr = float(context.get("atr") or 0.0)
            if len(closes) < 3 or zone_top <= 0 or zone_bottom <= 0 or atr <= 0:
                return {}
            result = evaluate_triggers(
                direction=setup.direction,
                zone_top=zone_top,
                zone_bottom=zone_bottom,
                opens=opens,
                highs=highs,
                lows=lows,
                closes=closes,
                atr=atr,
                timeframe=str(context.get("trigger_timeframe") or "M5"),
                is_closed=bool(context.get("candle_closed", True)),
            )
            return result.to_dict()
        except Exception as exc:  # noqa: BLE001 - fail-closed
            logger.warning("Orchestrator trigger evaluation failed: %s", exc)
            return {}

    @staticmethod
    def _derive_bias(role_outputs: dict[str, RoleOutput]) -> str:
        """Bias from CONSISTENT directional evidence (no voting)."""
        bull = bear = 0
        for rid in _DIRECTIONAL:
            ro = role_outputs.get(rid)
            if ro is None or ro.error:
                continue
            sig = str(ro.signal).upper()
            if sig in _BULL:
                bull += 1
            elif sig in _BEAR:
                bear += 1
        if bull > 0 and bear == 0:
            return "BULLISH"
        if bear > 0 and bull == 0:
            return "BEARISH"
        return "NEUTRAL"

    @staticmethod
    def _build_setup(
        symbol: str,
        assessment: MarketAssessment,
        role_outputs: dict[str, RoleOutput],
        bias: str,
    ) -> SetupCandidate:
        """Create a candidate (NOT an order) with supporting/contradicting refs."""
        direction = "BUY" if bias == "BULLISH" else "SELL"
        supporting: list[str] = []
        contradicting: list[str] = []
        want = bias
        for rid, ro in role_outputs.items():
            sig = str(ro.signal).upper()
            if sig == want:
                supporting.append(rid)
            elif sig in ("BULLISH", "BEARISH") and sig != want:
                contradicting.append(rid)
        setup = SetupCandidate(
            setup_id=f"setup_{assessment.assessment_id}",
            assessment_id=assessment.assessment_id,
            symbol=symbol,
            direction=direction,
            setup_type="CONTINUATION",
            timeframe=str(
                assessment.evidence_bundle.items()[0].timeframe
                if assessment.evidence_bundle and assessment.evidence_bundle.items()
                else "M15"
            ),
            entry_context="market structure location",
            invalidation="structure breaks opposite the hypothesis",
            required_conditions=["lower-timeframe confirmation (Phase 4 trigger)"],
            missing_conditions=["lower-timeframe confirmation (Phase 4 trigger)"],
            supporting_evidence_refs=supporting,
            contradicting_evidence_refs=contradicting,
            setup_quality=0.5,
            status="CANDIDATE",
        )
        return setup

    @staticmethod
    def _avg_evidence_quality(role_outputs: dict[str, RoleOutput]) -> float:
        vals = [
            float(ro.confidence_dimensions.get("evidence_quality", 0.0))
            for ro in role_outputs.values()
            if not ro.error
        ]
        return sum(vals) / len(vals) if vals else 0.0
