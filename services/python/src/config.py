"""Application configuration from environment variables."""

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    app_name: str = Field(default="ea-bot-python", alias="APP_NAME")
    environment: str = Field(default="development", alias="ENVIRONMENT")
    debug: bool = Field(default=False, alias="DEBUG")

    # Server
    host: str = Field(default="0.0.0.0", alias="HOST")
    port: int = Field(default=8000, alias="PORT")

    # MT5 (Jonhson MT5 — read-only sandbox, no real funds)
    mt5_terminal_path: str = Field(default="", alias="MT5_TERMINAL_PATH")
    mt5_login: int | None = Field(default=None, alias="MT5_LOGIN")
    mt5_password: str | None = Field(default=None, alias="MT5_PASSWORD")
    mt5_server: str = Field(default="", alias="MT5_SERVER")

    # Database
    database_url: str = Field(default="sqlite:///./ea_bot.db", alias="DATABASE_URL")

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
