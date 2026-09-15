# -*- coding: utf-8 -*-
"""Tests for EPIC 19 — live readiness gates and explicit LIVE activation.

Covers:
- 19.01–19.09, 19.11–19.15: the fourteen named readiness gates
- 19.10: explicit LIVE activation (all gates PASSED + exact phrase)
- fail-closed behavior: any regression while LIVE drops back to PAPER
"""

from __future__ import annotations

import pytest

from src.readiness import (
    DEFAULT_GATE_NAMES,
    LIVE_CONFIRMATION_PHRASE,
    ActivationBlockedError,
    GateStatus,
    LiveReadinessGate,
)

EXPECTED_GATES = {
    "backtest",
    "walk_forward",
    "paper",
    "demo",
    "risk",
    "stability",
    "recovery",
    "observability",
    "security",
    "autonomous_workflow",
    "committee_consensus",
    "learning_safety",
    "telegram_control_plane",
    "provider_discovery",
}


def _pass_all(gate: LiveReadinessGate) -> None:
    """Submit PASSED evidence for every registered gate."""
    for name in gate.gate_names():
        gate.submit(name, passed=True, evidence={"verified": True})


class TestGateRegistry:
    """Gate registration, submission and revocation."""

    def test_default_gate_names_cover_epic_19(self):
        assert len(DEFAULT_GATE_NAMES) == 14
        assert set(DEFAULT_GATE_NAMES) == EXPECTED_GATES

    def test_starts_in_paper_mode_with_pending_gates(self):
        gate = LiveReadinessGate()
        assert gate.mode == "PAPER"
        assert gate.is_live is False
        assert gate.is_ready() is False
        assert len(gate.blockers()) == 14
        for name in gate.gate_names():
            assert gate.status(name) == GateStatus.PENDING

    def test_submit_passed_records_evidence_and_timestamp(self):
        gate = LiveReadinessGate()
        result = gate.submit("backtest", passed=True, evidence={"report": "r-1"})
        assert result.status == GateStatus.PASSED
        assert result.evidence == {"report": "r-1"}
        assert result.timestamp
        assert gate.status("backtest") == GateStatus.PASSED

    def test_failing_submission_requires_evidence_or_reason(self):
        gate = LiveReadinessGate()
        with pytest.raises(ValueError):
            gate.submit("risk", passed=False)

    def test_failing_submission_with_reason_is_recorded(self):
        gate = LiveReadinessGate()
        result = gate.submit("risk", passed=False, reason="drawdown breached")
        assert result.status == GateStatus.FAILED
        assert "risk" in gate.blockers()

    def test_unknown_gate_raises_key_error(self):
        gate = LiveReadinessGate()
        with pytest.raises(KeyError):
            gate.status("nope")
        with pytest.raises(KeyError):
            gate.submit("nope", passed=True)
        with pytest.raises(KeyError):
            gate.revoke("nope")

    def test_revoke_returns_gate_to_pending(self):
        gate = LiveReadinessGate()
        gate.submit("paper", passed=True, evidence={"days": 30})
        gate.revoke("paper", reason="evidence expired")
        assert gate.status("paper") == GateStatus.PENDING
        assert "paper" in gate.blockers()


class TestReadinessReport:
    """Readiness reporting without side effects."""

    def test_report_structure_before_readiness(self):
        gate = LiveReadinessGate()
        report = gate.report()
        assert report["ready"] is False
        assert report["passed"] == 0
        assert report["total"] == 14
        assert report["mode"] == "PAPER"
        assert len(report["blockers"]) == 14
        assert set(report["gates"]) == EXPECTED_GATES
        assert set(report["gates"].values()) == {"pending"}

    def test_report_after_partial_pass(self):
        gate = LiveReadinessGate()
        gate.submit("backtest", passed=True, evidence={})
        gate.submit("risk", passed=False, reason="limits exceeded")
        report = gate.report()
        assert report["passed"] == 1
        assert report["gates"]["backtest"] == "passed"
        assert report["gates"]["risk"] == "failed"
        assert report["ready"] is False


