"""FastAPI application skeleton for EA Bot Python services."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .agents.registry import agent_registry
from .config import settings
from .mt5.endpoints import router as mt5_router
from .orchestration.endpoints import router as orchestration_router
from .orchestration.runtime import get_runtime
from .system.endpoints import router as system_router
from .trading.endpoints import router as trading_router
from .trading.events import router as events_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — startup and shutdown hooks."""
    # Startup
    from .agents.base import TechnicalAnalystAgent

    agent_registry.register(TechnicalAnalystAgent())

    # Autonomous scheduler (PRD_V2 §10.3, §32.17) — optional, non-blocking.
    scheduler_task = None
    if settings.scheduler_enabled:
        runtime = get_runtime()
        runtime.scheduler.poll_interval = settings.scheduler_poll_interval
        # start() creates the loop via asyncio.create_task, so startup is not
        # blocked. It returns immediately.
        await runtime.scheduler.start()
        scheduler_task = runtime.scheduler._task
        logger.info(
            "Autonomous scheduler started (poll_interval=%s)",
            settings.scheduler_poll_interval,
        )

    yield

    # Shutdown
    if scheduler_task is not None:
        try:
            await get_runtime().scheduler.stop()
        except Exception:  # pragma: no cover - defensive
            logger.exception("Error stopping autonomous scheduler")


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
app.include_router(trading_router)
app.include_router(events_router)
app.include_router(orchestration_router)
app.include_router(system_router)


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
