# -*- coding: utf-8 -*-
"""Tests for live readiness evaluation."""

from __future__ import annotations

import pytest

from src.live_readiness.base import LiveReadinessGate, LiveReadinessStatus, Phase30Gate
from src.live_readiness.evaluator import LiveReadinessEvaluator, LiveReadinessReport


class TestPhase30Gate:
    """Test Phase30Gate enum."""

    def test_gate_values(self):
        """Verify all 11 gates present."""
        gates = list(Phase30Gate)
        assert len(gates) == 11
        assert Phase30Gate.BACKTEST.value == "backtest"
        assert Phase30Gate.FORWARD_TEST.value == "forward_test"
        assert Phase30Gate.PAPER_TRADING.value == "paper_trading"
        assert Phase30Gate.DEMO_TRADING.value == "demo_trading"
        assert Phase30Gate.RISK_VALIDATION.value == "risk_validation"
        assert Phase30Gate.KILL_SWITCH.value == "kill_switch"
        assert Phase30Gate.MONITORING.value == "monitoring"
        assert Phase30Gate.ALERTS.value == "alerts"
        assert Phase30Gate.BACKUP.value == "backup"
        assert Phase30Gate.RECOVERY_TESTED.value == "recovery_tested"
        assert Phase30Gate.MANUAL_EMERGENCY_CONTROL.value == "manual_emergency_control"


class TestLiveReadinessGate:
    """Test LiveReadinessGate dataclass."""

    def test_gate_passed(self):
        gate = LiveReadinessGate(
            Phase30Gate.BACKTEST, LiveReadinessStatus.PASSED, "Backtest completed successfully"
        )
        assert gate.name == Phase30Gate.BACKTEST
        assert gate.status == LiveReadinessStatus.PASSED
        assert gate.details == "Backtest completed successfully"

    def test_gate_failed(self):
        gate = LiveReadinessGate(
            Phase30Gate.KILL_SWITCH, LiveReadinessStatus.FAILED, "Kill switch test failed"
        )
        assert gate.status == LiveReadinessStatus.FAILED

    def test_gate_default_status(self):
        gate = LiveReadinessGate(Phase30Gate.BACKTEST)
        assert gate.status == LiveReadinessStatus.NOT_STARTED
        assert gate.details == ""


class TestLiveReadinessEvaluator:
    """Test LiveReadinessEvaluator."""

    def test_init(self):
        evaluator = LiveReadinessEvaluator()
        assert evaluator.report is None

    def test_set_gate_passed(self):
        evaluator = LiveReadinessEvaluator()
        evaluator.set_gate(Phase30Gate.BACKTEST, True, "Passed")
        assert Phase30Gate.BACKTEST in evaluator._results
        assert evaluator._results[Phase30Gate.BACKTEST].status == LiveReadinessStatus.PASSED

    def test_set_gate_failed(self):
        evaluator = LiveReadinessEvaluator()
        evaluator.set_gate(Phase30Gate.BACKTEST, False, "Failed")
        assert evaluator._results[Phase30Gate.BACKTEST].status == LiveReadinessStatus.FAILED

    def test_evaluate_all_pass(self):
        """All 11 gates must pass for report to be PASSED."""
        evaluator = LiveReadinessEvaluator()
        for gate in Phase30Gate:
            evaluator.set_gate(gate, True, f"{gate.value} OK")
        report = evaluator.evaluate()
        assert report.status == LiveReadinessStatus.PASSED
        assert report.ready is True

    def test_evaluate_fail_closed_one_missing(self):
        """Missing gate defaults to FAILED (fail-closed)."""
        evaluator = LiveReadinessEvaluator()
        for gate in Phase30Gate:
            if gate != Phase30Gate.BACKTEST:
                evaluator.set_gate(gate, True, f"{gate.value} OK")
        report = evaluator.evaluate()
        assert report.status == LiveReadinessStatus.FAILED
        assert report.ready is False
        assert report.gates[Phase30Gate.BACKTEST].status == LiveReadinessStatus.FAILED
        assert "Evidence missing" in report.gates[Phase30Gate.BACKTEST].details

    def test_evaluate_fail_closed_one_failed(self):
        """One explicit FAILED gate causes overall FAILED."""
        evaluator = LiveReadinessEvaluator()
        for gate in Phase30Gate:
            evaluator.set_gate(gate, True, f"{gate.value} OK")
        evaluator.set_gate(Phase30Gate.MONITORING, False, "Monitoring not active")
        report = evaluator.evaluate()
        assert report.status == LiveReadinessStatus.FAILED
        assert report.ready is False
        assert report.gates[Phase30Gate.MONITORING].status == LiveReadinessStatus.FAILED

    def test_evaluate_report_structure(self):
        """Report contains all 11 gates with populated details."""
        evaluator = LiveReadinessEvaluator()
        for gate in Phase30Gate:
            evaluator.set_gate(gate, True, f"{gate.value} validation passed")
        report = evaluator.evaluate()
        assert len(report.gates) == 11
        assert all(g in report.gates for g in Phase30Gate)
        assert all(report.gates[g].details for g in Phase30Gate)

    def test_reset(self):
        """Reset clears evidence and returns to fail-closed."""
        evaluator = LiveReadinessEvaluator()
        evaluator.set_gate(Phase30Gate.BACKTEST, True, "OK")
        evaluator.evaluate()
        evaluator.reset()
        assert evaluator.report is None
        assert len(evaluator._results) == 0
        report = evaluator.evaluate()
        assert report.status == LiveReadinessStatus.FAILED


