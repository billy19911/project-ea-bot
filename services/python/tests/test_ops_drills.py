# -*- coding: utf-8 -*-
"""RED→GREEN tests for Gate D ops-drill evidence (CERT-D1).

Two things are proven here, without ever touching a live service:

* the **collector** (``_collect_gate_d``) reads REAL drill records from a JSONL
  store and maps them to evidence — a ``passed`` record yields ``True`` with a
  reason (timestamp + honest method), a ``failed`` record yields ``False`` and
  an absent/never-written drill stays ``unknown`` (``None`` — never a
  fabricated pass);
* the **runner** (``scripts/run_ops_drills.py``) enforces a per-drill timeout
  and runs its rollback in ``finally`` even when the drill raises — proven with
  fakes so no real service is stopped.

The tests never import the live service, never restart anything, and never
write to the real ``services/python/logs/ops_drills.jsonl``.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from src.live_readiness.certification_evidence import _collect_gate_d

# The 7 Gate D drills the collector must know about.
DRILLS = (
    "mt5_restart",
    "pc_restart",
    "mt5_disconnect",
    "database_failure",
    "llm_failure",
    "nine_router_failure",
    "telegram_failure",
)


def _write_records(path: Path, records: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")


# ---------------------------------------------------------------------------
# Collector: record → True + reason
# ---------------------------------------------------------------------------


def test_passed_record_is_true_with_reason(tmp_path: Path) -> None:
    store = tmp_path / "ops_drills.jsonl"
    _write_records(
        store,
        [
            {
                "drill": "mt5_restart",
                "status": "passed",
                "at": "2026-01-02T03:04:05+00:00",
                "method": "stop terminal → start → verifikasi reconnect",
            }
        ],
    )
    evidence = _collect_gate_d(drills_path=store)
    assert evidence["mt5_restart"]["value"] is True
    reason = evidence["mt5_restart"]["reason"]
    assert "mt5_restart" in reason
    assert "2026-01-02T03:04:05+00:00" in reason
    assert "stop terminal" in reason
    assert evidence["mt5_restart"]["evidence_source"] == "ops_drill"


def test_all_seven_passed_records(tmp_path: Path) -> None:
    store = tmp_path / "ops_drills.jsonl"
    _write_records(
        store,
        [
            {
                "drill": drill,
                "status": "passed",
                "at": "2026-01-01T00:00:00+00:00",
                "method": drill,
            }
            for drill in DRILLS
        ],
    )
    evidence = _collect_gate_d(drills_path=store)
    assert set(evidence) == set(DRILLS)
    for drill in DRILLS:
        assert evidence[drill]["value"] is True


def test_last_record_per_drill_wins(tmp_path: Path) -> None:
    """A later failed record must override an earlier passed one."""
    store = tmp_path / "ops_drills.jsonl"
    _write_records(
        store,
        [
            {
                "drill": "pc_restart",
                "status": "passed",
                "at": "2026-01-01T00:00:00",
                "method": "m1",
            },
            {
                "drill": "pc_restart",
                "status": "failed",
                "at": "2026-01-02T00:00:00",
                "method": "m2",
            },
        ],
    )
    evidence = _collect_gate_d(drills_path=store)
    assert evidence["pc_restart"]["value"] is False


def test_last_record_wins_when_recovered(tmp_path: Path) -> None:
    """A later passed record must override an earlier failed one."""
    store = tmp_path / "ops_drills.jsonl"
    _write_records(
        store,
        [
            {
                "drill": "llm_failure",
                "status": "failed",
                "at": "2026-01-01T00:00:00",
                "method": "m1",
            },
            {
                "drill": "llm_failure",
                "status": "passed",
                "at": "2026-01-02T00:00:00",
                "method": "m2",
            },
        ],
    )
    evidence = _collect_gate_d(drills_path=store)
    assert evidence["llm_failure"]["value"] is True


# ---------------------------------------------------------------------------
# Collector: absence → unknown
# ---------------------------------------------------------------------------


def test_absent_store_is_unknown_not_true(tmp_path: Path) -> None:
    evidence = _collect_gate_d(drills_path=tmp_path / "does-not-exist.jsonl")
    for drill in DRILLS:
        assert evidence[drill]["value"] is None


def test_drill_with_no_record_is_unknown(tmp_path: Path) -> None:
    store = tmp_path / "ops_drills.jsonl"
    _write_records(
        store,
        [{"drill": "mt5_restart", "status": "passed", "at": "t", "method": "m"}],
    )
    evidence = _collect_gate_d(drills_path=store)
    assert evidence["mt5_restart"]["value"] is True
    assert evidence["telegram_failure"]["value"] is None


# ---------------------------------------------------------------------------
# Collector: status failed → False
# ---------------------------------------------------------------------------


def test_failed_status_is_false(tmp_path: Path) -> None:
    store = tmp_path / "ops_drills.jsonl"
    _write_records(
        store,
        [
            {
                "drill": "database_failure",
                "status": "failed",
                "at": "t",
                "method": "restore gagal",
            }
        ],
    )
    evidence = _collect_gate_d(drills_path=store)
    assert evidence["database_failure"]["value"] is False
    assert "failed" in evidence["database_failure"]["reason"]


# ---------------------------------------------------------------------------
# Collector: broken file → unknown
# ---------------------------------------------------------------------------


def test_corrupt_lines_do_not_crash(tmp_path: Path) -> None:
    store = tmp_path / "ops_drills.jsonl"
    store.write_text(
        "not-json\n"
        '{"drill": "mt5_restart", "status": "passed", "at": "t", "method": "m"}\n'
        "\n"
        "[1, 2, 3]\n",
        encoding="utf-8",
    )
    evidence = _collect_gate_d(drills_path=store)
    assert evidence["mt5_restart"]["value"] is True
    # A skipped malformed line must not fabricate a pass for another drill.
    assert evidence["pc_restart"]["value"] is None


def test_unknown_drill_name_is_ignored(tmp_path: Path) -> None:
    store = tmp_path / "ops_drills.jsonl"
    _write_records(
        store,
        [{"drill": "not_a_real_drill", "status": "passed", "at": "t", "method": "m"}],
    )
    evidence = _collect_gate_d(drills_path=store)
    assert set(evidence) == set(DRILLS)


def test_env_override_path(tmp_path: Path, monkeypatch) -> None:
    """``OPS_DRILLS_PATH`` env override is honoured when no param is passed."""
    store = tmp_path / "env_store.jsonl"
    _write_records(
        store,
        [
            {
                "drill": "nine_router_failure",
                "status": "passed",
                "at": "t",
                "method": "m",
            }
        ],
    )
    monkeypatch.setenv("OPS_DRILLS_PATH", str(store))
    evidence = _collect_gate_d()
    assert evidence["nine_router_failure"]["value"] is True


def test_env_points_to_broken_path_is_unknown(tmp_path: Path, monkeypatch) -> None:
    """An unreadable store (a directory) must degrade to unknown, not crash."""
    bad = tmp_path / "a_directory"
    bad.mkdir()
    monkeypatch.setenv("OPS_DRILLS_PATH", str(bad))
    evidence = _collect_gate_d()
    for drill in DRILLS:
        assert evidence[drill]["value"] is None


# ---------------------------------------------------------------------------
# Runner: lazy import without executing module side effects
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def runner_module():
    """Import ``scripts/run_ops_drills.py`` without running anything.

    The module is imported via ``importlib`` (not executed as a script) so its
    CLI ``main`` never fires. It must guard all side effects behind
    ``if __name__ == "__main__"``.
    """
    repo_root = Path(__file__).resolve().parents[3]
    module_path = repo_root / "scripts" / "run_ops_drills.py"
    assert module_path.is_file(), f"runner missing: {module_path}"
    spec = importlib.util.spec_from_file_location("run_ops_drills", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_ops_drills"] = module
    spec.loader.exec_module(module)
    return module


def test_runner_exposes_seven_drills(runner_module) -> None:
    names = set(runner_module.DRILLS)
    assert set(DRILLS) == names


def test_runner_timeout_wraps_slow_drill(runner_module, monkeypatch, tmp_path) -> None:
    """A hanging drill must be cut off by the per-drill timeout, and the
    rollback must still run in ``finally`` — nothing is left un-rolled-back."""
    events: list[str] = []

    def _hang(*_args, **_kwargs) -> None:
        import time

        events.append("drill-start")
        time.sleep(30)  # would hang far past the timeout
        events.append("drill-end")  # pragma: no cover - never reached

    def _rollback(*_args, **_kwargs) -> None:
        events.append("rollback")

    monkeypatch.setattr(runner_module, "run_mt5_restart", _hang)
    store = tmp_path / "ops_drills.jsonl"
    runner = runner_module.OpsDrillRunner(drills_path=store, drill_timeout_s=1)

    record = runner.run_one("mt5_restart", rollback=_rollback)

    assert record["status"] == "failed"
    assert record["drill"] == "mt5_restart"
    assert "rollback" in events
    assert "drill-end" not in events


def test_runner_rollback_runs_on_exception(
    runner_module, monkeypatch, tmp_path
) -> None:
    events: list[str] = []

    def _boom(*_args, **_kwargs) -> None:
        events.append("drill")
        raise RuntimeError("drill exploded")

    def _rollback(*_args, **_kwargs) -> None:
        events.append("rollback")

    monkeypatch.setattr(runner_module, "run_llm_failure", _boom)
    store = tmp_path / "ops_drills.jsonl"
    runner = runner_module.OpsDrillRunner(drills_path=store, drill_timeout_s=5)

    record = runner.run_one("llm_failure", rollback=_rollback)

    assert record["status"] == "failed"
    assert events == ["drill", "rollback"]
    assert "drill exploded" in record["detail"]


def test_runner_persists_record_with_honest_fields(
    runner_module, monkeypatch, tmp_path
) -> None:
    def _ok(*_args, **_kwargs) -> dict:
        return {"ok": True}

    monkeypatch.setattr(runner_module, "run_pc_restart", _ok)
    store = tmp_path / "ops_drills.jsonl"
    runner = runner_module.OpsDrillRunner(drills_path=store, drill_timeout_s=5)

    record = runner.run_one("pc_restart", rollback=lambda *a, **k: None)

    assert record["status"] == "passed"
    assert record["drill"] == "pc_restart"
    assert record["method"]  # every record carries an honest method
    assert "at" in record
    # The record must be readable back by the collector.
    evidence = _collect_gate_d(drills_path=store)
    assert evidence["pc_restart"]["value"] is True


def test_runner_records_failure_when_verification_fails(
    runner_module, monkeypatch, tmp_path
) -> None:
    """A drill that returns ``{"ok": False}`` must be recorded failed."""

    def _not_ok(*_args, **_kwargs) -> dict:
        return {"ok": False, "detail": "service tidak sehat sesudah drill"}

    monkeypatch.setattr(runner_module, "run_telegram_failure", _not_ok)
    store = tmp_path / "ops_drills.jsonl"
    runner = runner_module.OpsDrillRunner(drills_path=store, drill_timeout_s=5)

    record = runner.run_one("telegram_failure", rollback=lambda *a, **k: None)

    assert record["status"] == "failed"
    evidence = _collect_gate_d(drills_path=store)
    assert evidence["telegram_failure"]["value"] is False
