# -*- coding: utf-8 -*-
"""Phase 2 — canonical decision chain builder (additive, fail-safe).

Builds the canonical decision objects from an existing supervisor analysis:

    MarketAssessment -> SetupCandidate -> DecisionState

The builder NEVER replaces the supervisor synthesis or the Risk Gate. It
observes the same ``agent_results`` the supervisor already produced and
records the canonical chain on the cycle result for traceability. Any error
degrades to ``None`` (the pipeline keeps its historic behaviour).

Phase 2 §2: one authoritative field for direction lives on the DecisionState
(``action``); the proposal's ``direction`` is the execution alias.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

__all__ = ["build_decision_chain", "STATE_ORDER"]

STATE_ORDER = (
    "DETECTED",
    "ANALYZING",
    "CANDIDATE",
    "VALIDATED",
    "ARMED",
    "WAITING_TRIGGER",
    "EXECUTING",
    "OPEN",
    "MANAGING",
    "CLOSED",
    "REJECTED",
    "EXPIRED",
)

_ACTIONABLE = {"BUY", "SELL"}


def _new_id(prefix: str) -> str:
    import uuid

    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def build_decision_chain(
    analysis: Any,
    *,
    symbol: str = "",
    trace_id: str = "",
    strategy_version: str = "",
) -> Optional[dict[str, Any]]:
    """Build the canonical chain from a supervisor analysis dict.

    Returns a serialised ``{"assessment", "setup", "decision"}`` dict, or
    ``None`` when the analysis carries no usable agent evidence. Never raises.
    """
    try:
        from agents.canonical import SetupCandidate
        from agents.committee import CommitteeCoordinator
    except Exception:  # noqa: BLE001 - canonical modules optional
        try:
            from src.agents.canonical import SetupCandidate  # type: ignore
            from src.agents.committee import CommitteeCoordinator  # type: ignore
        except Exception:  # noqa: BLE001 - keep historic behaviour
            logger.debug("Canonical decision modules unavailable")
            return None

    try:
        if not isinstance(analysis, dict):
            return None
        agent_results = analysis.get("agent_results")
        if not isinstance(agent_results, dict) or not agent_results:
            return None

        symbol = str(symbol or analysis.get("symbol") or "")
        trace_id = str(trace_id or analysis.get("trace_id") or analysis.get("signal_id") or "")

        coordinator = CommitteeCoordinator()
        try:
            assessment = coordinator.build_assessment(symbol, trace_id, agent_results)
        except Exception:
            return None

        # SetupCandidate only when the proposal direction is actionable AND the
        # assessment has no unresolved critical conflict (Phase 2 §2: an
        # unresolved conflict must not produce a tradeable candidate).
        proposal = analysis.get("proposal")
        if isinstance(proposal, dict):
            direction = str(proposal.get("direction", "")).upper()
        else:
            direction = ""
        setup: Optional[SetupCandidate] = None
        debate: Optional[dict[str, Any]] = None
        if direction in _ACTIONABLE:
            setup = SetupCandidate(
                setup_id=_new_id("setup"),
                assessment_id=assessment.assessment_id,
                symbol=symbol,
                direction=direction,
                setup_type=str(analysis.get("setup_type") or "CONTINUATION"),
                timeframe=str(analysis.get("timeframe") or "M15"),
            )
            # Phase 3: run the bounded debate for unresolved conflicts BEFORE
            # the decision is built. A failed/unresolved HIGH/CRITICAL debate
            # invalidates the setup (fail-closed); a resolved one clears the
            # conflicts so the decision can progress.
            debate = _run_debate(setup, assessment, symbol=symbol)
            if debate is not None and debate.get("outcome") in ("INVALID", "WAIT"):
                setup.status = "INVALID" if debate.get("outcome") == "INVALID" else "CHALLENGED"

        decision = coordinator.build_decision(
            assessment,
            setup=setup,
            strategy_version=str(strategy_version or ""),
        )
        return {
            "assessment": assessment.to_dict(),
            "setup": setup.to_dict() if setup is not None else None,
            "decision": decision.to_dict(),
            "debate": debate,
        }
    except Exception as exc:  # noqa: BLE001 - observability must never break a cycle
        logger.debug("Canonical decision chain skipped: %s", exc)
        return None


def _debate_challenger() -> Any:
    """Return the deterministic challenger role for the debate (injectable)."""
    try:
        from agents.roles import ChallengerRole
    except Exception:  # noqa: BLE001 - alternate import identity
        from src.agents.roles import ChallengerRole  # type: ignore
    return ChallengerRole()


def _run_debate(setup: Any, assessment: Any, *, symbol: str = "") -> Optional[dict[str, Any]]:
    """Run the bounded debate for unresolved conflicts (Phase 3, fail-safe).

    Returns the serialised debate outcome, or ``None`` when there is nothing
    to debate (no unresolved conflicts) or the debate modules are unavailable.
    Never raises.
    """
    try:
        conflicts = [c for c in (assessment.conflicts or []) if c.resolution_status != "RESOLVED"]
        if not conflicts:
            return None
        try:
            from agents.debate import DebateEngine
        except Exception:  # noqa: BLE001 - alternate import identity
            from src.agents.debate import DebateEngine  # type: ignore
        engine = DebateEngine(challenger=_debate_challenger())
        outcome = engine.run(
            setup,
            conflicts,
            hypothesis_direction=str(getattr(setup, "direction", "") or ""),
            context={"symbol": symbol},
        )
        return outcome.to_dict()
    except Exception as exc:  # noqa: BLE001 - debate must never break a cycle
        logger.debug("Debate skipped: %s", exc)
        return None
