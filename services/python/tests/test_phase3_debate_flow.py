# -*- coding: utf-8 -*-
"""Phase 3 — Committee & Debate acceptance tests.

Proves the runtime uses the bounded debate engine for conflicts:

* only RELEVANT specialists are re-queried (never the whole committee);
* ``max_rounds`` bounds the loop;
* an unresolved HIGH/CRITICAL conflict yields WAIT (fail-closed);
* a resolved conflict allows progression;
* the debate record is exposed on the cycle result.
"""

from __future__ import annotations

import pytest

from agents import canonical as canonical_mod
from agents import committee as committee_mod
from agents import debate as debate_mod
from agents import roles as roles_mod
from orchestration import decision_chain as chain_mod


def _conflict(severity: str = "HIGH") -> "canonical_mod.Conflict":
    return canonical_mod.Conflict(
        id="cfl_1",
        severity=severity,
        description="structure bullish vs momentum bearish",
        domains=["structure", "momentum"],
        evidence_refs=["structure:BULLISH", "momentum:BEARISH"],
    )


class _ChallengerPass:
    """Deterministic challenger that PASSES the hypothesis."""

    role = roles_mod.ROLE_CHALLENGER

    def analyze(self, context):
        return roles_mod.RoleOutput(
            role=roles_mod.ROLE_CHALLENGER,
            signal=roles_mod.CHALLENGE_PASSED,
            role_specific={"outcome": roles_mod.CHALLENGE_PASSED},
        )


class _ChallengerFail:
    """Deterministic challenger that FAILS the hypothesis."""

    role = roles_mod.ROLE_CHALLENGER

    def analyze(self, context):
        return roles_mod.RoleOutput(
            role=roles_mod.ROLE_CHALLENGER,
            signal=roles_mod.CHALLENGE_FAILED,
            role_specific={"outcome": roles_mod.CHALLENGE_FAILED},
        )


def _setup() -> "canonical_mod.SetupCandidate":
    return canonical_mod.SetupCandidate(
        setup_id="setup_1",
        assessment_id="asm_1",
        symbol="XAUUSD",
        direction="BUY",
        setup_type="CONTINUATION",
        timeframe="M15",
    )


# ── bounded debate mechanics ───────────────────────────────────────────
def test_debate_is_bounded_by_max_rounds() -> None:
    config = debate_mod.DebateConfig(max_rounds=2)
    engine = debate_mod.DebateEngine(config=config, challenger=_ChallengerFail())
    outcome = engine.run(_setup(), [_conflict("HIGH")], hypothesis_direction="BUY")
    assert outcome.rounds <= config.max_rounds
    assert len(outcome.records) <= config.max_rounds


def test_challenge_runner_receives_only_relevant_specialist() -> None:
    seen: list[str] = []

    def runner(role: str, context):
        seen.append(role)
        return None

    class _ChallengerUnresolved:
        role = roles_mod.ROLE_CHALLENGER

        def analyze(self, context):
            return roles_mod.RoleOutput(
                role=roles_mod.ROLE_CHALLENGER,
                signal=roles_mod.CHALLENGE_UNRESOLVED,
                role_specific={"outcome": roles_mod.CHALLENGE_UNRESOLVED},
            )

    engine = debate_mod.DebateEngine(challenger=_ChallengerUnresolved(), specialist_runner=runner)
    engine.run(_setup(), [_conflict("HIGH")], hypothesis_direction="BUY")
    # Only the disputed domains are consulted — never the whole committee.
    assert seen
    assert set(seen).issubset({"structure", "momentum"})


def test_unresolved_high_conflict_yields_wait() -> None:
    engine = debate_mod.DebateEngine(challenger=_ChallengerFail())
    outcome = engine.run(_setup(), [_conflict("HIGH")], hypothesis_direction="BUY")
    assert outcome.outcome in (debate_mod.OUTCOME_WAIT, debate_mod.OUTCOME_INVALID)
    assert outcome.unresolved_conflicts


def test_resolved_conflict_allows_progression() -> None:
    engine = debate_mod.DebateEngine(challenger=_ChallengerPass())
    outcome = engine.run(_setup(), [_conflict("HIGH")], hypothesis_direction="BUY")
    assert outcome.outcome == debate_mod.OUTCOME_RESOLVED


# ── runtime wiring: the builder must run the debate ────────────────────
def test_build_decision_chain_exposes_debate_outcome(monkeypatch) -> None:
    original = committee_mod.CommitteeCoordinator.build_assessment

    def conflicting(self, symbol, trace_id, agent_results, **kwargs):
        assessment = original(self, symbol, trace_id, agent_results, **kwargs)
        assessment.conflicts.append(_conflict("HIGH"))
        return assessment

    monkeypatch.setattr(committee_mod.CommitteeCoordinator, "build_assessment", conflicting)
    monkeypatch.setattr(chain_mod, "_debate_challenger", lambda: _ChallengerFail(), raising=False)

    result = chain_mod.build_decision_chain(
        {
            "agent_results": {
                "structure_analyst": {
                    "signal": "BULLISH",
                    "confidence": 0.8,
                    "domain": "structure",
                },
                "momentum_analyst": {
                    "signal": "BEARISH",
                    "confidence": 0.8,
                    "domain": "momentum",
                },
            },
            "proposal": {"direction": "BUY"},
            "symbol": "XAUUSD",
        },
        symbol="XAUUSD",
        trace_id="t1",
    )
    assert result is not None
    debate = result.get("debate")
    assert debate is not None
    assert debate["rounds"] >= 1
    assert debate["outcome"] in (
        debate_mod.OUTCOME_WAIT,
        debate_mod.OUTCOME_INVALID,
        debate_mod.OUTCOME_RESOLVED,
    )


def test_resolved_debate_allows_validated_decision(monkeypatch) -> None:
    original = committee_mod.CommitteeCoordinator.build_assessment

    def conflicting(self, symbol, trace_id, agent_results, **kwargs):
        assessment = original(self, symbol, trace_id, agent_results, **kwargs)
        assessment.conflicts.append(_conflict("HIGH"))
        return assessment

    monkeypatch.setattr(committee_mod.CommitteeCoordinator, "build_assessment", conflicting)
    monkeypatch.setattr(chain_mod, "_debate_challenger", lambda: _ChallengerPass(), raising=False)

    result = chain_mod.build_decision_chain(
        {
            "agent_results": {
                "structure_analyst": {
                    "signal": "BULLISH",
                    "confidence": 0.8,
                    "domain": "structure",
                },
                "momentum_analyst": {
                    "signal": "BULLISH",
                    "confidence": 0.8,
                    "domain": "momentum",
                },
            },
            "proposal": {"direction": "BUY"},
            "symbol": "XAUUSD",
        },
        symbol="XAUUSD",
        trace_id="t1",
    )
    assert result is not None
    # A resolved challenge must not leave an unresolved critical conflict.
    assert result["assessment"]["has_critical_conflicts"] is False


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
