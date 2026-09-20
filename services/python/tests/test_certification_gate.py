# -*- coding: utf-8 -*-
"""Tests for Production Certification Gate (Phase 50)."""

from src.live_readiness.certification_gate import (
    GATE_A_CHECKS,
    GATE_B_CHECKS,
    GATE_C_CHECKS,
    GATE_D_CHECKS,
    GATE_E_CHECKS,
    ProductionCertificationGate,
    ProductionStatus,
)


def _all_pass() -> dict[str, dict[str, bool]]:
    return {
        "A": {c: True for c in GATE_A_CHECKS},
        "B": {c: True for c in GATE_B_CHECKS},
        "C": {c: True for c in GATE_C_CHECKS},
        "D": {c: True for c in GATE_D_CHECKS},
        "E": {c: True for c in GATE_E_CHECKS},
    }


def test_empty_gate_is_not_ready() -> None:
    gate = ProductionCertificationGate()
    report = gate.evaluate()
    assert report.status == ProductionStatus.NOT_READY.value


def test_engineering_fail_not_ready() -> None:
    results = _all_pass()
    results["A"]["python_tests"] = False
    report = ProductionCertificationGate(results).evaluate()
    assert report.status == ProductionStatus.NOT_READY.value


def test_safety_fail_not_ready() -> None:
    results = _all_pass()
    results["B"]["kill_switch"] = False
    report = ProductionCertificationGate(results).evaluate()
    assert report.status == ProductionStatus.NOT_READY.value


def test_research_fail_ready_for_paper() -> None:
    results = _all_pass()
    results["C"]["monte_carlo"] = False
    report = ProductionCertificationGate(results).evaluate()
    assert report.status == ProductionStatus.READY_FOR_PAPER.value


def test_operational_fail_ready_for_demo() -> None:
    results = _all_pass()
    results["D"]["mt5_disconnect"] = False
    report = ProductionCertificationGate(results).evaluate()
    assert report.status == ProductionStatus.READY_FOR_DEMO.value


def test_all_pass_ready_for_small_live() -> None:
    report = ProductionCertificationGate(_all_pass()).evaluate()
    assert report.status == ProductionStatus.READY_FOR_SMALL_LIVE.value


def test_critical_incident_halts() -> None:
    report = ProductionCertificationGate(_all_pass(), critical_incident_open=True).evaluate()
    assert report.status == ProductionStatus.HALTED.value


def test_promote_to_production_requires_full_pass() -> None:
    gate = ProductionCertificationGate(_all_pass())
    report = gate.promote_to_production()
    assert report.status == ProductionStatus.PRODUCTION.value


def test_promote_refused_when_not_ready() -> None:
    report = ProductionCertificationGate({}).promote_to_production()
    assert report.status == ProductionStatus.NOT_READY.value


def test_report_lists_failed_checks() -> None:
    results = _all_pass()
    results["A"]["lint"] = False
    report = ProductionCertificationGate(results).evaluate()
    gate_a = next(g for g in report.gates if g.gate == "A")
    assert "lint" in gate_a.failed_checks()
