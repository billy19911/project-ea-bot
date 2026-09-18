"""Telegram control/communication gateway (PRD_V2 §21 / §32.18)."""

from src.telegram.gateway import TelegramGateway
from src.telegram.notifier import (
    build_gateway_from_env,
    get_gateway,
    notify_pipeline_result,
    set_gateway,
    summarize_pipeline_result,
)
from src.telegram.transport import HttpTelegramTransport

__all__ = [
    "TelegramGateway",
    "HttpTelegramTransport",
    "build_gateway_from_env",
    "get_gateway",
    "set_gateway",
    "notify_pipeline_result",
    "summarize_pipeline_result",
]
