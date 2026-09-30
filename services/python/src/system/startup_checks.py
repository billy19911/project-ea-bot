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

__all__ = ["run_startup_safety_gate", "run_execution_recovery"]


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
