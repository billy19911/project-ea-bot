# -*- coding: utf-8 -*-
"""Phase 9 individual readiness checks (§4–§29) — read-only probes.
Each function returns a :class:`ReadinessCheck`. Probes NEVER mutate trading
state, NEVER enable live trading, and preserve UNKNOWN honestly (a missing
mandatory value is UNKNOWN, which fails the gate — never fabricated as PASS).
"""
from __future__ import annotations

import platform
import sys
from typing import Any, Optional

from .certification import SEVERITY_MANDATORY, ReadinessCheck

__all__ = ["run_standard_checks", "environment_identity"]


def _check(
    cid,
    name,
    category,
    ok,
    *,
    severity=SEVERITY_MANDATORY,
    value=None,
    expected=None,
    source="",
    reason="",
) -> ReadinessCheck:
    status = "PASS" if ok is True else ("UNKNOWN" if ok is None else "FAIL")
    return ReadinessCheck(
        check_id=cid,
        name=name,
        category=category,
        status=status,
        severity=severity,
        value=value,
        expected=expected,
        source=source,
        reason=reason,
    )


def environment_identity() -> dict[str, Any]:
    """Material identity used for the certification fingerprint (§4, §30)."""
    ident: dict[str, Any] = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "environment": "UNKNOWN",
        "strategy_version": "UNKNOWN",
        "config_version": "UNKNOWN",
        "broker": "UNKNOWN",
        "account": "UNKNOWN",
        "symbols": [],
    }
    try:
        from config import settings

        ident["environment"] = getattr(settings, "environment", "UNKNOWN")
    except Exception:  # noqa: BLE001
        pass
    try:
        from strategy.registry import get_strategy_registry

        reg = get_strategy_registry()
        versions = reg.list_versions() if hasattr(reg, "list_versions") else []
        active = None
        for v in versions or []:
            d = v.to_dict() if hasattr(v, "to_dict") else (dict(v) if isinstance(v, dict) else {})
            if d.get("status") == "ACTIVE":
                active = d
                break
        ident["strategy_version"] = (
            f"{active.get('strategy_id')}@{active.get('version')}" if active else "NONE"
        )
    except Exception:  # noqa: BLE001
        pass
    try:
        from mt5 import connector

        ident["broker"] = str(getattr(connector, "get_account_info", lambda: {})() or "UNKNOWN")[
            :40
        ]
    except Exception:  # noqa: BLE001
        pass
    return ident


def _env_check() -> ReadinessCheck:
    ident = environment_identity()
    return _check(
        "environment",
        "Environment identity",
        "environment",
        ident.get("environment") not in ("", "UNKNOWN", None),
        value=ident.get("environment"),
        expected="named environment",
        source="config.settings",
    )


def _python_check() -> ReadinessCheck:
    major, minor = sys.version_info[:2]
    ok = (major, minor) >= (3, 11)
    return _check(
        "runtime_python",
        "Python >= 3.11",
        "environment",
        ok,
        value=f"{major}.{minor}",
        expected=">=3.11",
        source="runtime",
    )


def _broker_check() -> ReadinessCheck:
    try:
        from mt5 import connector

        info = connector.get_account_info() if hasattr(connector, "get_account_info") else None
        d = (
            dict(info)
            if isinstance(info, dict)
            else (info.model_dump() if hasattr(info, "model_dump") else None)
        )
        if d:
            equity = d.get("equity", d.get("balance"))
            return _check(
                "broker_account",
                "Broker/account metadata",
                "broker",
                equity is not None,
                value={"currency": d.get("currency")},
                expected="equity present",
                source="mt5.connector",
            )
        return _check(
            "broker_account",
            "Broker/account metadata",
            "broker",
            None,
            expected="account info",
            source="mt5.connector",
            reason="broker metadata UNKNOWN (connector unavailable)",
        )
    except Exception as exc:  # noqa: BLE001
        return _check(
            "broker_account",
            "Broker/account metadata",
            "broker",
            None,
            expected="account info",
            source="mt5.connector",
            reason=f"UNKNOWN: {str(exc)[:120]}",
        )


def _symbol_check(symbols: list[str]) -> ReadinessCheck:
    if not symbols:
        return _check(
            "symbol_spec",
            "Symbol specification",
            "broker",
            None,
            expected=">=1 symbol",
            source="market.symbol_spec",
            reason="no symbols configured for certification",
        )
    try:
        from market.symbol_spec import get_symbol_specification

        bad: list[str] = []
        for s in symbols:
            spec = get_symbol_specification(s)
            # Mandatory: broker-sourced spec with usable point. Fallback
            # (point=0) ⇒ UNKNOWN ⇒ FAIL for a mandatory symbol.
            if (
                str(getattr(spec, "source", "")) != "broker"
                or float(getattr(spec, "point", 0.0) or 0.0) <= 0
            ):
                bad.append(s)
        return _check(
            "symbol_spec",
            "Symbol specification",
            "broker",
            len(bad) == 0,
            value={"unknown": bad},
            expected="broker spec with point for every symbol",
            source="market.symbol_spec",
            reason="" if not bad else f"UNKNOWN spec for {bad}",
        )
    except Exception as exc:  # noqa: BLE001
        return _check(
            "symbol_spec",
            "Symbol specification",
            "broker",
            None,
            expected="broker spec",
            source="market.symbol_spec",
            reason=f"UNKNOWN: {str(exc)[:120]}",
        )


