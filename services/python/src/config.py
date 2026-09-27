"""Application configuration from environment variables."""

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    app_name: str = Field(default="ea-bot-python", alias="APP_NAME")
    environment: str = Field(default="development", alias="ENVIRONMENT")
    debug: bool = Field(default=False, alias="DEBUG")

    # Server
    host: str = Field(default="127.0.0.1", alias="HOST")
    port: int = Field(default=8787, alias="PORT")

    # API authentication (audit P0-1). When ``PYTHON_API_KEY`` is set, every
    # request except the health/read-only probes below must present a matching
    # ``X-API-Key`` header (or ``Authorization: Bearer <key>``). When unset the
    # service runs unauthenticated — acceptable ONLY for local dev on a
    # loopback bind. Production MUST set this key.
    python_api_key: str = Field(default="", alias="PYTHON_API_KEY")
    # Public paths that never require the API key (liveness/readiness probes).
    api_public_paths: str = Field(
        default="/health,/metrics,/",
        alias="PYTHON_API_PUBLIC_PATHS",
    )

    # CORS (PRD_V2 §28 Security) — comma-separated explicit origins. Never use
    # a wildcard together with credentials.
    cors_allowed_origins: str = Field(
        default="http://localhost:3000,http://127.0.0.1:3000",
        alias="CORS_ALLOWED_ORIGINS",
    )

    # MT5 (Jonhson MT5 — read-only sandbox, no real funds)
    mt5_terminal_path: str = Field(default="", alias="MT5_TERMINAL_PATH")
    mt5_login: int | None = Field(default=None, alias="MT5_LOGIN")
    mt5_password: str | None = Field(default=None, alias="MT5_PASSWORD")
    mt5_server: str = Field(default="", alias="MT5_SERVER")
    mt5_live_data: bool = Field(default=False, alias="MT5_LIVE_DATA")

    # Database
    database_url: str = Field(default="sqlite:///./ea_bot.db", alias="DATABASE_URL")

    # Autonomous scheduler (PRD_V2 §10.3, §32.17)
    scheduler_enabled: bool = Field(default=True, alias="SCHEDULER_ENABLED")
    scheduler_poll_interval: float = Field(default=1.0, alias="SCHEDULER_POLL_INTERVAL")

    # Market feed loop (Fase 6) — reads MT5 OHLC (read-only) and enqueues
    # detected events so the scheduler analyses the market autonomously.
    # Default OFF: the operator must explicitly switch it on.
    market_feed_enabled: bool = Field(default=False, alias="MARKET_FEED_ENABLED")
    market_feed_symbols: str = Field(default="XAUUSD", alias="MARKET_FEED_SYMBOLS")
    market_feed_timeframe: str = Field(default="M5", alias="MARKET_FEED_TIMEFRAME")
    market_feed_interval_s: float = Field(default=60.0, alias="MARKET_FEED_INTERVAL_S")
    # Anti-spam: minimum seconds before the same (symbol, event_type) may be
    # re-emitted into the pipeline (and reported to Telegram) again.
    market_feed_event_cooldown_s: float = Field(default=300.0, alias="MARKET_FEED_EVENT_COOLDOWN_S")
    # Multi-timeframe analysis (HTF bias + LTF entry). When enabled the feed
    # loop fetches this comma-separated set of timeframes, attaches
    # `timeframe_prices` (multi-TF consensus) and `htf_bias` to every snapshot,
    # and the pipeline may veto LTF entries that fight the HTF trend.
    multi_timeframe_enabled: bool = Field(default=False, alias="MULTI_TIMEFRAME_ENABLED")
    multi_timeframe_list: str = Field(default="M15,H1,H4", alias="MULTI_TIMEFRAME_LIST")
    # HTF bias whose strength is below this is treated as NEUTRAL (no filter).
    multi_timeframe_min_strength: float = Field(default=0.0, alias="MULTI_TIMEFRAME_MIN_STRENGTH")
    # When true, an LTF entry that fights a STRONG HTF bias is vetoed.
    multi_timeframe_filter_enabled: bool = Field(
        default=True, alias="MULTI_TIMEFRAME_FILTER_ENABLED"
    )

    # Risk monitor (FIX B) — periodically checks account drawdown/exposure/margin
    # via MT5 (read-only) and emits RISK_* events so the supervisor routes them
    # to RiskLead. Default OFF: the operator must explicitly switch it on.
    risk_monitor_enabled: bool = Field(default=False, alias="RISK_MONITOR_ENABLED")
    risk_monitor_interval_s: float = Field(default=60.0, alias="RISK_MONITOR_INTERVAL_S")
    # Max drawdown fraction (0.05 = 5%) before RISK_DRAWDOWN is emitted.
    risk_drawdown_threshold: float = Field(default=0.05, alias="RISK_DRAWDOWN_THRESHOLD")
    # Max exposure fraction (margin/equity, 0.30 = 30%) before RISK_EXPOSURE.
    risk_exposure_threshold: float = Field(default=0.30, alias="RISK_EXPOSURE_THRESHOLD")
    # Min free-margin fraction (margin_free/equity, 0.20 = 20%) before RISK_MARGIN.
    risk_margin_threshold: float = Field(default=0.20, alias="RISK_MARGIN_THRESHOLD")

    # Risk engine
    max_position_size: float = Field(default=1000.0, alias="MAX_POSITION_SIZE")
    max_daily_loss: float = Field(default=500.0, alias="MAX_DAILY_LOSS")
    risk_per_trade: float = Field(default=0.02, alias="RISK_PER_TRADE")

    # Dynamic stop-loss management (BEP / progressive TP1 lock / trailing).
    # Applied per cycle by the trade manager to OPEN positions (arm-gated,
    # fail-closed). Default OFF so behaviour is unchanged until opted in.
    sltp_management_enabled: bool = Field(default=False, alias="SLTP_MANAGEMENT_ENABLED")
    sltp_breakeven_enabled: bool = Field(default=True, alias="SLTP_BREAKEVEN_ENABLED")
    # Move to break-even once the position is up by this many R.
    sltp_bep_trigger_r: float = Field(default=1.0, alias="SLTP_BEP_TRIGGER_R")
    # Extra R locked beyond entry at break-even (0 = pure entry).
    sltp_bep_lock_r: float = Field(default=0.0, alias="SLTP_BEP_LOCK_R")
    sltp_progressive_enabled: bool = Field(default=True, alias="SLTP_PROGRESSIVE_ENABLED")
    # Reaching TP1 (this many R) locks this many R of profit.
    sltp_tp1_lock_r: float = Field(default=0.5, alias="SLTP_TP1_LOCK_R")
    sltp_trailing_enabled: bool = Field(default=True, alias="SLTP_TRAILING_ENABLED")
    # Trailing distance = ATR * factor.
    sltp_trail_atr_factor: float = Field(default=1.5, alias="SLTP_TRAIL_ATR_FACTOR")
    # Minimum stop move (in R) before a modification is sent (anti-churn).
    sltp_min_move_r: float = Field(default=0.05, alias="SLTP_MIN_MOVE_R")

    # Supervisor orchestration policy (audit P2-3). ``all_match`` (default) lets
    # every matching department lead / specialist run so departments genuinely
    # collaborate; ``first_match`` collapses to a single agent per cycle;
    # ``priority_based`` keeps all, ordered by priority.
    supervisor_routing_policy: str = Field(default="all_match", alias="SUPERVISOR_ROUTING_POLICY")

    # Signal confidence filter (PRD_V2 §32). Proposals with confidence below
    # this threshold are not actionable regardless of direction. Fail-closed:
    # missing confidence treated as 0.0.
    min_signal_confidence: float = Field(default=0.7, alias="MIN_SIGNAL_CONFIDENCE")

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }


settings = Settings()