class TestExplicitLiveActivation:
    """19.10 — explicit LIVE activation protocol."""

    def test_blocked_while_gates_pending(self):
        gate = LiveReadinessGate()
        with pytest.raises(ActivationBlockedError):
            gate.activate_live(LIVE_CONFIRMATION_PHRASE)
        assert gate.mode == "PAPER"

    def test_blocked_when_any_gate_failed(self):
        gate = LiveReadinessGate()
        _pass_all(gate)
        gate.submit("security", passed=False, reason="audit gap")
        with pytest.raises(ActivationBlockedError) as exc:
            gate.activate_live(LIVE_CONFIRMATION_PHRASE)
        assert "security" in str(exc.value)
        assert gate.mode == "PAPER"

    @pytest.mark.parametrize(
        "phrase",
        [
            "activate live trading",
            "Activate Live Trading",
            "ACTIVATE LIVE TRADING ",
            " ACTIVATE LIVE TRADING",
            "ACTIVATE  LIVE TRADING",
            "",
        ],
    )
    def test_blocked_on_inexact_confirmation_phrase(self, phrase):
        gate = LiveReadinessGate()
        _pass_all(gate)
        with pytest.raises(ActivationBlockedError):
            gate.activate_live(phrase)
        assert gate.mode == "PAPER"

    def test_activation_succeeds_with_all_gates_and_exact_phrase(self):
        gate = LiveReadinessGate()
        _pass_all(gate)
        assert gate.is_ready() is True
        record = gate.activate_live(LIVE_CONFIRMATION_PHRASE, activated_by="risk-ops")
        assert record.activated is True
        assert record.activated_by == "risk-ops"
        assert gate.mode == "LIVE"
        assert gate.is_live is True
        assert len(gate.history()) == 1

    def test_deactivation_returns_to_paper(self):
        gate = LiveReadinessGate()
        _pass_all(gate)
        gate.activate_live(LIVE_CONFIRMATION_PHRASE)
        record = gate.deactivate_live("operator stop")
        assert record.activated is False
        assert gate.mode == "PAPER"
        assert len(gate.history()) == 2

    def test_revoke_while_live_fails_closed_to_paper(self):
        gate = LiveReadinessGate()
        _pass_all(gate)
        gate.activate_live(LIVE_CONFIRMATION_PHRASE)
        gate.revoke("recovery", reason="drill failed")
        assert gate.mode == "PAPER"
        assert gate.is_live is False
        history = gate.history()
        assert history[-1].activated is False
        assert "recovery" in history[-1].reason

    def test_failed_submission_while_live_fails_closed_to_paper(self):
        gate = LiveReadinessGate()
        _pass_all(gate)
        gate.activate_live(LIVE_CONFIRMATION_PHRASE)
        gate.submit("stability", passed=False, reason="latency spike")
        assert gate.mode == "PAPER"
        assert "stability" in gate.blockers()


class TestCustomGates:
    """Pluggable custom gates participate in readiness."""

    class _AuditGate:
        name = "custom_audit"

        def evaluate(self, context):
            return True, dict(context)

    def test_register_custom_gate(self):
        gate = LiveReadinessGate()
        gate.register(self._AuditGate())
        assert "custom_audit" in gate.gate_names()
        assert gate.status("custom_audit") == GateStatus.PENDING
        assert len(gate.gate_names()) == 15

    def test_custom_gate_must_pass_for_activation(self):
        gate = LiveReadinessGate()
        _pass_all(gate)
        gate.register(self._AuditGate())
        with pytest.raises(ActivationBlockedError):
            gate.activate_live(LIVE_CONFIRMATION_PHRASE)
        gate.submit("custom_audit", passed=True, evidence={"audit": "ok"})
        gate.activate_live(LIVE_CONFIRMATION_PHRASE)
        assert gate.is_live is True
