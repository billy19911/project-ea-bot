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
from typing import Any, Optional

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


def get_active_strategy_config() -> Optional[dict[str, Any]]:
    """Return the active strategy's parameters, or None if no strategy is active.

    This helper bridges StrategyRegistry → TradingEngine: when a strategy is
    activated via the API, the engine uses its parameters instead of DEFAULT_CONFIG.
    """
    registry = get_strategy_registry()
    # Try technical_analysis first (live default), then any other active strategy
    active = registry.get_active_version(_LIVE_NAME)
    if active is None:
        # Check if any other strategy is active
        for strategy in registry.list_all():
            if strategy.status.value == "ACTIVE":
                active = strategy
                break
    if active is not None:
        return dict(active.parameters)
    return None


@router.get("", summary="List registered strategies")
async def list_strategies() -> dict[str, Any]:
    """Return every registered strategy version, sorted by ``(name, version)``."""
    registry = get_strategy_registry()
    strategies = sorted(registry.list_all(), key=lambda s: (s.name, s.version))
    return {"strategies": [s.to_dict() for s in strategies], "source": "live"}


@router.get("/active", summary="Get the currently active strategy")
async def get_active_strategy() -> Any:
    """Return the currently active strategy and its configuration.

    Returns 404 if no strategy is currently active.
    """
    config = get_active_strategy_config()
    if config is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": "no_active_strategy",
                "reason": "No strategy is currently active",
            },
        )

    registry = get_strategy_registry()
    active = registry.get_active_version(_LIVE_NAME)
    if active is None:
        for strategy in registry.list_all():
            if strategy.status.value == "ACTIVE":
                active = strategy
                break

    return {
        "strategy": active.to_dict() if active else None,
        "config": config,
        "source": "live",
    }


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
        return JSONResponse(
            status_code=400, content={"error": "active must be boolean"}
        )

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


# ---------------------------------------------------------------------------
# CRUD endpoints — create / edit / retire strategies via API
# ---------------------------------------------------------------------------


def _find_by_id(registry: StrategyRegistry, strategy_id: str) -> Optional[Any]:
    """Find a VersionedStrategy by strategy_id, or None."""
    return next(
        (s for s in registry.list_all() if s.strategy_id == strategy_id),
        None,
    )


@router.post("", summary="Create a new strategy version")
async def create_strategy(body: dict[str, Any]) -> Any:
    """Register a new strategy version.

    Required body fields: ``name`` (str), ``version`` (str).
    Optional: ``parameters`` (dict), ``description`` (str).

    Returns 409 if a strategy with the same ``(name, version)`` already exists.
    """
    name = body.get("name") if isinstance(body, dict) else None
    version = body.get("version") if isinstance(body, dict) else None
    if not isinstance(name, str) or not name.strip():
        return JSONResponse(status_code=400, content={"error": "name is required"})
    if not isinstance(version, str) or not version.strip():
        return JSONResponse(status_code=400, content={"error": "version is required"})

    parameters = body.get("parameters", {})
    if not isinstance(parameters, dict):
        return JSONResponse(
            status_code=400, content={"error": "parameters must be an object"}
        )
    description = body.get("description", "")
    if not isinstance(description, str):
        description = ""

    registry = get_strategy_registry()
    if registry.get(name, version) is not None:
        return JSONResponse(
            status_code=409,
            content={
                "error": "strategy_exists",
                "reason": f"Strategy {name} version {version} already exists",
            },
        )
    strategy = registry.register(
        name=name,
        version=version,
        parameters=parameters,
        description=description,
    )
    return JSONResponse(
        status_code=201,
        content={"strategy": strategy.to_dict(), "source": "live"},
    )


@router.patch("/{strategy_id}", summary="Edit a strategy's mutable fields")
async def edit_strategy(strategy_id: str, body: dict[str, Any]) -> Any:
    """Edit a strategy's mutable fields (description, parameters, risk_policy,
    compatible_regimes, rationale).

    Parameters of an ACTIVE strategy are read-only (frozen by ``freeze_parameters``).
    Editing such a strategy returns 409. Retire it first or create a new version.
    """
    registry = get_strategy_registry()
    target = _find_by_id(registry, strategy_id)
    if target is None:
        return JSONResponse(status_code=404, content={"error": "strategy_not_found"})

    is_active = target.status.value == "ACTIVE"

    # Validate the entire request before applying any mutation, so a bad
    # ``parameters`` on an ACTIVE strategy does not leave a partial edit behind.
    description = body.get("description")
    if description is not None and not isinstance(description, str):
        return JSONResponse(
            status_code=400, content={"error": "description must be a string"}
        )

    risk_policy = body.get("risk_policy")
    if risk_policy is not None and not isinstance(risk_policy, dict):
        return JSONResponse(
            status_code=400, content={"error": "risk_policy must be an object"}
        )

    compatible_regimes = body.get("compatible_regimes")
    if compatible_regimes is not None and not isinstance(compatible_regimes, list):
        return JSONResponse(
            status_code=400, content={"error": "compatible_regimes must be a list"}
        )

    rationale = body.get("rationale")
    if rationale is not None and not isinstance(rationale, str):
        return JSONResponse(
            status_code=400, content={"error": "rationale must be a string"}
        )

    parameters = body.get("parameters")
    if parameters is not None and not isinstance(parameters, dict):
        return JSONResponse(
            status_code=400, content={"error": "parameters must be an object"}
        )
    if parameters is not None and is_active:
        return JSONResponse(
            status_code=409,
            content={
                "error": "parameters_frozen",
                "reason": (
                    "Cannot edit parameters of an ACTIVE strategy. "
                    "Retire it first or create a new version."
                ),
            },
        )

    # All fields validated — apply atomically.
    if isinstance(description, str):
        target.description = description
    if isinstance(risk_policy, dict):
        target.risk_policy = risk_policy
    if isinstance(compatible_regimes, list):
        target.compatible_regimes = list(compatible_regimes)
    if isinstance(rationale, str):
        target.rationale = rationale
    if isinstance(parameters, dict):
        target.parameters = parameters

    return {"strategy": target.to_dict(), "source": "live"}


@router.delete("/{strategy_id}", summary="Retire a strategy")
async def retire_strategy(strategy_id: str) -> Any:
    """Retire a strategy version (lifecycle status → RETIRED).

    Retiring an already-RETIRED strategy is a no-op and returns 200.
    Returns 404 if the strategy id is not found.
    """
    registry = get_strategy_registry()
    target = _find_by_id(registry, strategy_id)
    if target is None:
        return JSONResponse(status_code=404, content={"error": "strategy_not_found"})

    registry.retire(target.name, target.version)
    return {
        "strategy": target.to_dict(),
        "message": f"Strategi {target.name} dihapus",
        "source": "live",
    }
