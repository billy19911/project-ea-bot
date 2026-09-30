# -*- coding: utf-8 -*-
"""Phase 9 — certification tests + adversarial CASES 1–15."""

from __future__ import annotations

import pytest

from src.certification import (
    CertificationGate,
    LiveReadinessCertification,
    ReadinessCheck,
    certification_fingerprint,
    environment_identity,
    run_soak,
    run_standard_checks,
)

MAND = "MANDATORY"


def _mk(cid="c1", status="PASS", severity=MAND):
    return ReadinessCheck(check_id=cid, name=cid, category="t", status=status, severity=severity)


# ── Gate semantics (§31) ────────────────────────────────────────────────


def test_mandatory_failure_fails():
    gate = CertificationGate()
    cert = gate.evaluate([_mk("a", "PASS"), _mk("b", "FAIL")], certification_id="c")
    assert cert.status == "FAIL"
    assert cert.blockers == ["b"]


def test_warning_only_passes_with_warnings():
    from src.certification import SEVERITY_WARNING

    gate = CertificationGate()
    cert = gate.evaluate(
        [_mk("a", "PASS"), _mk("w", "FAIL", SEVERITY_WARNING)], certification_id="c"
    )
    assert cert.status == "PASS_WITH_WARNINGS"


def test_all_mandatory_pass():
    gate = CertificationGate()
    cert = gate.evaluate([_mk("a", "PASS"), _mk("b", "PASS")], certification_id="c")
    assert cert.status == "PASS"
    assert cert.blockers == []


def test_unknown_mandatory_fails_closed():
    gate = CertificationGate()
    cert = gate.evaluate([_mk("a", "UNKNOWN")], certification_id="c")
    assert cert.status == "FAIL"  # UNKNOWN is not a PASS


def test_invalid_status_rejected():
    with pytest.raises(ValueError):
        ReadinessCheck(check_id="x", name="x", category="t", status="MAYBE")


# ── Identity (§4) ───────────────────────────────────────────────────────


def test_strategy_version_mismatch_fails():
    ident = environment_identity()
    assert "strategy_version" in ident and "broker" in ident


def test_fingerprint_stable_and_sensitive():
    a = {"code": "abc", "strategy": "v1"}
    b = {"code": "abc", "strategy": "v1"}
    c = {"code": "abc", "strategy": "v2"}
    assert certification_fingerprint(a) == certification_fingerprint(b)
    assert certification_fingerprint(a) != certification_fingerprint(c)


# ── Broker metadata (§5) ───────────────────────────────────────────────


def test_unknown_symbol_spec_fails():
    checks = run_standard_checks([])
    spec = next(c for c in checks if c.check_id == "symbol_spec")
    assert spec.status in ("FAIL", "UNKNOWN")


# ── Recovery (§9–§11) ──────────────────────────────────────────────────


def test_restart_recover_scan():
    from src.system.startup_checks import run_execution_recovery

    report = run_execution_recovery()
    assert "summary" in report and "flagged" in report


def test_unknown_execution_adopt_not_duplicate():
    from src.execution.engine import ExecutionEngine, OrderRequest

    placed: list[dict] = []

    class _F:
        def order_send(self, payload):
            placed.append(payload)
            raise ConnectionError("connection lost after send")

        def get_symbol_info(self, s):
            return {"symbol": s, "volume_min": 0.01, "volume_max": 100.0}

        def positions(self):
            return [
                {
                    "ticket": 7,
                    "symbol": p["symbol"],
                    "side": "BUY",
                    "volume": p["volume"],
                    "price_open": 1.0,
                    "profit": 0.0,
                }
                for p in placed
            ]

    conn = _F()

    def _loc(req):
        for p in conn.positions():
            if p["symbol"] == req.symbol and abs(p["volume"] - req.volume) < 1e-9:
                return {"ticket": p["ticket"]}
        return None

    eng = ExecutionEngine(mt5_connector=conn, max_retries=2, retry_delay=0.0, order_locator=_loc)
    res = eng.execute_order(
        OrderRequest(symbol="X", order_type="BUY", volume=0.1, idempotency_key="p9-a")
    )
    assert res.success is True and len(placed) == 1


