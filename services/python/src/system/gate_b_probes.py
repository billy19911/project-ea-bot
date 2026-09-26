# -*- coding: utf-8 -*-
"""Gate B runtime probes for the Production Certification Gate (PRD_V2 §50).

The certification collector (``live_readiness.certification_evidence``) accepts a
``gate_b_probes`` mapping of callables. Each probe observes **real in-process
runtime state** and returns ``(value, reason, evidence_source)`` (or a rich
``{value, reason, evidence_source}`` dict) so the gate never fabricates a pass:

* ``True``  — a real artefact/state was seen healthy,
* ``False`` — a real artefact/state was seen unhealthy,
* ``None``  — state is not observable from this process (unknown, NOT_RUN).

A probe that raises is converted by the collector into ``unknown`` with the
exception recorded — the endpoint never crashes. This module therefore reads
state defensively and never mutates configuration, arms a terminal, or trades.

The seven checks mirror :data:`live_readiness.certification_gate.GATE_B_CHECKS`.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

__all__ = ["build_gate_b_probes", "GATE_B_PROBE_CHECKS"]

# Kept in sync with certification_gate.GATE_B_CHECKS (imported lazily to avoid a
# hard import cycle at module load; asserted by tests).
GATE_B_PROBE_CHECKS: tuple[str, ...] = (
    "risk_gate",
    "kill_switch",
    "circuit_breaker",
    "duplicate_prevention",
    "broker_spec",
    "reconciliation",
    "recovery",
)

# Symbol used for the broker symbol-spec probe. A resolved spec is
# broker-independent; this is the app's default trading instrument.
_BROKER_SPEC_SYMBOL = "XAUUSD"


def _ev(value: bool | None, reason: str, source: str) -> tuple[bool | None, str, str]:
    return (value, reason, source)


def _runtime() -> Any:
    """Return the process-wide orchestration runtime (or raise if unavailable)."""
    from ..orchestration.runtime import get_runtime

    return get_runtime()


def _probe_risk_gate() -> tuple[bool | None, str, str]:
    """RiskGate installed in the runtime pipeline + executor require_approval.

    Boundary B-3 requires the deterministic Risk Gate to be an
    executor-enforced boundary: the runtime pipeline must carry a ``risk_gate``
    and the execution engine must refuse orders without a gate-issued approval
    token (``require_approval=True``).
    """
    try:
        pipeline = _runtime().pipeline
    except Exception as exc:  # noqa: BLE001 - unobservable => unknown
        return _ev(None, f"pipeline runtime tidak tersedia: {exc}", "runtime")

    risk_gate = getattr(pipeline, "risk_gate", None)
    if risk_gate is None:
        return _ev(
            False, "RiskGate tidak terpasang di pipeline runtime", "runtime.pipeline"
        )
    engine = getattr(pipeline, "execution_engine", None)
    if engine is None:
        return _ev(
            False,
            "ExecutionEngine tidak terpasang di pipeline runtime",
            "runtime.pipeline",
        )
    if not bool(getattr(engine, "require_approval", False)):
        return _ev(
            False,
            "ExecutionEngine.require_approval=False — risk gate bukan boundary executor",
            "runtime.pipeline.execution_engine",
        )
    return _ev(
        True,
        f"RiskGate={type(risk_gate).__name__} terpasang + require_approval=True",
        "runtime.pipeline",
    )


def _probe_kill_switch() -> tuple[bool | None, str, str]:
    """Kill switch state loaded from the durable store; healthy when not blocked."""
    from ..risk.kill_switch import load_kill_switch

    ks = load_kill_switch()
    state = ks.state.value
    blocked = ks.is_blocked()
    value = not blocked
    reason = f"kill switch state={state} locked={ks.locked} is_blocked={blocked}"
    if not value:
        reason = f"kill switch BLOCKED — state={state} locked={ks.locked}"
    return _ev(value, reason, "risk.kill_switch")


def _probe_circuit_breaker() -> tuple[bool | None, str, str]:
    """Multi-level circuit breaker at its NORMAL level (no degraded entry policy)."""
    from .v2_endpoints import get_circuit_breaker

    data = get_circuit_breaker().to_dict()
    level = data.get("level", data.get("state"))
    value = level == "normal"
    reason = f"circuit breaker level={level} latched={data.get('latched')}"
    if not value:
        reason = (
            f"circuit breaker NOT normal — level={level} reason={data.get('reason')}"
        )
    return _ev(value, reason, "risk.multi_level_breaker")


def _probe_duplicate_prevention() -> tuple[bool | None, str, str]:
    """Durable intent store attached + engine idempotency dedup active."""
    from ..execution import intents

    store = intents.get_store()
    if store is None:
        return _ev(False, "durable intent store tidak terpasang", "execution.intents")
    try:
        engine_ok = True
        pipeline = _runtime().pipeline
        engine = getattr(pipeline, "execution_engine", None)
        if engine is None or not hasattr(engine, "_is_duplicate"):
            engine_ok = False
    except Exception as exc:  # noqa: BLE001 - engine check best-effort
        engine_ok = False
        engine_err = str(exc)
    else:
        engine_err = ""
    if not engine_ok:
        detail = f" ({engine_err})" if engine_err else ""
        return _ev(
            False,
            f"duplikasi idempotency_key tidak aktif di engine{detail}",
            "execution.intents",
        )
    return _ev(
        True,
        f"durable intent store={type(store).__name__} + dedup idempotency_key aktif",
        "execution.intents",
    )


def _probe_broker_spec() -> tuple[bool | None, str, str]:
    """Connector ``get_symbol_info`` returns a valid spec (digits>0, point>0).

    An unavailable connector (or missing symbol) is ``unknown`` — never a
    fabricated pass.
    """
    import importlib

    connector = None
    for mod_name in ("src.mt5.connector", "mt5.connector"):
        try:
            connector = importlib.import_module(mod_name)
            break
        except ImportError:
            continue
    if connector is None:
        return _ev(None, "connector MT5 tidak tersedia", "mt5.connector")
    try:
        get_symbol_info: Callable[[str], Any] = getattr(connector, "get_symbol_info")
    except AttributeError:
        return _ev(None, "connector tidak menyediakan get_symbol_info", "mt5.connector")
    try:
        info = get_symbol_info(_BROKER_SPEC_SYMBOL)
    except Exception as exc:  # noqa: BLE001 - lookup failure => unknown
        return _ev(None, f"get_symbol_info gagal: {exc}", "mt5.connector")
    if info is None:
        return _ev(
            None,
            f"spec simbol {_BROKER_SPEC_SYMBOL} tidak tersedia (connector tidak live?)",
            "mt5.connector",
        )
    digits = int(getattr(info, "digits", 0) or 0)
    point = float(getattr(info, "point", 0.0) or 0.0)
    value = digits > 0 and point > 0
    reason = f"{_BROKER_SPEC_SYMBOL} digits={digits} point={point}"
    if not value:
        reason = (
            f"spec {_BROKER_SPEC_SYMBOL} tidak valid — digits={digits} point={point}"
        )
    return _ev(value, reason, "mt5.connector")


def _probe_reconciliation() -> tuple[bool | None, str, str]:
    """Latest reconciliation report exists and has no critical mismatch."""
    try:
        report = _runtime().last_reconciliation()
    except Exception as exc:  # noqa: BLE001 - unobservable => unknown
        return _ev(None, f"runtime reconciliation tidak tersedia: {exc}", "runtime")
    if report is None:
        return _ev(False, "belum ada laporan reconciliation", "runtime.reconciliation")
    critical = bool(report.has_critical())
    mismatches = len(getattr(report, "mismatches", []) or [])
    value = not critical
    reason = f"reconciliation mismatches={mismatches} critical={critical}"
    if not value:
        reason = f"reconciliation kritikal — mismatches={mismatches}"
    return _ev(value, reason, "runtime.reconciliation")


def _probe_recovery() -> tuple[bool | None, str, str]:
    """Durable stores attached (kill switch, order ledger, reconciliation) + loaded."""
    checks: dict[str, bool] = {}
    sources: list[str] = []

    # Kill switch durable store.
    try:
        from ..risk import kill_switch as ks_mod

        checks["kill_switch_store"] = ks_mod._store is not None
    except Exception:  # noqa: BLE001
        checks["kill_switch_store"] = False

    # Order ledger store (execution.state_machine).
    try:
        from ..execution import state_machine

        checks["order_ledger_store"] = state_machine.get_store() is not None
    except Exception:  # noqa: BLE001
        checks["order_ledger_store"] = False

    # Reconciliation snapshot store (on the runtime position monitor).
    try:
        monitor = getattr(_runtime(), "position_monitor", None)
        recon_store = (
            getattr(monitor, "reconciliation_store", None) if monitor else None
        )
        checks["reconciliation_store"] = recon_store is not None
    except Exception:  # noqa: BLE001
        checks["reconciliation_store"] = False

    missing = [name for name, ok in checks.items() if not ok]
    sources.append("persistence")
    if missing:
        return _ev(
            False,
            "durable store tidak terpasang: " + ", ".join(missing),
            "persistence",
        )

    # State must actually load from disk (not merely be wired).
    try:
        from ..risk.kill_switch import load_kill_switch

        load_kill_switch()
    except Exception as exc:  # noqa: BLE001 - load failure => not recovered
        return _ev(False, f"state durable gagal dimuat: {exc}", "persistence")
    return _ev(
        True,
        "durable stores terpasang + state dimuat dari disk",
        "persistence",
    )


def build_gate_b_probes() -> dict[str, Callable[[], Any]]:
    """Return the seven Gate B probes bound to the live runtime.

    Each callable returns ``(value, reason, evidence_source)`` and never raises
    for an *expected* missing subsystem (it returns ``unknown`` instead). The
    collector additionally guards any unexpected exception.
    """
    return {
        "risk_gate": _probe_risk_gate,
        "kill_switch": _probe_kill_switch,
        "circuit_breaker": _probe_circuit_breaker,
        "duplicate_prevention": _probe_duplicate_prevention,
        "broker_spec": _probe_broker_spec,
        "reconciliation": _probe_reconciliation,
        "recovery": _probe_recovery,
    }
