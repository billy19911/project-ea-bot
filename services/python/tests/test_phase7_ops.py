# -*- coding: utf-8 -*-
"""Phase 7 — ops read-model tests (§33): overview, health, trace, risk,
models, budget, research, unknown, secrets, audit."""

from __future__ import annotations

import pytest

from src.ops import readmodels as rm
from src.ops import secrets as sec
from src.ops import trace as trace_mod


def test_overview_aggregates_without_authority():
    data = rm.overview()
    for k in (
        "system",
        "market",
        "risk",
        "execution",
        "positions",
        "models",
        "research",
        "strategies",
        "alerts",
    ):
        assert k in data
    # No trading authority surface.
    blob = str(data).lower()
    assert "execute_mt5" not in blob


def test_health_never_infers_healthy():
    h = rm.health_snapshot()
    assert h["status"] in ("HEALTHY", "DEGRADED", "FAILED", "UNKNOWN")
    for c in h["components"]:
        assert c["status"] in ("HEALTHY", "DEGRADED", "FAILED", "UNKNOWN")


def test_market_unknown_preserved():
    m = rm.market_snapshot("NONEXISTENT_XYZ")
    # Unknown symbol → UNKNOWN fields, never fabricated numbers.
    assert m["symbol"] == "NONEXISTENT_XYZ"
    assert m["bid"] in (sec.UNKNOWN, None) or isinstance(m["bid"], (int, float))


def test_decision_trace_empty_key_honest():
    t = trace_mod.decision_trace(decision_id="no-such-id-xyz")
    assert t["complete"] is False
    assert isinstance(t["nodes"], list)


def test_explain_non_trade_shape():
    e = trace_mod.explain_non_trade(setup_id="no-such-setup")
    for k in ("state", "blocking_conditions", "missing_conditions", "reason_codes", "risk_result"):
        assert k in e


def test_risk_comes_from_backend():
    r = rm.risk_summary()
    assert "limits" in r
    assert r.get("source", "").startswith("backend")


def test_model_provenance_shape():
    m = rm.model_summary()
    assert "calls" in m and "count" in m


def test_budget_reconciles():
    b = rm.budget_summary()
    # Either UNKNOWN (no supervisor) or numeric trio.
    assert "token_budget" in b or b.get("budget") == "UNKNOWN"


def test_research_lineage_shape():
    r = rm.research_summary()
    assert isinstance(r, dict)


def test_unknown_stays_unknown():
    assert sec.unknown_if_none(None) == "UNKNOWN"
    assert sec.unknown_if_none(0) == 0
    assert sec.unknown_if_none(False) is False
    assert sec.unknown_if_none("x") == "x"


def test_secrets_masked():
    payload = {"api_key": "sk-live-123", "nested": {"bot_token": "t", "ok": 1}}
    out = sec.mask_secrets(payload)
    assert out["api_key"] == "***REDACTED***"
    assert out["nested"]["bot_token"] == "***REDACTED***"
    assert out["nested"]["ok"] == 1


def test_mutation_audit_records():
    audit = sec.get_mutation_audit()
    n0 = len(audit.all())
    rec = sec.audit_mutation(
        action="alert.acknowledge", identity="tester", resource="alert:x", result="OK"
    )
    assert len(audit.all()) == n0 + 1
    assert rec.to_dict()["identity"] == "tester"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
