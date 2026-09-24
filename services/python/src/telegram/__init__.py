"""Telegram control/communication gateway (PRD_V2 §21 / §32.18)."""

from src.telegram.gateway import TelegramGateway
from src.telegram.notifier import (
    PipelineDigest,
    build_gateway_from_env,
    build_signal_gateway_from_env,
    flush_pipeline_digest,
    get_gateway,
    get_report_gateway,
    get_signal_gateway,
    notify_pipeline_result,
    queue_pipeline_result,
    reset_digest,
    reset_signal_gateway,
    set_digest,
    set_gateway,
    set_signal_gateway,
    summarize_pipeline_result,
)
from src.telegram.signal_lifecycle import get_signal_lifecycle, reset_signal_lifecycle
from src.telegram.transport import HttpTelegramTransport

__all__ = [
    "TelegramGateway",
    "HttpTelegramTransport",
    "PipelineDigest",
    "build_gateway_from_env",
    "build_signal_gateway_from_env",
    "get_gateway",
    "get_report_gateway",
    "get_signal_gateway",
    "set_gateway",
    "set_signal_gateway",
    "reset_signal_gateway",
    "notify_pipeline_result",
    "queue_pipeline_result",
    "flush_pipeline_digest",
    "set_digest",
    "reset_digest",
    "summarize_pipeline_result",
    "get_signal_lifecycle",
    "reset_signal_lifecycle",
]
