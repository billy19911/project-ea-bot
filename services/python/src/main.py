"""FastAPI application skeleton for EA Bot Python services."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .agents.registry import agent_registry
from .config import settings
from .mt5.endpoints import router as mt5_router
from .trading.endpoints import router as trading_router
from .trading.events import router as events_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — startup and shutdown hooks."""
    # Startup
    yield
    # Shutdown


app = FastAPI(
    title=settings.app_name,
    description="AI autonomous trading system — Python services",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — adjust origins in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(mt5_router)
app.include_router(trading_router)
app.include_router(events_router)


# Agent registry singleton — registered at startup
@app.on_event("startup")
async def register_default_agents():
    """Register core agents into the singleton registry."""
    from .agents.base import TechnicalAnalystAgent

    agent_registry.register(TechnicalAnalystAgent())


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
