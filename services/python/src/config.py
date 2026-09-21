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
    port: int = Field(default=8000, alias="PORT")

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

    # Risk engine
    max_position_size: float = Field(default=1000.0, alias="MAX_POSITION_SIZE")
    max_daily_loss: float = Field(default=500.0, alias="MAX_DAILY_LOSS")
    risk_per_trade: float = Field(default=0.02, alias="RISK_PER_TRADE")

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }


settings = Settings()