class TestLiveReadinessReport:
    """Test LiveReadinessReport frozen dataclass."""

    def test_report_frozen(self):
        """Report is immutable once created."""
        gates = {
            Phase30Gate.BACKTEST: LiveReadinessGate(
                Phase30Gate.BACKTEST, LiveReadinessStatus.PASSED
            )
        }
        report = LiveReadinessReport(gates, LiveReadinessStatus.PASSED)
        with pytest.raises(Exception):  # FrozenInstanceError
            report.status = LiveReadinessStatus.FAILED

    def test_report_ready_property(self):
        """ready property reflects status."""
        gates = {g: LiveReadinessGate(g, LiveReadinessStatus.PASSED) for g in Phase30Gate}
        report = LiveReadinessReport(gates, LiveReadinessStatus.PASSED)
        assert report.ready is True

        gates_failed = {g: LiveReadinessGate(g, LiveReadinessStatus.FAILED) for g in Phase30Gate}
        report_failed = LiveReadinessReport(gates_failed, LiveReadinessStatus.FAILED)
        assert report_failed.ready is False


class TestLiveReadinessChecklistReporting:
    """Test deterministic Phase 30 checklist reporting."""

    def test_report_lists_all_blocking_gates_when_evidence_is_missing(self):
        evaluator = LiveReadinessEvaluator()

        report = evaluator.evaluate()

        assert report.status == LiveReadinessStatus.FAILED
        assert report.ready is False
        assert report.blocked_gates == tuple(Phase30Gate)
        assert "LIVE EXECUTION: BLOCKED" in report.render_checklist()

    def test_report_serializes_all_gate_details_without_execution(self):
        evaluator = LiveReadinessEvaluator()
        for gate in Phase30Gate:
            evaluator.set_gate(gate, True, f"{gate.value} evidence recorded")

        report = evaluator.evaluate()
        payload = report.to_dict()

        assert payload["status"] == "passed"
        assert payload["ready"] is True
        assert payload["live_execution_enabled"] is False
        assert payload["blocked_gates"] == []
        assert len(payload["checklist"]) == len(Phase30Gate)
        assert payload["checklist"]["kill_switch"]["details"] == ("kill_switch evidence recorded")

    def test_report_marks_failed_gate_as_blocking(self):
        evaluator = LiveReadinessEvaluator()
        for gate in Phase30Gate:
            evaluator.set_gate(gate, True, "evidence recorded")
        evaluator.set_gate(Phase30Gate.RECOVERY_TESTED, False, "restore test failed")

        report = evaluator.evaluate()

        assert report.blocked_gates == (Phase30Gate.RECOVERY_TESTED,)
        assert "[FAILED] recovery_tested — restore test failed" in (report.render_checklist())
