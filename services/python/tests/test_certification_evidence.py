# -*- coding: utf-8 -*-
"""RED→GREEN tests for certification evidence + real accounts (slice A/B/C)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from src.live_readiness.certification_evidence import collect_gate_evidence
from src.live_readiness.certification_gate import (
    GATE_A_CHECKS,
    ProductionCertificationGate,
    ProductionStatus,
)
from src.main import app
from src.system import v2_endpoints

client = TestClient(app)


def test_gate_none_is_not_run_not_false() -> None:
    """A None evidence value must be NOT_RUN, never silently False."""
    gate = ProductionCertificationGate({"A": {"python_tests": None}})
    report = gate.evaluate()
    gate_a = next(g for g in report.gates if g.gate == "A")
    assert gate_a.checks["python_tests"] is None
    assert "python_tests" in gate_a.failed_checks()
    assert report.status == ProductionStatus.NOT_READY.value


def test_gate_false_still_fails_deterministically() -> None:
    results = {"A": {c: True for c in GATE_A_CHECKS}}
    results["A"]["lint"] = False
    gate = ProductionCertificationGate(results)
    gate_a = next(g for g in gate.evaluate().gates if g.gate == "A")
    assert gate_a.checks["lint"] is False


def test_gate_accepts_rich_evidence_and_reasons() -> None:
    evidence = {
        "A": {
            "python_tests": {"value": True, "reason": "ok", "evidence_source": "file:x"},
            "node_tests": {"value": None, "reason": "tidak ada laporan", "evidence_source": "fs"},
        }
    }
    gate = ProductionCertificationGate(evidence)
    report = gate.evaluate()
    gate_a = next(g for g in report.gates if g.gate == "A")
    assert gate_a.checks["python_tests"] is True
    assert gate_a.checks["node_tests"] is None
    assert gate_a.to_dict()["reasons"]["python_tests"]["evidence_source"] == "file:x"


def test_default_evidence_all_gates_not_passed(tmp_path: Path) -> None:
    evidence = collect_gate_evidence(repo_root=tmp_path)
    gate = ProductionCertificationGate(evidence)
    report = gate.evaluate()
    assert report.status == ProductionStatus.NOT_READY.value
    for g in report.gates:
        assert g.passed is False
        assert "reasons" in g.to_dict()


def test_absent_artifact_is_unknown_not_true(tmp_path: Path) -> None:
    evidence = collect_gate_evidence(repo_root=tmp_path)
    for check in GATE_A_CHECKS:
        assert evidence["A"][check]["value"] is None


def test_present_artifact_is_true(tmp_path: Path) -> None:
    (tmp_path / "pytest_report.txt").write_text("1 passed", encoding="utf-8")
    evidence = collect_gate_evidence(repo_root=tmp_path)
    assert evidence["A"]["python_tests"]["value"] is True


def test_gate_b_probe_observed_healthy(tmp_path: Path) -> None:
    probes = {
        "risk_gate": lambda: (True, "validasi terakhir sehat", "risk_gate"),
        "kill_switch": lambda: (False, "kill switch aktif", "kill_switch"),
    }
    evidence = collect_gate_evidence(repo_root=tmp_path, gate_b_probes=probes)
    assert evidence["B"]["risk_gate"]["value"] is True
    assert evidence["B"]["kill_switch"]["value"] is False
    # untouched checks are unknown, not fabricated False
    assert evidence["B"]["circuit_breaker"]["value"] is None


def test_gate_c_no_backtest_is_false(tmp_path: Path) -> None:
    evidence = collect_gate_evidence(repo_root=tmp_path, research_records=[])
    assert evidence["C"]["backtest"]["value"] is False
    assert evidence["C"]["monte_carlo"]["value"] is None


def test_gate_c_completed_backtest_is_true(tmp_path: Path) -> None:
    records = [
        {
            "status": "COMPLETED",
            "metrics_summary": {"trades": 150},
            "validation_evidence": {"walk_forward": True, "sensitivity": True},
        }
    ]
    evidence = collect_gate_evidence(repo_root=tmp_path, research_records=records)
    assert evidence["C"]["backtest"]["value"] is True
    assert evidence["C"]["walk_forward"]["value"] is True
    assert evidence["C"]["parameter_sensitivity"]["value"] is True
    assert evidence["C"]["sufficient_sample"]["value"] is True
    assert evidence["C"]["monte_carlo"]["value"] is None


def test_execution_quality_evidence_reflects_records(tmp_path: Path) -> None:
    from src.observability.execution_quality import ExecutionQualityAnalytics, ExecutionRecord

    analytics = ExecutionQualityAnalytics()
    evidence = collect_gate_evidence(repo_root=tmp_path, execution_quality=analytics)
    assert evidence["E"]["execution_quality"]["value"] is False

    analytics.record(ExecutionRecord(requested_entry=1.0, actual_fill=1.0))
    evidence = collect_gate_evidence(repo_root=tmp_path, execution_quality=analytics)
    assert evidence["E"]["execution_quality"]["value"] is True


def test_certification_endpoint_reports_reasons() -> None:
    for name in ("_incident_manager", "_execution_quality"):
        setattr(v2_endpoints, name, None)
    r = client.get("/v2/certification/gate")
    assert r.status_code == 200
    body = r.json()["value"]
    assert body["status"] == "NOT_READY"
    assert all("reasons" in g for g in body["gates"])
    assert all("checks" in g for g in body["gates"])


def test_environment_precondition_details() -> None:
    r = client.get("/v2/environment")
    body = r.json()["value"]
    assert body["environment"] == "DEV"
    assert body["live_allowed"] is False
    assert "precondition_details" in body
    assert "arm_note" in body
    for name, detail in body["precondition_details"].items():
        assert "met" in detail
        assert "what_satisfies" in detail


class _FakeAccount:
    def model_dump(self) -> dict:
        return {
            "login": 555,
            "server": "Demo-Server",
            "currency": "USD",
            "trade_mode": "DEMO",
            "leverage": 100,
            "name": "tester",
            "balance": 10000.0,
        }


class _FakeConnector:
    def __init__(self, live: bool = True) -> None:
        self._live = live

    def is_live_mode(self) -> bool:
        return self._live

    def get_account_info(self):
        return _FakeAccount()


def test_read_attached_account_fake_connector() -> None:
    info = v2_endpoints._read_attached_account(_FakeConnector(live=True))
    assert info["available"] is True
    account = info["account"]
    assert account["login"] == 555
    assert account["server"] == "Demo-Server"
    assert account["currency"] == "USD"
    assert account["trade_mode"] == "DEMO"
    assert "password" not in account
    assert "token" not in account


def test_read_attached_account_unavailable() -> None:
    info = v2_endpoints._read_attached_account(_FakeConnector(live=False))
    assert info["available"] is False
    assert "unavailable_reason" in info
