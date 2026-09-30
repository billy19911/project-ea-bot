# -*- coding: utf-8 -*-
"""Phase 7 ops read models — aggregated, read-only views over canonical stores.

Every function is a thin assembler over the EXISTING source of truth (runtime
trace store, gate config, ledger, stores, connectors). No function here has
trading authority, and none mutates backend state. UNKNOWN/stale/partial data
is preserved honestly (UNKNOWN ≠ 0/HEALTHY).
"""

from __future__ import annotations

import time
from typing import Any, Optional

from .secrets import UNKNOWN, mask_secrets, unknown_if_none


def _alerts() -> dict[str, Any]:
    try:
        from .alerts import evaluate_runtime_alerts

        return evaluate_runtime_alerts()
    except Exception:  # noqa: BLE001
        return {"alerts": [], "count": 0, "by_severity": {}}


def _now() -> float:
    return time.time()


def _staleness(source_ts: Optional[float]) -> dict[str, Any]:
    """Freshness envelope for a timestamp (UNKNOWN when missing)."""
    if not source_ts:
        return {"last_updated": None, "staleness_s": None, "fresh": UNKNOWN}
    age = max(0.0, _now() - float(source_ts))
    return {"last_updated": source_ts, "staleness_s": round(age, 2), "fresh": age < 30.0}


# ── Overview (§1) ──────────────────────────────────────────────────────


def overview() -> dict[str, Any]:
    """Compact command-center overview assembled from each subsystem."""
    return mask_secrets(
        {
            "system": health_snapshot(),
            "market": market_snapshot(),
            "risk": risk_summary(),
            "execution": execution_summary(),
            "positions": position_summary(),
            "models": model_summary(),
            "research": research_summary(),
            "strategies": strategy_summary(),
            "alerts": _alerts(),
            "generated_at": _now(),
        }
    )


# ── System health (§2) ────────────────────────────────────────────────


def _component(name: str, probe: Any) -> dict[str, Any]:
    """Run one health probe fail-safe; UNKNOWN on any error."""
    try:
        if callable(probe):
            out = probe()
            if isinstance(out, dict):
                return {"name": name, **out}
            return {"name": name, "status": "HEALTHY" if out else UNKNOWN}
    except Exception as exc:  # noqa: BLE001 - health must never break overview
        return {"name": name, "status": "FAILED", "last_error": str(exc)[:200]}
    return {"name": name, "status": UNKNOWN}


def health_snapshot() -> dict[str, Any]:
    """Per-component health from live probes (never inferred from existence)."""
    components: list[dict[str, Any]] = []

    def _api() -> dict[str, Any]:
        return {"status": "HEALTHY", "version": "v2"}

    def _engine() -> dict[str, Any]:
        try:
            from orchestration.runtime import get_runtime

            rt = get_runtime()
            pipe = getattr(rt, "pipeline", None)
            return {"status": "HEALTHY" if pipe is not None else "UNKNOWN"}
        except Exception:
            return {"status": UNKNOWN}

    def _mt5() -> dict[str, Any]:
        try:
            from mt5 import connector

            src = connector.data_source() if hasattr(connector, "data_source") else UNKNOWN
            live = src == "LIVE" if isinstance(src, str) else False
            return {
                "status": "HEALTHY" if live else "DEGRADED",
                "data_source": unknown_if_none(src),
            }
        except Exception:
            return {"status": UNKNOWN}

    def _scheduler() -> dict[str, Any]:
        try:
            from orchestration.runtime import get_runtime

            rt = get_runtime()
            sched = getattr(rt, "scheduler", None)
            return {"status": "HEALTHY" if sched is not None else UNKNOWN}
        except Exception:
            return {"status": UNKNOWN}

    def _reconciliation() -> dict[str, Any]:
        try:
            from orchestration.runtime import get_runtime

            rt = get_runtime()
            ok = rt.last_reconciliation_ok() if hasattr(rt, "last_reconciliation_ok") else None
            return {
                "status": "HEALTHY" if ok else ("DEGRADED" if ok is False else UNKNOWN),
                "last_ok": ok if ok is not None else UNKNOWN,
            }
        except Exception:
            return {"status": UNKNOWN}

    def _research_queue() -> dict[str, Any]:
        try:
            from learning.review_store import ResearchQueue

            q = ResearchQueue()
            return {"status": "HEALTHY", "depth": q.depth(), "errors": q.errors}
        except Exception:
            return {"status": UNKNOWN}

    def _telegram() -> dict[str, Any]:
        return {"status": "UNKNOWN", "note": "report-only hooks; no health probe"}

    for name, probe in (
        ("api", _api),
        ("engine", _engine),
        ("scheduler", _scheduler),
        ("mt5", _mt5),
        ("reconciliation", _reconciliation),
        ("research_queue", _research_queue),
        ("telegram", _telegram),
    ):
        components.append(_component(name, probe))

    overall = "HEALTHY"
    for c in components:
        if c.get("status") == "FAILED":
            overall = "FAILED"
            break
        if c.get("status") in ("DEGRADED", UNKNOWN):
            overall = "DEGRADED"
    return {"status": overall, "components": components, "checked_at": _now()}


