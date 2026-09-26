# -*- coding: utf-8 -*-
"""RED→GREEN tests for certification evidence + real accounts (slice A/B/C)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from src.live_readiness.certification_evidence import (
    _normalize_store_records,
    _research_results_store,
    collect_gate_evidence,
)
from src.live_readiness.certification_gate import (
    GATE_A_CHECKS,
    ProductionCertificationGate,
    ProductionStatus,
)
from src.main import app
from src.research.store import ResearchStore
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
            "python_tests": {
                "value": True,
                "reason": "ok",
                "evidence_source": "file:x",
            },
            "node_tests": {
                "value": None,
                "reason": "tidak ada laporan",
                "evidence_source": "fs",
            },
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


def test_temp_fixture_dirs_are_not_evidence(tmp_path: Path) -> None:
    """Leftover pytest ``tmp_path`` fixture dirs must not count as CI evidence."""
    # top-level temp_pytest dir
    (tmp_path / "temp_pytest").mkdir()
    (tmp_path / "temp_pytest" / "pytest_report.txt").write_text(
        "1 passed", encoding="utf-8"
    )
    # nested case: deeper inside a temp fixture
    nested = tmp_path / "temp_pytest" / "test_present_artifact_is_true0"
    nested.mkdir()
    (nested / "pytest_report.txt").write_text("1 passed", encoding="utf-8")
    evidence = collect_gate_evidence(repo_root=tmp_path)
    assert evidence["A"]["python_tests"]["value"] is None

    # a real report dir outside any temp/hidden/build path is still honored
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "pytest_report.txt").write_text(
        "1 passed", encoding="utf-8"
    )
    evidence = collect_gate_evidence(repo_root=tmp_path)
    assert evidence["A"]["python_tests"]["value"] is True


def test_hidden_and_build_dirs_are_not_evidence(tmp_path: Path) -> None:
    """Hidden dirs and build/vendor caches must never be accepted as evidence."""
    for rel in ("node_modules", "dist", "build", "__pycache__", ".venv", ".cache"):
        d = tmp_path / rel
        d.mkdir()
        (d / "pytest_report.txt").write_text("1 passed", encoding="utf-8")
    evidence = collect_gate_evidence(repo_root=tmp_path)
    assert evidence["A"]["python_tests"]["value"] is None


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
    from src.observability.execution_quality import (
        ExecutionQualityAnalytics,
        ExecutionRecord,
    )

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


# ---------------------------------------------------------------------------
# CERT-C1 — research evidence wiring (RED→GREEN)
# ---------------------------------------------------------------------------


def test_normalize_backtest_result_record() -> None:
    """A raw ``backtest_result`` record → collector shape with real metrics."""
    records = [
        {
            "type": "backtest_result",
            "data": {
                "experiment_id": "exp-1",
                "total_trades": 141,
                "win_rate": 42.5,
                "profit_factor": 1.3,
                "net_pnl": 12.34,
                "walk_forward": {"enabled": True, "windows": []},
            },
        }
    ]
    normalized = _normalize_store_records(records)
    assert len(normalized) == 1
    record = normalized[0]
    assert record["status"] == "COMPLETED"
    assert record["metrics_summary"]["trades"] == 141
    assert record["metrics_summary"]["total_trades"] == 141
    assert record["validation_evidence"]["walk_forward"] is True


def test_normalize_backtest_result_without_walk_forward() -> None:
    records = [
        {"type": "backtest_result", "data": {"experiment_id": "e", "total_trades": 5}},
    ]
    normalized = _normalize_store_records(records)
    assert normalized[0]["validation_evidence"]["walk_forward"] is False


def test_normalize_validation_evidence_record() -> None:
    """A ``validation_evidence`` record carries MC + sensitivity evidence."""
    records = [
        {
            "type": "validation_evidence",
            "data": {
                "experiment_id": "exp-2",
                "status": "COMPLETED",
                "metrics_summary": {"trades": 121},
                "validation_evidence": {
                    "walk_forward": True,
                    "monte_carlo": {"status": "ROBUST", "median_return": 1.5},
                    "sensitivity": {"cliff_edge": False},
                },
            },
        }
    ]
    normalized = _normalize_store_records(records)
    assert len(normalized) == 1
    record = normalized[0]
    assert record["metrics_summary"]["trades"] == 121
    assert record["validation_evidence"]["monte_carlo"]["status"] == "ROBUST"
    assert record["validation_evidence"]["sensitivity"]["cliff_edge"] is False


def test_normalize_skips_malformed_and_unknown_records() -> None:
    records = [
        "not-a-dict",
        {"type": "hypothesis", "data": {"id": "h"}},
        {"type": "backtest_result", "data": "not-a-dict"},
        {"type": "backtest_result", "data": {"experiment_id": "ok", "total_trades": 3}},
    ]
    normalized = _normalize_store_records(records)
    assert len(normalized) == 1
    assert normalized[0]["metrics_summary"]["trades"] == 3


def test_store_read_uses_research_state_path(tmp_path: Path, monkeypatch) -> None:
    """``RESEARCH_STATE_PATH`` env override is honoured (no hardcoded path)."""
    path = tmp_path / "research_state.jsonl"
    store = ResearchStore(path)
    store.append(
        "backtest_result",
        {"experiment_id": "e1", "total_trades": 120, "walk_forward": {"enabled": True}},
    )
    monkeypatch.setenv("RESEARCH_STATE_PATH", str(path))
    records = _research_results_store()
    assert records is not None
    assert records[0]["metrics_summary"]["trades"] == 120


def test_store_read_uses_explicit_path(tmp_path: Path) -> None:
    path = tmp_path / "explicit.jsonl"
    store = ResearchStore(path)
    store.append(
        "validation_evidence",
        {
            "experiment_id": "e2",
            "status": "COMPLETED",
            "metrics_summary": {"trades": 150},
            "validation_evidence": {
                "walk_forward": True,
                "monte_carlo": {"status": "ROBUST"},
                "sensitivity": {"cliff_edge": False},
            },
        },
    )
    records = _research_results_store(store_path=path)
    assert records is not None
    assert records[0]["metrics_summary"]["trades"] == 150


def test_gate_c_all_five_pass_from_real_store(tmp_path: Path) -> None:
    """A store with a completed backtest + validation evidence → Gate C 5/5."""
    path = tmp_path / "research_state.jsonl"
    store = ResearchStore(path)
    store.append(
        "backtest_result",
        {
            "experiment_id": "e",
            "total_trades": 141,
            "win_rate": 42.0,
            "walk_forward": {"enabled": True, "windows": []},
        },
    )
    store.append(
        "validation_evidence",
        {
            "experiment_id": "e",
            "status": "COMPLETED",
            "metrics_summary": {"trades": 141},
            "validation_evidence": {
                "walk_forward": True,
                "monte_carlo": {"status": "ROBUST"},
                "sensitivity": {"cliff_edge": False},
            },
        },
    )
    records = _research_results_store(store_path=path)
    evidence = collect_gate_evidence(repo_root=tmp_path, research_records=records)
    gate_c = evidence["C"]
    assert gate_c["backtest"]["value"] is True
    assert gate_c["walk_forward"]["value"] is True
    assert gate_c["monte_carlo"]["value"] is True
    assert gate_c["parameter_sensitivity"]["value"] is True
    assert gate_c["sufficient_sample"]["value"] is True


def test_store_read_absent_path_is_observable_empty(tmp_path: Path) -> None:
    """A missing store file is observable-empty (=> no backtests, False)."""
    records = _research_results_store(store_path=tmp_path / "does-not-exist.jsonl")
    assert records == []
    evidence = collect_gate_evidence(repo_root=tmp_path, research_records=records)
    assert evidence["C"]["backtest"]["value"] is False
    assert evidence["C"]["monte_carlo"]["value"] is None


def test_collector_reads_real_store_no_hardcoded_numbers(tmp_path: Path) -> None:
    """The collector reports the *real* max sample trade count from the store."""
    path = tmp_path / "research_state.jsonl"
    store = ResearchStore(path)
    store.append("backtest_result", {"experiment_id": "a", "total_trades": 80})
    store.append("backtest_result", {"experiment_id": "b", "total_trades": 175})
    records = _research_results_store(store_path=path)
    evidence = collect_gate_evidence(repo_root=tmp_path, research_records=records)
    assert "175" in evidence["C"]["sufficient_sample"]["reason"]
    assert evidence["C"]["sufficient_sample"]["value"] is True