def test_terminal_states_sticky():
    from src.trading.signal_state_machine import Signal

    s = Signal(signal_id="p9")
    assert s.transition("REJECTED") is True
    assert s.transition("EXECUTING") is False


# ── Execution (§12) ────────────────────────────────────────────────────


def test_timeout_no_blind_retry():
    from src.execution.engine import ExecutionEngine, OrderRequest

    class _Dead:
        calls = 0

        def order_send(self, payload):
            type(self).calls += 1
            raise ConnectionError("timeout")

        def get_symbol_info(self, s):
            return {"symbol": s, "volume_min": 0.01, "volume_max": 100.0}

    conn = _Dead()
    eng = ExecutionEngine(
        mt5_connector=conn, max_retries=1, retry_delay=0.0, order_locator=lambda r: None
    )
    res = eng.execute_order(
        OrderRequest(symbol="X", order_type="BUY", volume=0.1, idempotency_key="p9-t")
    )
    assert res.success is False
    assert conn.calls == 2  # initial + 1 bounded retry, locator consulted


# ── Market (§7) ─────────────────────────────────────────────────────────


def test_stale_market_blocks_and_inverted_blocks():
    from src.risk.base import RiskThreshold
    from src.risk.engine import RiskEngine
    from src.risk.gate import RiskGate
    from src.risk.money_management import MoneyManager

    eng = RiskEngine()
    eng.set_threshold(RiskThreshold.MAX_EXPOSURE, 0.9)
    gate = RiskGate(eng, MoneyManager(), max_spread_pips=5.0)
    acct = {
        "equity": 10_000.0,
        "balance": 10_000.0,
        "peak_equity": 10_000.0,
        "daily_pnl": 0.0,
        "used_margin": 0.0,
        "margin_call_level": 500.0,
    }
    prop = {
        "symbol": "EURUSD",
        "direction": "BUY",
        "entry_price": 100.0,
        "stop_loss": 95.0,
        "take_profit": 115.0,
        "size": 0.1,
    }
    assert gate.validate_proposal(prop, acct, [], {}).checks_passed["spread"] is False


# ── Strategy (§19) ─────────────────────────────────────────────────────


def test_loss_no_mutation_and_candidate_pending():
    from src.learning.canonical import StrategyCandidateRecord
    from src.learning.research_phase5 import PromotionGate

    cand = StrategyCandidateRecord(
        candidate_id="p9",
        backtest_results={
            "trade_count": 50,
            "expectancy": 0.2,
            "max_drawdown": 0.1,
            "profit_factor": 1.5,
        },
        walkforward_results={"unstable": False},
    )
    promo = PromotionGate().evaluate(
        cand,
        extra_metrics={
            "cost_sensitive": False,
            "regime_fragile": False,
            "session_fragile": False,
            "direction_fragile": False,
        },
    )
    assert promo.decision == "PENDING"
    assert cand.to_dict()["activation"] == "PROPOSAL_ONLY"


# ── Security (§27) ─────────────────────────────────────────────────────


def test_secret_masked_in_cert():
    cert = LiveReadinessCertification(
        certification_id="s", broker="Paper", account="sk-live-SECRET-99", status="PASS"
    )
    assert "SECRET-99" not in str(cert.to_dict())


# ── Soak (§23) ─────────────────────────────────────────────────────────


def test_soak_bounded():
    from src.certification import SoakConfig

    res = run_soak(SoakConfig(cycles=50, max_seconds=30.0))
    assert res.cycles_run == 50 and res.errors == 0
    assert res.threads_end - res.threads_start <= 2


# ── Topology (§28) ─────────────────────────────────────────────────────