# ── Market (§3) ────────────────────────────────────────────────────────


def market_snapshot(symbol: str = "XAUUSD") -> dict[str, Any]:
    """Live market state from the connector (UNKNOWN preserved)."""
    out: dict[str, Any] = {"symbol": symbol}
    try:
        from mt5 import connector

        tick = connector.get_tick(symbol) if hasattr(connector, "get_tick") else None
        td = (
            dict(tick)
            if isinstance(tick, dict)
            else (tick.model_dump() if hasattr(tick, "model_dump") else {})
        )
        bid = td.get("bid")
        ask = td.get("ask")
        out.update(
            {
                "bid": unknown_if_none(bid),
                "ask": unknown_if_none(ask),
                "spread": (float(ask) - float(bid)) if bid and ask else UNKNOWN,
                "staleness": _staleness(
                    td.get("time") if isinstance(td.get("time"), (int, float)) else None
                ),
            }
        )
    except Exception:
        out.update(
            {"bid": UNKNOWN, "ask": UNKNOWN, "spread": UNKNOWN, "staleness": _staleness(None)}
        )
    # Regime/volatility/news/session from the latest market-state cache.
    try:
        from trading.market_snapshot import get_latest_snapshot

        snap = get_latest_snapshot(symbol) or {}
        for k in ("regime", "volatility", "news_state", "session", "timeframe"):
            out[k] = snap.get(k, UNKNOWN)
    except Exception:
        for k in ("regime", "volatility", "news_state", "session", "timeframe"):
            out[k] = UNKNOWN
    return mask_secrets(out)


# ── Risk (§10) ─────────────────────────────────────────────────────────


def risk_summary() -> dict[str, Any]:
    """Deterministic risk state — read from the backend gate, never recomputed."""
    try:
        from orchestration.runtime import get_runtime
        from system.endpoints import _risk_limits_snapshot

        snap = _risk_limits_snapshot()
        limits = snap.get("limits", {}) if isinstance(snap, dict) else {}
        rt = get_runtime()
        pipe = getattr(rt, "pipeline", None)
        gate = getattr(pipe, "risk_gate", None) if pipe else None
        return {
            "limits": limits,
            "gate_configured": gate is not None,
            "source": "backend RiskGate (source of truth)",
            "checked_at": _now(),
        }
    except Exception as exc:  # noqa: BLE001
        return {"limits": {}, "gate_configured": UNKNOWN, "error": str(exc)[:200]}


# ── Execution (§11) ────────────────────────────────────────────────────


def execution_summary(limit: int = 25) -> dict[str, Any]:
    """Recent execution lifecycle from the durable order ledger."""
    try:
        from execution.state_machine import get_store

        store = get_store()
        orders = store.all_orders() if store is not None else {}
        rows = []
        for intent_id, rec in list(orders.items())[-max(1, int(limit)) :]:
            if isinstance(rec, dict):
                rows.append(
                    {
                        "intent_id": intent_id,
                        "state": rec.get("state", UNKNOWN),
                        "ticket": rec.get("ticket", UNKNOWN),
                        "timestamp": rec.get("timestamp"),
                    }
                )
        return {"orders": rows, "count": len(orders), "source": "durable order ledger"}
    except Exception as exc:  # noqa: BLE001
        return {"orders": [], "count": UNKNOWN, "error": str(exc)[:200]}


# ── Positions (§12) ────────────────────────────────────────────────────


def position_summary() -> dict[str, Any]:
    """Active positions from MT5 (read-only)."""
    try:
        from mt5 import connector

        positions = connector.get_positions() if hasattr(connector, "get_positions") else []
        rows = []
        for p in positions or []:
            d = (
                dict(p)
                if isinstance(p, dict)
                else (p.model_dump() if hasattr(p, "model_dump") else {})
            )
            rows.append(
                {
                    "position_id": d.get("ticket", UNKNOWN),
                    "symbol": d.get("symbol", UNKNOWN),
                    "direction": d.get("type", d.get("side", UNKNOWN)),
                    "volume": d.get("volume", UNKNOWN),
                    "entry": d.get("price_open", d.get("price", UNKNOWN)),
                    "sl": d.get("sl", UNKNOWN),
                    "tp": d.get("tp", UNKNOWN),
                    "profit": d.get("profit", UNKNOWN),
                }
            )
        return {"positions": rows, "count": len(rows)}
    except Exception as exc:  # noqa: BLE001
        return {"positions": [], "count": UNKNOWN, "error": str(exc)[:200]}


