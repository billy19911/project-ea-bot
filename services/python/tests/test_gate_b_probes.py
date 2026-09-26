# -*- coding: utf-8 -*-
"""RED→GREEN tests for Gate B runtime probes + endpoint wiring (CERT-B2).

Proves that:
* the certification endpoint sends ``gate_b_probes`` (all seven checks), and
* every probe reads REAL runtime state — normal → ``True``, bad → ``False``,
  exception/unobservable → ``None`` (unknown), never a crash.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from src.execution import intents as intents_mod
from src.execution import state_machine
from src.live_readiness.certification_gate import GATE_B_CHECKS
from src.main import app
from src.orchestration.runtime import OrchestrationRuntime, set_runtime
from src.risk import kill_switch as kill_switch_mod
from src.system import gate_b_probes as gbp
from src.system import v2_endpoints

client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolated_runtime(monkeypatch, tmp_path):
    """Give each test a fresh runtime and detach global durable stores.

    The probes read process-global singletons (runtime, kill-switch store,
    intent store). Isolating them keeps the assertions about REAL state
    deterministic.
    """
    runtime = OrchestrationRuntime()
    set_runtime(runtime)
    # Reset durable store hooks to a clean state; individual tests re-attach
    # the stores they need.
    kill_switch_mod.set_kill_switch_store(None)
    intents_mod.set_store(None)
    state_machine.set_store(None)
    v2_endpoints._circuit_breaker = None
    yield runtime
    set_runtime(None)
    kill_switch_mod.set_kill_switch_store(None)
    intents_mod.set_store(None)
    state_machine.set_store(None)
    v2_endpoints._circuit_breaker = None


# ---------------------------------------------------------------------------
# Interface contract
# ---------------------------------------------------------------------------


def test_probes_match_gate_b_checks() -> None:
    probes = gbp.build_gate_b_probes()
    assert set(probes) == set(GATE_B_CHECKS)
    assert len(probes) == 7


def test_every_probe_returns_triple_or_none() -> None:
    for name, probe in gbp.build_gate_b_probes().items():
        result = probe()
        assert isinstance(result, tuple) and len(result) == 3, name
        value, reason, source = result
        assert value in (True, False, None), name
        assert isinstance(reason, str)
        assert isinstance(source, str)


# ---------------------------------------------------------------------------
# risk_gate
# ---------------------------------------------------------------------------


def test_risk_gate_normal_true() -> None:
    value, _reason, _source = gbp._probe_risk_gate()
    assert value is True


def test_risk_gate_bad_when_require_approval_off(_isolated_runtime) -> None:
    _isolated_runtime.pipeline.execution_engine.require_approval = False
    value, reason, _source = gbp._probe_risk_gate()
    assert value is False
    assert "require_approval" in reason


def test_risk_gate_bad_when_no_gate(_isolated_runtime) -> None:
    _isolated_runtime.pipeline.risk_gate = None
    value, _reason, _source = gbp._probe_risk_gate()
    assert value is False


# ---------------------------------------------------------------------------
# kill_switch
# ---------------------------------------------------------------------------


def test_kill_switch_normal_true() -> None:
    value, reason, _source = gbp._probe_kill_switch()
    assert value is True
    assert "state=active" in reason


def test_kill_switch_blocked_false() -> None:
    class _Store:
        def load_state(self):
            return {"state": "locked", "locked": True}

    kill_switch_mod.set_kill_switch_store(_Store())
    value, reason, _source = gbp._probe_kill_switch()
    assert value is False
    assert "BLOCKED" in reason


# ---------------------------------------------------------------------------
# circuit_breaker
# ---------------------------------------------------------------------------


def test_circuit_breaker_normal_true() -> None:
    value, reason, _source = gbp._probe_circuit_breaker()
    assert value is True
    assert "level=normal" in reason


def test_circuit_breaker_bad_false() -> None:
    from src.risk.multi_level_breaker import BreakerLevel, TriggerType

    breaker = v2_endpoints.get_circuit_breaker()
    breaker.trigger(TriggerType.MANUAL, "test")  # escalates to HALTED (latched)
    value, reason, _source = gbp._probe_circuit_breaker()
    assert value is False
    assert "NOT normal" in reason
    assert BreakerLevel.HALTED.value


# ---------------------------------------------------------------------------
# duplicate_prevention
# ---------------------------------------------------------------------------


def test_duplicate_prevention_true_when_store_attached() -> None:
    class _Store:
        def all_intents(self):
            return {}

    intents_mod.set_store(_Store())
    value, reason, _source = gbp._probe_duplicate_prevention()
    assert value is True
    assert "dedup" in reason


def test_duplicate_prevention_false_without_store() -> None:
    value, reason, _source = gbp._probe_duplicate_prevention()
    assert value is False
    assert "intent store" in reason


# ---------------------------------------------------------------------------
# broker_spec
# ---------------------------------------------------------------------------


def test_broker_spec_valid_true() -> None:
    value, reason, _source = gbp._probe_broker_spec()
    assert value is True
    assert "digits=" in reason


def test_broker_spec_unknown_when_no_info(monkeypatch) -> None:
    import src.mt5.connector as connector

    monkeypatch.setattr(connector, "get_symbol_info", lambda symbol: None)
    value, reason, _source = gbp._probe_broker_spec()
    assert value is None
    assert "tidak tersedia" in reason


def test_broker_spec_unknown_on_exception(monkeypatch) -> None:
    import src.mt5.connector as connector

    def _boom(symbol):
        raise RuntimeError("broker down")

    monkeypatch.setattr(connector, "get_symbol_info", _boom)
    value, reason, _source = gbp._probe_broker_spec()
    assert value is None
    assert "gagal" in reason


# ---------------------------------------------------------------------------
# reconciliation
# ---------------------------------------------------------------------------


def test_reconciliation_true_after_clean_run(_isolated_runtime) -> None:
    _isolated_runtime._reconciliation_runner.run_once()
    value, reason, _source = gbp._probe_reconciliation()
    assert value is True
    assert "critical=False" in reason


def test_reconciliation_false_when_no_report() -> None:
    value, reason, _source = gbp._probe_reconciliation()
    assert value is False
    assert "belum ada" in reason


# ---------------------------------------------------------------------------
# recovery
# ---------------------------------------------------------------------------


def test_recovery_false_without_stores() -> None:
    value, reason, _source = gbp._probe_recovery()
    assert value is False
    assert "tidak terpasang" in reason


def test_recovery_true_when_stores_attached() -> None:
    class _KS:
        def load_state(self):
            return {"state": "active"}

    class _Monitor:
        reconciliation_store = object()

    kill_switch_mod.set_kill_switch_store(_KS())
    state_machine.set_store(object())

    # Wire the runtime position monitor's reconciliation store.
    class _Rt:
        position_monitor = _Monitor()

    from src.orchestration import runtime as rt_mod

    rt_mod.set_runtime(_Rt())
    value, reason, _source = gbp._probe_recovery()
    assert value is True
    assert "durable stores terpasang" in reason


# ---------------------------------------------------------------------------
# Endpoint wiring
# ---------------------------------------------------------------------------


def test_endpoint_sends_gate_b_probes() -> None:
    r = client.get("/v2/certification/gate")
    assert r.status_code == 200
    body = r.json()["value"]
    gate_b = next(g for g in body["gates"] if g["gate"] == "B")
    # All seven checks are present and, with the live/wired state, NOT the
    # generic "probe runtime tidak tersedia" placeholder.
    assert set(gate_b["checks"]) == set(GATE_B_CHECKS)
    for name in GATE_B_CHECKS:
        reason = gate_b["reasons"].get(name, {}).get("reason", "")
        assert "probe runtime tidak tersedia" not in reason, name


def test_endpoint_reports_probe_reasons() -> None:
    r = client.get("/v2/certification/gate")
    body = r.json()["value"]
    gate_b = next(g for g in body["gates"] if g["gate"] == "B")
    # Every probe contributes a human reason + evidence source.
    for name in GATE_B_CHECKS:
        entry = gate_b["reasons"].get(name)
        assert entry is not None, name
        assert entry.get("evidence_source"), name