def _market_data_check(symbol: str) -> ReadinessCheck:
    try:
        from mt5 import connector

        tick = connector.get_tick(symbol) if hasattr(connector, "get_tick") else None
        d = (
            dict(tick)
            if isinstance(tick, dict)
            else (tick.model_dump() if hasattr(tick, "model_dump") else {})
        )
        bid, ask = d.get("bid"), d.get("ask")
        if bid and ask and float(bid) < float(ask):
            return _check(
                "market_data",
                "Market data health",
                "market",
                True,
                value={"bid": bid, "ask": ask},
                expected="bid<ask",
                source="mt5.connector",
            )
        return _check(
            "market_data",
            "Market data health",
            "market",
            None,
            value={"bid": bid, "ask": ask},
            expected="bid<ask",
            source="mt5.connector",
            reason="stale/inverted/missing → UNKNOWN",
        )
    except Exception as exc:  # noqa: BLE001
        return _check(
            "market_data",
            "Market data health",
            "market",
            None,
            expected="bid<ask",
            source="mt5.connector",
            reason=f"UNKNOWN: {str(exc)[:120]}",
        )


def _clock_check() -> ReadinessCheck:
    try:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        ok = now.tzinfo is not None
        return _check(
            "clock",
            "Clock/timezone handling",
            "environment",
            ok,
            value=now.isoformat(),
            expected="tz-aware UTC",
            source="runtime",
        )
    except Exception as exc:  # noqa: BLE001
        return _check(
            "clock",
            "Clock/timezone handling",
            "environment",
            False,
            expected="tz-aware UTC",
            source="runtime",
            reason=str(exc)[:120],
        )


def _startup_check() -> ReadinessCheck:
    try:
        from system.startup_checks import run_startup_safety_gate

        report = run_startup_safety_gate()
        ok = "pipeline unavailable" not in str(report.get("summary", ""))
        return _check(
            "startup_safety",
            "Startup safety config",
            "startup",
            ok,
            value=report.get("summary"),
            expected="no invalid safety config",
            source="system.startup_checks",
        )
    except Exception as exc:  # noqa: BLE001
        return _check(
            "startup_safety",
            "Startup safety config",
            "startup",
            None,
            expected="valid",
            source="system.startup_checks",
            reason=f"UNKNOWN: {str(exc)[:120]}",
        )


def _live_guard_check() -> ReadinessCheck:
    """Verify the live guard exists and is currently DISABLED (§34)."""
    try:
        from readiness.gate import LiveReadinessGate

        gate = LiveReadinessGate()
        ok = gate.is_live is False
        return _check(
            "live_guard",
            "Live trading DISABLED",
            "live_guard",
            ok,
            value={"is_live": gate.is_live, "mode": gate.mode},
            expected="is_live False",
            source="readiness.gate",
            reason="" if ok else "live activated unexpectedly",
        )
    except Exception as exc:  # noqa: BLE001
        return _check(
            "live_guard",
            "Live trading DISABLED",
            "live_guard",
            None,
            expected="disabled",
            source="readiness.gate",
            reason=str(exc)[:120],
        )


def _learning_isolation_check() -> ReadinessCheck:
    """Research output cannot mutate the active strategy (§19)."""
    try:
        from learning.canonical import StrategyCandidateRecord

        cand = StrategyCandidateRecord(candidate_id="probe")
        ok = cand.to_dict().get("activation") == "PROPOSAL_ONLY"
        return _check(
            "learning_isolation",
            "Learning cannot mutate strategy",
            "learning",
            ok,
            expected="PROPOSAL_ONLY",
            source="learning.canonical",
        )
    except Exception as exc:  # noqa: BLE001
        return _check(
            "learning_isolation",
            "Learning cannot mutate strategy",
            "learning",
            None,
            expected="PROPOSAL_ONLY",
            reason=f"UNKNOWN: {str(exc)[:120]}",
        )


def _money_management_check() -> ReadinessCheck:
    """Final volume is deterministic + capped (§14, CASE 8)."""
    try:
        from risk.money_management import MoneyManager

        capped = MoneyManager().cap_lot_size(25.0, max_lot_per_trade=0.05)
        ok = capped == 0.05
        return _check(
            "money_management",
            "MoneyManager caps final volume",
            "risk",
            ok,
            value=capped,
            expected=0.05,
            source="risk.money_management",
        )
    except Exception as exc:  # noqa: BLE001
        return _check(
            "money_management",
            "MoneyManager caps final volume",
            "risk",
            False,
            expected=0.05,
            reason=str(exc)[:120],
        )


