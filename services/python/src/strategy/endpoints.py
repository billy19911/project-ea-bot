# -*- coding: utf-8 -*-
"""FastAPI router exposing the :class:`StrategyRegistry` over HTTP (EPIC 13).

The Node API control plane (Strategy Center) previously served a hard-coded
``strategiesDB`` with four fabricated rows. This router replaces that seed data
with the *real* process-wide registry so the web page reflects actual
lifecycle/governance metadata.

Honesty note (PRD_V2 §19): the registry stores **lifecycle and governance
metadata** — registered versions, their status, parameters and timestamps. It is
*not* the execution configuration. The deterministic engine executes
:data:`src.trading.engine.DEFAULT_CONFIG`; the ``technical_analysis`` strategy
registered here simply *describes* that live configuration so the control plane
has something real to display. Do not overclaim: activating/retiring a strategy
here changes governance state only, not what the engine runs.

Every success response carries ``source="live"``. No fabricated fallback is ever
returned; an empty registry honestly yields an empty list.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..trading.engine import DEFAULT_CONFIG
from .registry import PromotionError, StrategyRegistry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/strategies", tags=["strategy-registry"])

# ---------------------------------------------------------------------------
# Process-wide registry
# ---------------------------------------------------------------------------
#
# A single process-wide registry so the control plane sees the same governance
# state the rest of the system accumulates. Handlers call
# :func:`get_strategy_registry` per request rather than capturing the object at
# import time, so tests can swap in a fresh instance.

_registry: StrategyRegistry = StrategyRegistry()

_LIVE_NAME = "technical_analysis"
_LIVE_VERSION = "v1.0.0"


def get_strategy_registry() -> StrategyRegistry:
    """Return the process-wide strategy registry."""
    return _registry


def register_live_strategy() -> None:
    """Register the real live engine configuration with the registry.

    Idempotent: if ``technical_analysis`` ``v1.0.0`` is already registered it is
    left untouched. Otherwise it is registered with the actual
    :data:`DEFAULT_CONFIG` parameters used by the deterministic engine, then
    activated.
    """
    registry = get_strategy_registry()
    if registry.get(_LIVE_NAME, _LIVE_VERSION) is not None:
        return
    registry.register(
        name=_LIVE_NAME,
        version=_LIVE_VERSION,
        parameters=dict(DEFAULT_CONFIG),
        description="Deterministic TradingEngine default configuration (live)",
    )
    registry.activate(_LIVE_NAME, _LIVE_VERSION)
    logger.info("Registered live strategy %s %s", _LIVE_NAME, _LIVE_VERSION)


@router.get("", summary="List registered strategies")
async def list_strategies() -> dict[str, Any]:
    """Return every registered strategy version, sorted by ``(name, version)``."""
    registry = get_strategy_registry()
    strategies = sorted(registry.list_all(), key=lambda s: (s.name, s.version))
    return {"strategies": [s.to_dict() for s in strategies], "source": "live"}


@router.get("/{strategy_id}", summary="Get a strategy by id")
async def get_strategy(strategy_id: str) -> Any:
    """Return a single strategy version by its ``strategy_id``."""
    registry = get_strategy_registry()
    for strategy in registry.list_all():
        if strategy.strategy_id == strategy_id:
            return {"strategy": strategy.to_dict(), "source": "live"}
    return JSONResponse(status_code=404, content={"error": "strategy_not_found"})


@router.post("/{strategy_id}/active", summary="Activate or retire a strategy")
async def set_active(strategy_id: str, body: dict[str, Any]) -> Any:
    """Activate (``active=true``) or retire (``active=false``) a strategy version.

    Activation is gated (audit P1-5): the promotion gate must approve, using the
    strategy's recorded ``metrics_summary``/``validation_evidence`` (or evidence
    supplied in the request body). A denied promotion returns 409 with the
    reason — a strategy can no longer be flipped ACTIVE without evidence.
    """
    active = body.get("active") if isinstance(body, dict) else None
    if not isinstance(active, bool):
        return JSONResponse(status_code=400, content={"error": "active must be boolean"})

    registry = get_strategy_registry()
    target = next(
        (s for s in registry.list_all() if s.strategy_id == strategy_id),
        None,
    )
    if target is None:
        return JSONResponse(status_code=404, content={"error": "strategy_not_found"})

    if active:
        # Optional inline evidence (metrics / validation_passed) wins over the
        # strategy's stored evidence, so the caller can record evidence at
        # activation time.
        metrics = body.get("metrics")
        if isinstance(metrics, dict):
            target.metrics_summary = metrics
        if "validation_passed" in body:
            target.validation_evidence = {
                **target.validation_evidence,
                "passed": bool(body.get("validation_passed")),
            }
        try:
            registry.activate(target.name, target.version, enforce_evidence=True)
        except PromotionError as exc:
            return JSONResponse(
                status_code=409,
                content={"error": "promotion_denied", "reason": str(exc)},
            )
        message = f"Strategi {target.name} diaktifkan"
    else:
        registry.retire(target.name, target.version)
        message = f"Strategi {target.name} dinonaktifkan"

    return {"strategy": target.to_dict(), "message": message}