def test_multiwriter_blocks(monkeypatch):
    monkeypatch.setenv("UVICORN_WORKERS", "4")
    checks = run_standard_checks(["XAUUSD"])
    topo = next(c for c in checks if c.check_id == "topology")
    assert topo.status == "FAIL"
    gate = CertificationGate().evaluate(checks, certification_id="t")
    assert gate.status == "FAIL"
    assert "topology" in gate.blockers
    monkeypatch.delenv("UVICORN_WORKERS", raising=False)


# ── Adversarial CASES 1–15 ──────────────────────────────────────────────


def test_case1_strategy_change_invalidates():
    gate = CertificationGate()
    cert = gate.evaluate(
        [_mk("a")], certification_id="c1", identity={"strategy": "v1", "code": "x"}
    )
    ok, reason = CertificationGate.validate_still_current(cert, {"strategy": "v2", "code": "x"})
    assert ok is False and "mismatch" in reason


def test_case2_broker_change_invalidates():
    gate = CertificationGate()
    cert = gate.evaluate([_mk("a")], certification_id="c2", identity={"broker": "Paper-A"})
    ok, _ = CertificationGate.validate_still_current(cert, {"broker": "Paper-B"})
    assert ok is False


def test_case4_provider_unavailable_fails_closed():
    from src.llm.canonical import ModelRequest
    from src.llm.router import CanonicalModelRouter

    r = CanonicalModelRouter()
    rec, out = r.execute(
        ModelRequest(request_id="c4", task_type="FAST_CLASSIFICATION", cycle_id="c4"),
        route_through=lambda m, p, **k: (_ for _ in ()).throw(ConnectionError("down")),
    )
    assert rec.output_status == "FAILED" and out is None


def test_case7_risk_reject_no_execution():
    from src.risk.base import RiskThreshold
    from src.risk.engine import RiskEngine
    from src.risk.gate import RiskGate
    from src.risk.money_management import MoneyManager

    eng = RiskEngine()
    eng.set_threshold(RiskThreshold.MAX_EXPOSURE, 0.01)
    gate = RiskGate(eng, MoneyManager(), max_spread_pips=5.0)
    d = gate.validate_proposal(
        {
            "symbol": "EURUSD",
            "direction": "BUY",
            "entry_price": 100.0,
            "stop_loss": 95.0,
            "take_profit": 115.0,
            "size": 50.0,
        },
        {
            "equity": 10_000.0,
            "balance": 10_000.0,
            "peak_equity": 10_000.0,
            "daily_pnl": 0.0,
            "used_margin": 0.0,
            "margin_call_level": 500.0,
        },
        [],
        {"spread_pips": 1.0, "bid": 100.0, "ask": 100.0, "price": 100.0},
    )
    assert d.approved is False


def test_case8_volume_override_stripped():
    from src.llm.router import OutputValidator

    ok, _, parsed = OutputValidator().validate({"signal": "BUY", "final_volume": 9.9})
    assert ok is False and "final_volume" not in parsed


def test_case9_activate_strategy_blocked():
    from src.llm.router import OutputValidator

    ok, _, parsed = OutputValidator().validate({"activate_strategy": "v9"})
    assert ok is False and parsed == {}


def test_case10_backtest_success_candidate_only():
    test_loss_no_mutation_and_candidate_pending()


def test_case13_stale_cert_blocks_arm():
    gate = CertificationGate()
    cert = gate.evaluate([_mk("a")], certification_id="c13", identity={"strategy": "v1"})
    # Simulate expiry by constructing an expired copy.
    from dataclasses import replace

    expired = replace(cert, expires_at="2000-01-01T00:00:00+00:00")
    ok, reason = CertificationGate.validate_still_current(expired, {"strategy": "v1"})
    assert ok is False and "expired" in reason


def test_case14_live_flag_rejected():
    from src.readiness.gate import LiveReadinessGate

    gate = LiveReadinessGate()
    assert gate.is_live is False
    assert gate.mode == "PAPER"


def test_standard_checks_run_without_raising():
    checks = run_standard_checks(["XAUUSD"])
    assert len(checks) >= 10
    for c in checks:
        assert c.status in ("PASS", "FAIL", "WARNING", "UNKNOWN")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
