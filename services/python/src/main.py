"""FastAPI application skeleton for EA Bot Python services."""

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agents.analysts import (
    FundamentalAnalystAgent,
    MomentumAnalystAgent,
    NewsSentimentAgent,
    StructureAnalystAgent,
    VolatilityAnalystAgent,
)
from agents.base import TechnicalAnalystAgent
from agents.registry import agent_registry

from .charting.endpoints import router as charting_router
from .config import settings
from .market.endpoints import router as market_router
from .market.intelligence import MarketLead
from .mt5 import connector
from .mt5.endpoints import router as mt5_router
from .observability.sampler import get_trend_sampler
from .orchestration.endpoints import router as orchestration_router
from .orchestration.runtime import get_runtime
from .reports.endpoints import router as reports_router
from .research.endpoints import router as research_router
from .strategy.endpoints import register_live_strategy
from .strategy.endpoints import router as strategy_router
from .system.endpoints import router as system_router
from .trading.endpoints import router as trading_router
from .trading.events import router as events_router

logger = logging.getLogger(__name__)

# Process start time, captured at import. Used to report a REAL service uptime
# (seconds since boot) instead of a placeholder string.
_STARTED_AT = time.time()


def register_default_agents() -> list[str]:
    """Register the default analyst agents; returns newly added names.

    Idempotent: agents already present in the registry are skipped, so a warm
    reload (or a second call) never raises "already registered". Every agent
    here is deterministic and analysis-only — none of them can reach MT5, the
    Risk Gate, or the Execution Engine.

    The ``MarketLead`` department lead is registered last: the Supervisor
    delegates market events to registered department leads first (EPIC 01),
    so the market department answers through its regime-weighted committee.
    """
    default_agents = [
        TechnicalAnalystAgent(),
        MomentumAnalystAgent(),
        StructureAnalystAgent(),
        VolatilityAnalystAgent(),
        NewsSentimentAgent(),
        FundamentalAnalystAgent(),
        MarketLead(),
    ]
    added: list[str] = []
    for agent in default_agents:
        if agent_registry.get(agent.name) is None:
            agent_registry.register(agent)
            added.append(agent.name)
    return added


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — startup and shutdown hooks."""
    # Startup — register every default analyst (idempotent).
    added = register_default_agents()
    logger.info("Registered default agents: %s", added or "none (already present)")

    # Register the real live engine configuration with the strategy registry
    # (EPIC 13) — idempotent, so a warm reload does not duplicate it.
    register_live_strategy()

    # Runtime settings (UI/UX ide #7): stored operator values win over the
    # environment default and are pushed into the live objects now. Runs even
    # when the scheduler is disabled — the supervisor knob still applies.
    # Only knobs actually consumed by the runtime are stored; see
    # system/settings_store.py.
    stored: dict[str, float] = {}
    try:
        from .system.endpoints import _apply_to_runtime
        from .system.settings_store import get_settings_store

        stored = get_settings_store().snapshot().values
        pushed = _apply_to_runtime(stored)
        logger.info("Runtime settings applied at startup: %s", pushed)
    except Exception:  # pragma: no cover - defensive, never block startup
        logger.exception("Gagal menerapkan runtime settings saat startup")

    # Autonomous scheduler (PRD_V2 §10.3, §32.17) — optional, non-blocking.
    scheduler_task = None
    if settings.scheduler_enabled:
        runtime = get_runtime()
        # Env value seeds the scheduler; a stored override (above) wins.
        if "scheduler_poll_interval" not in stored:
            runtime.scheduler.poll_interval = settings.scheduler_poll_interval

        # start() creates the loop via asyncio.create_task, so startup is not
        # blocked. It returns immediately.
        await runtime.scheduler.start()
        scheduler_task = runtime.scheduler._task
        logger.info(
            "Autonomous scheduler started (poll_interval=%s)",
            runtime.scheduler.poll_interval,
        )

    # Trend sampler (UI/UX ide #8) — ring buffer of REAL samples for the
    # dashboard charts. Started regardless of the scheduler: account equity
    # moves whether or not an event is queued. Read-only against MT5.
    trend_sampler = get_trend_sampler()
    await trend_sampler.start()

    if settings.mt5_live_data:
        live_data_started = connector.use_live_data_mode()
        if live_data_started:
            # Run 24: reflect the attached terminal as the initial selection so
            # the dashboard immediately shows which terminal is active. The
            # arm switch itself always starts OFF.
            from .mt5 import terminals as terminal_manager

            terminal_manager.sync_selection_from_attached()
        logger.info("MT5 live data mode startup: %s", live_data_started)

    yield

    # Shutdown
    try:
        await trend_sampler.stop()
    except Exception:  # pragma: no cover - defensive
        logger.exception("Error stopping trend sampler")

    if scheduler_task is not None:
        try:
            await get_runtime().scheduler.stop()
        except Exception:  # pragma: no cover - defensive
            logger.exception("Error stopping autonomous scheduler")

    if connector.is_live_mode():
        connector.shutdown()


app = FastAPI(
    title=settings.app_name,
    description="AI autonomous trading system — Python services",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS (PRD_V2 §28 Security) — env-driven, explicit origins only.
#
# A wildcard origin ("*") must never be combined with credentials=True: browsers
# reject that combination and it would expose authenticated responses to any
# site. We therefore always declare explicit origins from CORS_ALLOWED_ORIGINS
# (comma-separated) and keep credentials enabled only against those origins.
_cors_origins = [
    origin.strip() for origin in settings.cors_allowed_origins.split(",") if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(mt5_router)
app.include_router(charting_router)
app.include_router(trading_router)
app.include_router(events_router)
app.include_router(orchestration_router)
app.include_router(system_router)
app.include_router(strategy_router)
app.include_router(reports_router)
app.include_router(research_router)
app.include_router(market_router)


@app.get("/health")
async def health_check() -> dict:
    """Health check endpoint — includes agent registry and risk gate status."""
    from .trading.risk_gate import RiskGate

    rg = RiskGate()
    safety = rg.check_account_safety(
        account_equity=10000.0,
        account_balance=10000.0,
        margin_used=0.0,
        open_positions_value=0.0,
        daily_pnl=0.0,
        current_drawdown=0.0,
    )

    agents = [a.to_dict() for a in agent_registry.list()]

    return {
        "status": "ok",
        "environment": settings.environment,
        "version": "0.1.0",
        "uptime_seconds": round(time.time() - _STARTED_AT, 1),
        "trading_engine": "deterministic",
        "agents_registered": agent_registry.count(),
        "agents": agents,
        "agent_types": list({a.agent_type for a in agent_registry.list()}),
        "risk_gate": {
            "safe": safety["safe"],
            "flags": safety["flags"],
            "max_daily_loss": safety["checks"]["max_daily_loss"],
            "max_drawdown_pct": safety["checks"]["max_drawdown_pct"],
            "margin_threshold_pct": safety["checks"]["margin_threshold_pct"],
        },
    }


@app.get("/")
async def root():
    """Root endpoint."""
    return {"service": settings.app_name, "version": "0.1.0"}
