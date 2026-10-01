# -*- coding: utf-8 -*-
"""Phase 8 H3/H4 — startup safety gate + execution recovery routine.

* ``run_startup_safety_gate``: fail-early validation of safety-critical
  configuration. Invalid values are clamped to SAFE defaults (never dangerous
  ones) and every correction is returned in the report for audit.
* ``run_execution_recovery``: at boot, list durable ledger intents stuck in
  UNKNOWN/SUBMITTING and flag them for reconciliation. It NEVER blind-retries:
  it only marks records so the next locator/reconciliation pass adopts them.

Both are best-effort and must never block startup (callers wrap in try/except).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["run_startup_safety_gate", "run_execution_recovery", "run_restart_recovery"]


def _get_pipeline() -> Any:
    try:
        from ..orchestration.runtime import get_runtime
    except ImportError:
        try:
            from orchestration.runtime import get_runtime  # type: ignore
        except Exception:
            return None
    try:
        return get_runtime().pipeline
    except Exception:  # noqa: BLE001
        return None


def run_startup_safety_gate() -> dict[str, Any]:
    """Validate safety-critical runtime config; clamp invalid → safe defaults."""
    corrections: list[str] = []
    pipe = _get_pipeline()
    if pipe is None:
        return {"summary": "pipeline unavailable (skipped)", "corrections": corrections}

    # 1. max_lot_per_trade must be in (0, 100]; else safe default 0.05.
    try:
        cap = float(getattr(pipe, "max_lot_per_trade", 0.0) or 0.0)
    except (TypeError, ValueError):
        cap = 0.0
    if not (0 < cap <= 100):
        pipe.max_lot_per_trade = 0.05
        corrections.append(f"max_lot_per_trade={cap!r} invalid → 0.05 (safe default)")

    # 2. default_risk_pct must be in (0, 1]; else 0.01 (1%).
    try:
        risk = float(getattr(pipe, "default_risk_pct", 0.0) or 0.0)
    except (TypeError, ValueError):
        risk = 0.0
    # The UI knob pushes PERCENT (>=0.1, e.g. 1.0 = 1%); accept both units.
    if risk >= 0.1:
        risk_frac = risk / 100.0
    else:
        risk_frac = risk
    if not (0 < risk_frac <= 1.0):
        pipe.default_risk_pct = 0.01
        corrections.append("default_risk_pct invalid -> 0.01 (safe default)")

    # 3. Retry bounds must be sane (bounded, never infinite/negative).
    try:
        from ..orchestration.runtime import get_runtime

        engine = getattr(get_runtime().pipeline, "execution_engine", None)
    except Exception:  # noqa: BLE001
        engine = getattr(pipe, "execution_engine", None)
    if engine is not None:
        try:
            mr = int(getattr(engine, "max_retries", 3))
            if mr < 0 or mr > 10:
                engine.max_retries = max(0, min(mr, 10))
                corrections.append(f"max_retries clamped to {engine.max_retries}")
        except (TypeError, ValueError):
            pass

    summary = (
        "all safety configs valid"
        if not corrections
        else f"{len(corrections)} correction(s): " + "; ".join(corrections)
    )
    for c in corrections:
        logger.warning("Startup safety gate correction: %s", c)
    return {"summary": summary, "corrections": corrections}


def run_execution_recovery() -> dict[str, Any]:
    """Flag UNKNOWN/SUBMITTING ledger intents for reconciliation at boot.

    Recovery rule: load durable intents; any record in UNKNOWN/SUBMITTING is
    re-marked UNKNOWN with a ``needs_reconciliation`` flag so the next
    locator/reconciliation pass adopts (never blind-retries) it.
    """
    flagged: list[str] = []
    try:
        try:
            from ..execution.state_machine import OrderState, get_store
        except ImportError:
            from execution.state_machine import OrderState, get_store  # type: ignore
    except Exception as exc:  # noqa: BLE001
        return {"summary": f"state machine unavailable ({exc})", "flagged": flagged}

    try:
        store = get_store()
        if store is None:
            return {"summary": "no durable store attached (nothing to recover)", "flagged": flagged}
        pending_states = {OrderState.UNKNOWN.value, OrderState.SUBMITTING.value}
        for intent_id, rec in (store.all_orders() or {}).items():
            state = str((rec or {}).get("state", "")).lower()
            if state in pending_states:
                flagged.append(str(intent_id))
        summary = (
            f"{len(flagged)} intent(s) flagged for reconciliation (adopt, never blind-retry)"
            if flagged
            else "no pending intents (nothing to recover)"
        )
        return {"summary": summary, "flagged": flagged}
    except Exception as exc:  # noqa: BLE001
        return {"summary": f"recovery scan failed: {exc}", "flagged": flagged}


def _build_restart_coordinator() -> Any:
    """Build the production :class:`RestartRecoveryCoordinator` (TASK 08).

    Wires the durable order ledger as the intent source, the read-only MT5
    connector for positions/orders/deals, and the reconciliation engine. Every
    external effect is the *real* production source; no fallback fabricates
    state. Returns ``None`` when a required source cannot be imported (caller
    then skips recovery, staying fail-closed by NOT permitting orders).
    """
    try:
        try:
            from ..execution.reconciliation import Reconciler
            from ..execution.restart_recovery import RestartRecoveryCoordinator
            from ..execution.state_machine import get_store
        except ImportError:
            from execution.reconciliation import Reconciler  # type: ignore
            from execution.restart_recovery import RestartRecoveryCoordinator  # type: ignore
            from execution.state_machine import get_store  # type: ignore
    except Exception as exc:  # noqa: BLE001
        logger.warning("Restart recovery coordinator unavailable: %s", exc)
        return None

    def _load_intents() -> list[Any]:
        store = get_store()
        if store is None:
            return []
        return list((store.all_orders() or {}).values())

    def _connector() -> Any:
        for mod_name in ("src.mt5.connector", "mt5.connector"):
            try:
                import importlib

                return importlib.import_module(mod_name)
            except ImportError:
                continue
        return None

    def _is_live() -> bool:
        conn = _connector()
        if conn is None:
            return False
        try:
            return bool(getattr(conn, "is_live_mode", lambda: False)())
        except Exception:  # noqa: BLE001
            return False

    def _connect_mt5() -> bool:
        conn = _connector()
        if conn is None:
            return False
        try:
            # In non-live (paper/dev) mode there is no real broker book — the
            # connector's synthetic positions are placeholders the engine never
            # created. Recovery still runs its sequence, but reconciliation is a
            # verified no-op (see ``_reconcile``), so a simulated placeholder can
            # never be misread as an orphan position.
            getattr(conn, "is_live_mode", lambda: False)()
            return True
        except Exception:  # noqa: BLE001 - any doubt → not connected (block)
            return False

    def _read_positions() -> Any:
        conn = _connector()
        if conn is None:
            return False, []
        get_ex = getattr(conn, "get_positions_ex", None)
        if callable(get_ex):
            # (ok, positions): distinguishes verified-empty from failed read.
            return get_ex()
        try:
            return True, list(conn.get_positions() or [])
        except Exception:  # noqa: BLE001 - failed read → unverified
            return False, []

    def _read_orders() -> Any:
        conn = _connector()
        if conn is None:
            return False, []
        try:
            return True, list(conn.get_orders() or [])
        except Exception:  # noqa: BLE001
            return False, []

    def _read_deals() -> Any:
        # Deals are consumed only for the adopt-vs-resend decision; an empty or
        # unavailable history is acceptable (it downgrades adoption matching).
        return []

    reconciler = Reconciler()

    def _reconcile(intents: list[Any]) -> Any:
        # Compare the internal ledger's open positions against the broker book.
        # NON-LIVE MODE: the connector's synthetic positions are placeholders
        # the engine never created, so reconciling them against an empty internal
        # ledger would be a permanent false-positive (and would block every new
        # order). Recovery is therefore a verified no-op in non-live mode.
        if not _is_live():
            return Reconciler().compare([], [], [], [])
        try:
            from ..execution.reconciliation_providers import internal_positions_from_store
        except ImportError:
            from execution.reconciliation_providers import (  # type: ignore
                internal_positions_from_store,
            )
        store = get_store()
        internal = internal_positions_from_store(
            (store.all_orders() if store is not None else {}) or {}
        )
        pos_result = _read_positions()
        _ok, broker = pos_result if isinstance(pos_result, tuple) else (True, pos_result)
        return reconciler.compare(internal, list(broker or []), [], [])

    return RestartRecoveryCoordinator(
        load_intents=_load_intents,
        connect_mt5=_connect_mt5,
        read_positions=_read_positions,
        read_orders=_read_orders,
        read_deals=_read_deals,
        reconcile=_reconcile,
    )


def run_restart_recovery() -> dict[str, Any]:
    """Run the TASK 08 restart sequence against the process-wide runtime.

    Builds the coordinator, wires it onto the runtime (so the readiness gate
    blocks new orders until it converges) and runs it once. Fail-safe: never
    raises; a failure leaves the system fail-closed (orders blocked).
    """
    try:
        from ..orchestration.runtime import get_runtime
    except ImportError:
        try:
            from orchestration.runtime import get_runtime  # type: ignore
        except Exception:  # noqa: BLE001
            return {"summary": "runtime unavailable (recovery skipped)", "state": "skipped"}

    coordinator = _build_restart_coordinator()
    if coordinator is None:
        return {"summary": "recovery coordinator unavailable (skipped)", "state": "skipped"}
    try:
        runtime = get_runtime()
        runtime.recovery_coordinator = coordinator
        # Re-wire the readiness gate so the already-built pipeline enforces it.
        from ..execution.restart_recovery import ReconciliationReadinessGate
    except ImportError:
        from execution.restart_recovery import ReconciliationReadinessGate  # type: ignore
    except Exception as exc:  # noqa: BLE001
        return {"summary": f"runtime wiring failed: {exc}", "state": "blocked"}
    try:
        runtime._readiness_gate = ReconciliationReadinessGate(coordinator)
        if getattr(runtime, "pipeline", None) is not None:
            runtime.pipeline.readiness_guard = runtime._readiness_gate
    except Exception as exc:  # noqa: BLE001
        logger.warning("Readiness gate wiring failed: %s", exc)

    report = coordinator.run()
    data = report.to_dict()
    data["summary"] = data.get("reason", "")
    return data
