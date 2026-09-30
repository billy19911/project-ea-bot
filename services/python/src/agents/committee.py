# -*- coding: utf-8 -*-
"""Committee coordinator (Phase 2 §14–§16) — evidence-driven decision orchestration.

Transforms legacy agent outputs into canonical evidence, builds a
MarketAssessment, detects structural conflicts, runs a targeted
challenge/second-opinion flow, and emits a canonical DecisionState. It NEVER
votes; conflicts are surfaced and either resolved by targeted evidence or left
UNRESOLVED (which forces WAIT/NO_TRADE).

Deterministic boundary: this coordinator only produces structure. It does not
execute, does not touch MT5, and does not set final volume.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from .canonical import (
    Challenge,
    Conflict,
    DecisionState,
    EntryAssessment,
    EvidenceBundle,
    EvidenceItem,
    EvidenceKind,
    Freshness,
    MarketAssessment,
    SetupCandidate,
)

logger = logging.getLogger(__name__)

__all__ = [
    "AgentOutputAdapter",
    "CommitteeCoordinator",
]

# Domains whose signals are directional (must agree on direction).
_DIRECTIONAL_DOMAINS = ("structure", "regime", "liquidity", "momentum")

# Confidence floor below which we do not trust a directional claim.
_MIN_CLAIM_QUALITY = 0.5


def _new_id(prefix: str) -> str:
    import uuid

    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class AgentOutputAdapter:
    """Adapt a legacy agent output dict into canonical :class:`EvidenceItem`s."""

    def to_evidence(
        self,
        agent_name: str,
        output: dict[str, Any],
        *,
        symbol: str = "",
        timeframe: str = "",
        domain: str = "",
    ) -> EvidenceBundle:
        """Convert one agent output into an EvidenceBundle (never raises).

        A directional claim without any evidence is emitted with low quality
        (and marked) so downstream reject/incomplete logic can act on it.
        """
        bundle = EvidenceBundle()
        if not isinstance(output, dict):
            return bundle

        signal = str(output.get("signal", "NEUTRAL") or "NEUTRAL").upper()
        try:
            confidence = float(output.get("confidence", 0.0) or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = min(1.0, max(0.0, confidence))

        # Freshness / age
        age = output.get("age_seconds")
        try:
            age_val = float(age) if age is not None else None
        except (TypeError, ValueError):
            age_val = None

        # 1. Directional interpretation (INTERPRETATION)
        bundle.add(
            EvidenceItem(
                kind=EvidenceKind.INTERPRETATION,
                content=f"{agent_name} signal={signal}",
                source=agent_name,
                timeframe=timeframe,
                quality=confidence,
                age_seconds=age_val,
                domain=domain,
                metric_name="signal_confidence",
                metric_value=confidence,
            )
        )

        # 2. Explicit evidence list (FACTs), if provided by the agent.
        raw_evidence = output.get("evidence")
        if isinstance(raw_evidence, list):
            for ev in raw_evidence:
                if isinstance(ev, dict):
                    content = str(
                        ev.get("content") or ev.get("reason") or ev.get("reasoning") or ""
                    ).strip()
                    if not content:
                        continue
                    try:
                        quality = float(ev.get("quality", confidence) or confidence)
                    except (TypeError, ValueError):
                        quality = confidence
                    try:
                        kind = EvidenceKind(str(ev.get("kind", "FACT")).upper())
                    except ValueError:
                        kind = EvidenceKind.FACT
                    bundle.add(
                        EvidenceItem(
                            kind=kind,
                            content=content,
                            source=str(ev.get("source") or agent_name),
                            timeframe=str(ev.get("timeframe") or timeframe),
                            quality=min(1.0, max(0.0, quality)),
                            age_seconds=age_val,
                            domain=domain,
                        )
                    )
                elif isinstance(ev, str) and ev.strip():
                    bundle.add(
                        EvidenceItem(
                            kind=EvidenceKind.FACT,
                            content=ev.strip(),
                            source=agent_name,
                            timeframe=timeframe,
                            quality=confidence,
                            age_seconds=age_val,
                            domain=domain,
                        )
                    )

        # 3. Mark directional claims that lack supporting evidence (incomplete).
        if signal in ("BULLISH", "BEARISH", "BUY", "SELL"):
            has_facts = any(i.kind == EvidenceKind.FACT for i in bundle.items())
            if not has_facts:
                bundle.add(
                    EvidenceItem(
                        kind=EvidenceKind.RECOMMENDATION,
                        content="[INCOMPLETE] directional claim without supporting evidence",
                        source=agent_name,
                        timeframe=timeframe,
                        quality=0.0 if confidence < _MIN_CLAIM_QUALITY else confidence * 0.5,
                        age_seconds=age_val,
                        domain=domain,
                    )
                )
        return bundle


class CommitteeCoordinator:
    """Build a canonical DecisionState from agent evidence (no voting)."""

    def __init__(
        self,
        *,
        directional_claim_threshold: float = 0.6,
        un_resolved_conflict_blocks: bool = True,
        challenge_runner: Optional[Callable[[str, str, str], Optional[dict[str, Any]]]] = None,
    ) -> None:
        """
        Args:
            directional_claim_threshold: Minimum claimed evidence weight for a
                direction to form a setup candidate at all.
            un_resolved_conflict_blocks: When True, an unresolved HIGH/CRITICAL
                conflict forces the decision to WAIT (no actionable proposal).
            challenge_runner: Optional callable ``(agent_name, issue, context)
                -> output dict`` used to fetch a targeted second opinion. When
                None, challenges are recorded but not automatically resolved.
        """
        self.directional_claim_threshold = directional_claim_threshold
        self.un_resolved_conflict_blocks = un_resolved_conflict_blocks
        self.challenge_runner = challenge_runner
        self.adapter = AgentOutputAdapter()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_assessment(
        self,
        symbol: str,
        trace_id: str,
        agent_results: dict[str, dict[str, Any]],
        *,
        higher_timeframe_bias: str = "NEUTRAL",
        data_quality: float = 0.0,
        data_freshness: Optional[Freshness] = None,
    ) -> MarketAssessment:
        """Build a :class:`MarketAssessment` from agent results (evidence-backed)."""
        assessment = MarketAssessment(
            assessment_id=_new_id("asm"),
            trace_id=trace_id,
            symbol=symbol,
            higher_timeframe_bias=higher_timeframe_bias,
            data_quality=float(data_quality or 0.0),
            data_freshness=data_freshness or Freshness.FRESH,
        )
        bundle = assessment.evidence_bundle

        # Domain→signal map (last non-neutral wins per domain; conflicts tracked).
        domain_signal: dict[str, str] = {}
        for name, output in (agent_results or {}).items():
            if not isinstance(output, dict):
                continue
            domain = str(output.get("domain") or output.get("department") or name).lower()
            for item in self.adapter.to_evidence(
                name, output, symbol=symbol, domain=domain
            ).items():
                bundle.add(item)
            sig = str(output.get("signal", "NEUTRAL") or "NEUTRAL").upper()
            if sig not in ("NEUTRAL", ""):
                domain_signal.setdefault(domain, sig)

        # Populate coarse assessment fields from domain signals (evidence, not votes).
        assessment.regime = domain_signal.get("regime", "UNKNOWN")
        assessment.structure = domain_signal.get("structure", "UNKNOWN")
        assessment.liquidity = domain_signal.get("liquidity", "UNKNOWN")
        assessment.momentum = domain_signal.get("momentum", "UNKNOWN")
        assessment.volatility = domain_signal.get("volatility", "UNKNOWN")
        assessment.news = domain_signal.get("news", "UNKNOWN")

        # Detect directional conflicts across domains.
        assessment.conflicts = self.detect_conflicts(domains=domain_signal)
        return assessment

    def detect_conflicts(self, *, domains: dict[str, str]) -> list[Conflict]:
        """Detect structural conflicts between directional domains.

        Examples: structure bullish + momentum bearish; HTF vs LTF mismatches.
        Non-directional domains (volatility/news) are checked for UNKNOWN risk.
        """
        conflicts: list[Conflict] = []
        bull = [
            d
            for d in _DIRECTIONAL_DOMAINS
            if domains.get(d) in ("BULLISH", "STRONG_BULLISH", "BUY")
        ]
        bear = [
            d
            for d in _DIRECTIONAL_DOMAINS
            if domains.get(d) in ("BEARISH", "STRONG_BEARISH", "SELL")
        ]
        if bull and bear:
            conflicts.append(
                Conflict(
                    id=_new_id("cfl"),
                    severity="HIGH",
                    description=f"Directional conflict: {bull} bullish vs {bear} bearish",
                    domains=bull + bear,
                    evidence_refs=[f"{d}:{domains.get(d)}" for d in bull + bear],
                )
            )
        # News UNKNOWN is a risk marker (never treated as safe).
        if domains.get("news") in ("UNKNOWN", ""):
            conflicts.append(
                Conflict(
                    id=_new_id("cfl"),
                    severity="MEDIUM",
                    description="News/macro state UNKNOWN — risk not assessable",
                    domains=["news"],
                    evidence_refs=["news:UNKNOWN"],
                )
            )
        return conflicts

    def build_decision(
        self,
        assessment: MarketAssessment,
        *,
        setup: Optional[SetupCandidate] = None,
        entry: Optional[EntryAssessment] = None,
        evidence_quality: float = 0.0,
        setup_quality: float = 0.0,
        entry_quality: float = 0.0,
        data_quality: float = 0.0,
        risk_quality: float = 0.0,
        legacy_confidence: float = 0.0,
        strategy_version: str = "",
    ) -> DecisionState:
        """Produce a canonical :class:`DecisionState` (pre-execution states only).

        Direction/action is derived from evidence consistency, NOT voting:
        * consistent bullish evidence → bias BULLISH, action BUY candidate;
        * consistent bearish evidence → bias BEARISH, action SELL candidate;
        * any unresolved HIGH/CRITICAL conflict → action WAIT (no trade).
        """
        bias = self._derive_bias(assessment)
        action = "WAIT"
        state = "CANDIDATE" if setup is not None else "ANALYZING"

        unresolved_block = self.un_resolved_conflict_blocks and assessment.has_critical_conflicts()
        if not unresolved_block and bias in ("BULLISH", "BEARISH") and setup is not None:
            action = "BUY" if bias == "BULLISH" else "SELL"
            state = "VALIDATED"
        elif unresolved_block:
            action = "WAIT"
            state = "ANALYZING"

        decision = DecisionState(
            decision_id=_new_id("dec"),
            trace_id=assessment.trace_id,
            assessment_id=assessment.assessment_id,
            setup_id=setup.setup_id if setup else None,
            entry_assessment_id=entry.entry_assessment_id if entry else None,
            symbol=assessment.symbol,
            market_bias=bias,
            setup_type=setup.setup_type if setup else "NONE",
            action=action,
            evidence_quality=float(evidence_quality),
            setup_quality=float(setup_quality),
            entry_quality=float(entry_quality),
            data_quality=float(data_quality),
            risk_quality=float(risk_quality),
            legacy_confidence=float(legacy_confidence),
            evidence_bundle_ref=(
                assessment.evidence_bundle.id if assessment.evidence_bundle else None
            ),
            strategy_version=strategy_version,
            conflicts=list(assessment.conflicts),
        )
        # ALWAYS start at DETECTED, then walk the explicit state machine.
        decision.current_state = "DETECTED"
        decision.transition_to("ANALYZING")
        if state in ("CANDIDATE", "VALIDATED") and decision.is_valid_transition(
            "CANDIDATE" if state == "CANDIDATE" else "CANDIDATE"
        ):
            decision.transition_to("CANDIDATE")
        if state == "VALIDATED" and decision.is_valid_transition("VALIDATED"):
            decision.transition_to("VALIDATED")
        if action == "WAIT" and assessment.has_critical_conflicts():
            decision.rationale = "Unresolved high-severity conflict — WAIT (no automatic trade)."
        return decision

    def run_challenge(
        self,
        setup: SetupCandidate,
        conflict: Conflict,
    ) -> Challenge:
        """Create (and optionally run) a targeted challenge for a conflict.

        The challenge is targeted: it asks the OPPOSING domain's specialist to
        justify/refute, rather than re-running every agent.
        """
        opposing = conflict.domains[0] if conflict.domains else "structure"
        issue = conflict.description
        challenge = Challenge(
            challenge_id=_new_id("chl"),
            setup_id=setup.setup_id,
            issue=issue,
            evidence_requested=(
                f"Is the evidence from '{opposing}' strong enough to invalidate the "
                f"{setup.direction} setup?"
            ),
            assigned_to=opposing,
        )
        setup.challenge(issue)
        if self.challenge_runner is not None:
            try:
                follow_up = self.challenge_runner(opposing, issue, {"setup_id": setup.setup_id})
            except Exception as exc:  # noqa: BLE001 - challenge must never break
                logger.warning("Challenge runner failed: %s", exc)
                follow_up = None
            if isinstance(follow_up, dict):
                challenge.outcome = str(follow_up.get("outcome", "PENDING"))
                challenge.secondary_evidence_ref = str(follow_up.get("evidence_ref", "")) or None
        return challenge

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _derive_bias(assessment: MarketAssessment) -> str:
        """Derive directional bias from consistent (non-conflicting) evidence."""
        domains = {
            "regime": assessment.regime,
            "structure": assessment.structure,
            "liquidity": assessment.liquidity,
            "momentum": assessment.momentum,
        }
        bull = sum(
            1
            for d in _DIRECTIONAL_DOMAINS
            if domains.get(d) in ("BULLISH", "STRONG_BULLISH", "BUY")
        )
        bear = sum(
            1
            for d in _DIRECTIONAL_DOMAINS
            if domains.get(d) in ("BEARISH", "STRONG_BEARISH", "SELL")
        )
        # Bias is directional ONLY when evidence agrees; mixed → NEUTRAL.
        if bull > 0 and bear == 0:
            return "BULLISH"
        if bear > 0 and bull == 0:
            return "BEARISH"
        return "NEUTRAL"
