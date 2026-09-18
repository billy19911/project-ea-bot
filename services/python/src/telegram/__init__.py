"""Telegram control/communication gateway (PRD_V2 §21 / §32.18)."""

from src.telegram.gateway import TelegramGateway
from src.telegram.notifier import (
    PipelineDigest,
    build_gateway_from_env,
    flush_pipeline_digest,
    get_gateway,
    notify_pipeline_result,
    queue_pipeline_result,
    reset_digest,
    set_digest,
    set_gateway,
    summarize_pipeline_result,
)
from src.telegram.transport import HttpTelegramTransport

__all__ = [
    "TelegramGateway",
    "HttpTelegramTransport",
    "PipelineDigest",
    "build_gateway_from_env",
    "get_gateway",
    "set_gateway",
    "notify_pipeline_result",
    "queue_pipeline_result",
    "flush_pipeline_digest",
    "set_digest",
    "reset_digest",
    "summarize_pipeline_result",
]
