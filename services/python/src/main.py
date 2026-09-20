"""FastAPI application skeleton for EA Bot Python services."""

import asyncio
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
from .review.intelligence import ReviewLead
from .risk.intelligence import RiskLead
from .strategy.endpoints import register_live_strategy
from .strategy.endpoints import router as strategy_router
from .system.endpoints import router as system_router
from .system.v2_endpoints import router as v2_router
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

    ``RiskLead`` is the advisory risk department lead (EPIC 05): risk events
    (``RISK_``, ``DRAWDOWN_``, ``MARGIN_``, …) route to its committee for
    advisory evidence. The deterministic Risk Gate remains the sole authority
    over hard limits — RiskLead can never veto, bypass, or reach MT5.

    ``ReviewLead`` is the post-trade review department lead (EPIC 06):
    ``TRADE_CLOSE*`` / ``POST_TRADE_REVIEW`` events route to its review
    specialist, which extracts deterministic lessons and persists them through
    the injectable lesson store. Review is analysis-only — it can never reach
    MT5, the Risk Gate, or the Execution Engine.
    """
    default_agents = [
        TechnicalAnalystAgent(),
        MomentumAnalystAgent(),
        StructureAnalystAgent(),
        VolatilityAnalystAgent(),
        NewsSentimentAgent(),
        FundamentalAnalystAgent(),
        MarketLead(),
        RiskLead(),
        ReviewLead(),
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
    # Learning feedback (Fase 7) — persist lessons across restarts (JSONL) and
    # bridge the paper-close review path into the *same* store the ReviewLead
    # writes to. Wired before agent registration so ReviewLead captures the
    # persistent store. Fail-safe: a wiring error must never block startup.
    try:
        from agents.analysts.review_agent import get_lesson_store, set_lesson_store
        from learning.feedback import record_review_lesson
        from learning.lesson_store import JsonlLessonStore
        from review.auto_trigger import ReviewAutoTrigger, set_auto_trigger

        set_lesson_store(JsonlLessonStore())
        set_auto_trigger(
            ReviewAutoTrigger(
                on_review=lambda record: record_review_lesson(get_lesson_store(), record)
            )
        )
        logger.info("Learning feedback wired: persistent lesson store + review bridge")
    except Exception:  # pragma: no cover - defensive, never block startup
        logger.exception("Learning feedback wiring failed (system continues)")

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

    # Market feed loop (Fase 6) — OFF by default; operator opts in via
    # MARKET_FEED_ENABLED=true. Reads MT5 OHLC (read-only) and enqueues
    # detected events so the scheduler analyses the market autonomously.
    feed_task = None
    if settings.market_feed_enabled:
        from .trading.feed_loop import MarketFeedLoop

        runtime = get_runtime()
        feed = MarketFeedLoop(
            queue=runtime.queue,
            symbols=[s.strip() for s in settings.market_feed_symbols.split(",") if s.strip()],
            timeframe=settings.market_feed_timeframe,
            interval_s=settings.market_feed_interval_s,
            event_cooldown_s=settings.market_feed_event_cooldown_s,
        )
        feed_task = asyncio.create_task(feed.run())
        logger.info(
            "Market feed loop started (symbols=%s, timeframe=%s, interval=%ss)",
            settings.market_feed_symbols,
            settings.market_feed_timeframe,
            settings.market_feed_interval_s,
        )

    # Telegram inbound poller (optional) — OFF unless TELEGRAM_POLLER_ENABLED
    # is truthy AND a dedicated bot token is configured. Telegram allows only
    # one getUpdates consumer per bot, so this uses a *second* bot
    # (TELEGRAM_POLLER_BOT_TOKEN) and never the report bot's token. Read-only
    # command surface — it can never place an order.
    poller = None
    poller_task = None
    try:
        from .telegram.poller import build_poller_from_env

        poller = build_poller_from_env()
        if poller is not None:
            poller_task = asyncio.create_task(poller.run())
            logger.info("Telegram inbound poller started (read-only commands)")
    except Exception:  # pragma: no cover - defensive, never block startup
        logger.exception("Telegram poller wiring failed (system continues)")

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

    if feed_task is not None:
        try:
            feed.stop()
            await asyncio.wait_for(feed_task, timeout=5.0)
        except Exception:  # pragma: no cover - defensive
            logger.exception("Error stopping market feed loop")

    if poller_task is not None:
        try:
            poller.stop()
            await asyncio.wait_for(poller_task, timeout=5.0)
        except Exception:  # pragma: no cover - defensive
            logger.exception("Error stopping Telegram poller")

    if scheduler_task is not None:
        try:
            await get_runtime().scheduler.stop()
        except Exception:  # pragma: no cover - defensive
            logger.exception("Error stopping autonomous scheduler")

    # Flush any pending Telegram digest batch so a clean shutdown never
    # leaves queued reports undelivered. Fail-safe: a Telegram outage must
    # never block shutdown.
    try:
        from .telegram.notifier import flush_pipeline_digest

        flush_pipeline_digest()
    except Exception:  # pragma: no cover - defensive
        logger.exception("Error flushing Telegram digest")

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
app.include_router(v2_router)
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