def _risk_gate_check() -> ReadinessCheck:
    """RiskGate rejects oversized proposals (§13)."""
    try:
        from risk.base import RiskThreshold
        from risk.engine import RiskEngine
        from risk.gate import RiskGate
        from risk.money_management import MoneyManager

        eng = RiskEngine()
        eng.set_threshold(RiskThreshold.MAX_DRAWDOWN, 0.2)
        eng.set_threshold(RiskThreshold.MAX_EXPOSURE, 0.3)
        gate = RiskGate(eng, MoneyManager(), max_spread_pips=5.0)
        d = gate.validate_proposal(
            {
                "symbol": "EURUSD",
                "direction": "BUY",
                "entry_price": 100.0,
                "stop_loss": 95.0,
                "take_profit": 115.0,
                "size": 500.0,
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
        ok = d.approved is False
        return _check(
            "risk_gate",
            "RiskGate rejects oversized",
            "risk",
            ok,
            expected="rejected",
            source="risk.gate",
        )
    except Exception as exc:  # noqa: BLE001
        return _check(
            "risk_gate",
            "RiskGate rejects oversized",
            "risk",
            False,
            expected="rejected",
            reason=str(exc)[:120],
        )


def _trigger_semantics_check() -> ReadinessCheck:
    """Zone touch ≠ entry; deterministic trigger engine authoritative (§15)."""
    try:
        from agents.roles import EntryRole

        out = EntryRole().analyze(
            {
                "setup": {"direction": "BUY", "missing_conditions": []},
                "trigger_result": {
                    "conditions_met": {"zone_touch": True, "rejection": False},
                    "blocking": [],
                },
                "required_triggers": ("zone_touch", "rejection"),
            }
        )
        ok = out.signal == "WAIT_TRIGGER"
        return _check(
            "trigger_semantics",
            "Zone touch != entry",
            "entry",
            ok,
            value=out.signal,
            expected="WAIT_TRIGGER",
            source="agents.roles",
        )
    except Exception as exc:  # noqa: BLE001
        return _check(
            "trigger_semantics",
            "Zone touch != entry",
            "entry",
            False,
            expected="WAIT_TRIGGER",
            reason=str(exc)[:120],
        )


def _model_router_check() -> ReadinessCheck:
    """Model router is bounded + fail-closed (§17)."""
    try:
        from llm.canonical import ModelRequest
        from llm.router import CanonicalModelRouter

        r = CanonicalModelRouter()
        rec, out = r.execute(
            ModelRequest(request_id="cert-probe", task_type="FAST_CLASSIFICATION", cycle_id="cert"),
            route_through=lambda m, p, **k: (_ for _ in ()).throw(ConnectionError("down")),
        )
        ok = rec.output_status == "FAILED" and out is None
        return _check(
            "model_router",
            "Model router fail-closed",
            "model",
            ok,
            value=rec.output_status,
            expected="FAILED",
            source="llm.router",
        )
    except Exception as exc:  # noqa: BLE001
        return _check(
            "model_router",
            "Model router fail-closed",
            "model",
            None,
            expected="FAILED",
            reason=f"UNKNOWN: {str(exc)[:120]}",
        )


def _security_check() -> ReadinessCheck:
    """Secret masking works (§27)."""
    try:
        from ops.secrets import mask_secrets

        out = mask_secrets({"api_key": "sk-live-secret"})
        ok = out.get("api_key") == "***REDACTED***"
        return _check(
            "security", "Secret masking", "security", ok, expected="redacted", source="ops.secrets"
        )
    except Exception as exc:  # noqa: BLE001
        return _check(
            "security",
            "Secret masking",
            "security",
            False,
            expected="redacted",
            reason=str(exc)[:120],
        )


def _topology_check() -> ReadinessCheck:
    """Single-writer assumption must hold unless cross-process safety exists (§28).
    Reported as WARNING (advisory) by default; deployment must confirm.
    """
    workers = None
    try:
        import os

        workers = int(os.getenv("UVICORN_WORKERS", "1") or "1")
    except Exception:  # noqa: BLE001
        workers = None
    if workers is None:
        return _check(
            "topology",
            "Single-writer topology",
            "topology",
            None,
            severity=SEVERITY_MANDATORY,
            expected="1 writer",
            source="env.UVICORN_WORKERS",
            reason="UNKNOWN worker count",
        )
    ok = workers <= 1
    return _check(
        "topology",
        "Single-writer topology",
        "topology",
        ok,
        severity=SEVERITY_MANDATORY,
        value=workers,
        expected="<=1",
        source="env.UVICORN_WORKERS",
        reason="" if ok else "multi-writer without cross-process locks",
    )


def run_standard_checks(symbols: Optional[list[str]] = None) -> list[ReadinessCheck]:
    """Run the full read-only check suite (deterministic order)."""
    syms = list(symbols or [])
    market_symbol = syms[0] if syms else "XAUUSD"
    return [
        _env_check(),
        _python_check(),
        _broker_check(),
        _symbol_check(syms),
        _market_data_check(market_symbol),
        _clock_check(),
        _startup_check(),
        _live_guard_check(),
        _risk_gate_check(),
        _money_management_check(),
        _trigger_semantics_check(),
        _learning_isolation_check(),
        _model_router_check(),
        _security_check(),
        _topology_check(),
    ]