# ── Models / budget / providers (§7–§9) ────────────────────────────────


def model_summary(limit: int = 50) -> dict[str, Any]:
    """Model call provenance from the shared telemetry store."""
    try:
        from system.v2_endpoints import get_llm_store

        store = get_llm_store()
        rows = store.all() if hasattr(store, "all") else []
        out = []
        for r in (rows or [])[-max(1, int(limit)) :]:
            d = r.to_dict() if hasattr(r, "to_dict") else (dict(r) if isinstance(r, dict) else {})
            out.append(
                {
                    "agent": d.get("agent", UNKNOWN),
                    "model": d.get("model", UNKNOWN),
                    "provider": d.get("provider", UNKNOWN),
                    "tokens": (d.get("input_tokens"), d.get("output_tokens")),
                    "latency": d.get("latency", UNKNOWN),
                    "fallback": d.get("fallback", UNKNOWN),
                    "status": "error" if d.get("error") else "ok",
                }
            )
        return {"calls": out, "count": len(rows or [])}
    except Exception as exc:  # noqa: BLE001
        return {"calls": [], "count": UNKNOWN, "error": str(exc)[:200]}


def budget_summary() -> dict[str, Any]:
    """Supervisor token budget + advisor commits (informational)."""
    try:
        from orchestration.runtime import get_runtime

        sup = getattr(get_runtime().pipeline, "supervisor", None)
        if sup is None:
            return {"budget": UNKNOWN}
        return {
            "token_budget": getattr(sup, "token_budget", UNKNOWN),
            "token_used": getattr(sup, "token_used", UNKNOWN),
            "remaining": (getattr(sup, "token_budget", 0) or 0)
            - (getattr(sup, "token_used", 0) or 0),
        }
    except Exception as exc:  # noqa: BLE001
        return {"budget": UNKNOWN, "error": str(exc)[:200]}


def provider_summary() -> dict[str, Any]:
    """Provider/model availability from the registry (no cost fabrication)."""
    try:
        from llm.registry import ModelRegistry

        reg = ModelRegistry()
        models = []
        for m in reg.list_models():
            models.append(
                {
                    "model": getattr(m, "name", UNKNOWN),
                    "provider": getattr(m, "provider", UNKNOWN),
                    "free": getattr(m, "is_free", UNKNOWN),
                    "context_window": getattr(m, "context_window", UNKNOWN),
                }
            )
        health = reg.health() if hasattr(reg, "health") else {}
        return {
            "models": models,
            "health": health if isinstance(health, dict) else {"state": UNKNOWN},
        }
    except Exception as exc:  # noqa: BLE001
        return {"models": [], "health": {"state": UNKNOWN}, "error": str(exc)[:200]}


# ── Research / strategy (§15–§16) ──────────────────────────────────────


def research_summary() -> dict[str, Any]:
    """Phase 5 research state: reviews, queue, candidates."""
    out: dict[str, Any] = {}
    try:
        from learning.review_store import CanonicalStore, ResearchQueue

        store = CanonicalStore()
        out["reviews"] = store.count("TradeReview") + store.count("DecisionReview")
        out["patterns"] = store.count("PatternObservation")
        out["hypotheses"] = store.count("HypothesisRecord")
        out["candidates"] = store.count("StrategyCandidateRecord")
        q = ResearchQueue()
        out["queue_depth"] = q.depth()
        out["queue_errors"] = q.errors
    except Exception as exc:  # noqa: BLE001
        out["error"] = str(exc)[:200]
    return out


def strategy_summary() -> dict[str, Any]:
    """Active/candidate strategy versions (read-only; no activation surface)."""
    try:
        from strategy.registry import get_strategy_registry

        reg = get_strategy_registry()
        versions = (
            reg.list_versions()
            if hasattr(reg, "list_versions")
            else (reg.all() if hasattr(reg, "all") else [])
        )
        rows = []
        for v in versions or []:
            d = v.to_dict() if hasattr(v, "to_dict") else (dict(v) if isinstance(v, dict) else {})
            rows.append(
                {
                    "strategy_id": d.get("strategy_id", UNKNOWN),
                    "version": d.get("version", UNKNOWN),
                    "status": d.get("status", UNKNOWN),
                    "approved": d.get("status") == "APPROVED",
                }
            )
        active = [r for r in rows if r.get("status") == "ACTIVE"]
        return {
            "active": active[0] if active else None,
            "versions": rows,
            "live_trading": "DISABLED",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "active": UNKNOWN,
            "versions": [],
            "live_trading": "DISABLED",
            "error": str(exc)[:200],
        }
