# -*- coding: utf-8 -*-
"""Read-only command providers for the Telegram gateway.

These callables answer the gateway's read-only commands (``/status``,
``/positions``, ``/risk``, ``/why``, ``/review``) from live process state.

Design rules:

* **Read-only** — every provider only reads (runtime stats, MT5 read-only data
  access, lesson store). None of them can place, modify, or cancel orders, and
  this module never imports execution code.
* **Fail-safe** — the gateway already wraps provider exceptions; providers also
  degrade to honest payloads instead of fabricating numbers.
* Heavy imports (runtime, MT5 connector, agents) happen lazily inside the
  provider functions, so importing this module is side-effect free.
"""

from __future__ import annotations

from typing import Any, Callable

__all__ = ["build_default_providers"]


def _status_provider() -> dict[str, Any]:
    """Return a compact scheduler/MT5 status summary (read-only)."""
    from ..orchestration.runtime import get_runtime

    stats = get_runtime().scheduler.stats()
    try:
        from ..mt5 import connector

        live = bool(connector.is_live_mode())
    except Exception:  # noqa: BLE001 - status must never raise
        live = False
    return {
        "state": "RUNNING" if stats.get("running") else "STOPPED",
        "scheduler": {
            "queue_size": stats.get("queue_size", 0),
            "events_processed": stats.get("events_processed", 0),
            "trades_blocked": stats.get("trades_blocked", 0),
        },
        "mt5_live_data": live,
    }


def _positions_provider() -> dict[str, Any]:
    """Return open positions as short rows (read-only, live or simulated)."""
    try:
        from ..mt5 import connector
    except Exception:  # noqa: BLE001 - degrade honestly
        return {"positions": [], "count": 0, "mode": "unavailable"}

    try:
        positions = connector.get_positions()
        mode = "live" if connector.is_live_mode() else "simulated"
    except Exception:  # noqa: BLE001 - a dead connector must not break the command
        return {"positions": [], "count": 0, "mode": "unavailable"}

    rows = [
        f"{p.symbol} {p.side} {p.quantity} @ {p.price_open} (PnL {p.profit})" for p in positions
    ]
    return {
        "positions": rows,
        "count": len(rows),
        "mode": mode,
    }


def _risk_provider() -> dict[str, Any]:
    """Return the live risk limits plus a read-only account safety check."""
    from ..orchestration.runtime import get_runtime

    runtime = get_runtime()
    gate = getattr(runtime.pipeline, "risk_gate", None)

    limits: dict[str, Any] = {}
    if gate is not None:
        limits = {
            "max_spread_pips": getattr(gate, "_max_spread_pips", None),
            "min_rr": getattr(gate, "_min_rr", None),
        }
        engine = getattr(gate, "_engine", None)
        thresholds = getattr(engine, "_thresholds", None)
        if isinstance(thresholds, dict):
            for key, value in thresholds.items():
                name = getattr(key, "name", None) or getattr(key, "value", None)
                if name:
                    limits[str(name).lower()] = value

    safety: Any = None
    if gate is not None:
        try:
            from ..mt5 import connector

            account = connector.get_account_info()
            safety = gate.check_account_safety(
                account_equity=float(getattr(account, "equity", 0.0) or 0.0),
                account_balance=float(getattr(account, "balance", 0.0) or 0.0),
                margin_used=float(getattr(account, "margin", 0.0) or 0.0),
                open_positions_value=0.0,
                daily_pnl=0.0,
                current_drawdown=0.0,
            )
        except Exception:  # noqa: BLE001 - limits alone are still useful
            safety = None

    result: dict[str, Any] = {"limits": limits}
    if isinstance(safety, dict):
        result["safe"] = bool(safety.get("safe"))
        result["flags"] = safety.get("flags", [])
    else:
        result["safe"] = None
    return result


def _decision_trace_provider() -> dict[str, Any]:
    """Return a structured summary + evidence of the last decision (no CoT)."""
    from ..orchestration.runtime import get_runtime

    decisions = get_runtime().recent_decisions(limit=1)
    if not decisions:
        return {"summary": "No decisions recorded yet.", "decision": "", "evidence": []}

    record = decisions[0]
    evidence: list[str] = []
    for stage in record.get("trace") or []:
        if not isinstance(stage, dict):
            continue
        label = f"{stage.get('stage', '')}: {stage.get('status', '')}"
        detail = str(stage.get("detail") or "")
        if detail:
            label += f" — {detail}"
        evidence.append(label)

    summary = str(record.get("summary") or "")
    if not summary:
        summary = f"{record.get('event_type', '')} → {record.get('decision', '')}"
    return {
        "summary": summary,
        "decision": str(record.get("decision") or ""),
        "evidence": evidence[:6],
    }


def _review_provider() -> dict[str, Any]:
    """Return the latest recorded lesson summary (read-only)."""
    from agents.analysts.review_agent import get_lesson_store

    lessons = get_lesson_store().get_lessons()
    if not lessons:
        return {"summary": "No lessons recorded yet."}
    last = lessons[-1] if isinstance(lessons[-1], dict) else {}
    outcome = str(last.get("outcome") or "?")
    text = str(last.get("text") or "")
    return {"summary": f"[{outcome}] {text}".strip()}


def build_default_providers() -> dict[str, Callable[[], Any]]:
    """Return the read-only provider map for :class:`TelegramGateway`."""
    return {
        "status_provider": _status_provider,
        "positions_provider": _positions_provider,
        "risk_provider": _risk_provider,
        "decision_trace_provider": _decision_trace_provider,
        "review_provider": _review_provider,
    }
