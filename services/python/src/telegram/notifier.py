# -*- coding: utf-8 -*-
"""Telegram notifier — pipeline reports for the user (Phase 5).

Wires the read-only :class:`TelegramGateway` into the orchestration loop:

* ``summarize_pipeline_result`` — compact, honest summary of a pipeline record,
* ``notify_pipeline_result`` — fail-safe delivery through the shared gateway,
* ``build_gateway_from_env`` / ``get_gateway`` / ``set_gateway`` — env-driven
  gateway singleton (no token → transport stays ``None``, feature is off).

Design rules:

* Fail-safe: a Telegram outage must never break the autonomous loop — every
  helper here catches its own errors.
* No token in logs; the transport never leaks it either.
* No execution / MT5 imports.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from .gateway import TelegramGateway
from .transport import HttpTelegramTransport

logger = logging.getLogger(__name__)

__all__ = [
    "build_gateway_from_env",
    "get_gateway",
    "set_gateway",
    "notify_pipeline_result",
    "summarize_pipeline_result",
]

# Max length of the free-text summary carried in a report (Telegram-friendly).
_SUMMARY_MAX_CHARS = 240

_gateway: Optional[TelegramGateway] = None


def _parse_allowlist(raw: str) -> list[str]:
    """Split a comma-separated chat-id list into trimmed non-empty items."""
    return [cid.strip() for cid in (raw or "").split(",") if cid.strip()]


def build_gateway_from_env() -> TelegramGateway:
    """Build a gateway from ``TELEGRAM_BOT_TOKEN`` / ``TELEGRAM_ALLOWED_CHAT_IDS``.

    Without a token the transport stays ``None`` — the gateway still works as a
    read-only command surface (legacy behaviour) but sends nothing.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN") or ""
    raw_allowlist = os.getenv("TELEGRAM_ALLOWED_CHAT_IDS") or os.getenv("TELEGRAM_CHAT_IDS") or ""
    allowlist = _parse_allowlist(raw_allowlist)

    transport: Optional[HttpTelegramTransport] = None
    if token.strip():
        try:
            transport = HttpTelegramTransport(token=token)
        except Exception:  # pragma: no cover - defensive; blank handled above
            logger.warning("Could not build Telegram transport; alerts disabled")
            transport = None

    return TelegramGateway(transport=transport, allowlist=allowlist)


def get_gateway() -> TelegramGateway:
    """Return the process-wide gateway, building it from env on first use."""
    global _gateway
    if _gateway is None:
        _gateway = build_gateway_from_env()
    return _gateway


def set_gateway(gateway: Optional[TelegramGateway]) -> None:
    """Override the process-wide gateway (used by tests / startup wiring)."""
    global _gateway
    _gateway = gateway


def summarize_pipeline_result(result: dict[str, Any]) -> dict[str, Any]:
    """Return a compact, JSON-friendly summary of a pipeline record.

    Missing fields degrade to honest defaults — never fabricates values.
    """
    record = result if isinstance(result, dict) else {}

    summary_text = str(record.get("summary") or "")
    if len(summary_text) > _SUMMARY_MAX_CHARS:
        summary_text = summary_text[: _SUMMARY_MAX_CHARS - 3] + "..."

    confidence: float = 0.0
    try:
        confidence = float(record.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0

    return {
        "event_type": str(record.get("event_type") or ""),
        "decision": str(record.get("decision") or ""),
        "status": str(record.get("status") or ""),
        "confidence": confidence,
        "summary": summary_text,
        "risk_reason": str(record.get("risk_reason") or ""),
        "executed": bool(record.get("executed", False)),
        "trace_id": str(record.get("trace_id") or ""),
    }


def notify_pipeline_result(
    result: dict[str, Any],
    gateway: Optional[TelegramGateway] = None,
) -> bool:
    """Send a ``pipeline_result`` report. Never raises.

    Returns True when the message was dispatched, False otherwise (no
    transport / no allowlist / delivery failure — all silently degraded).
    """
    try:
        gw = gateway if gateway is not None else get_gateway()
        if gw is None:
            return False
        # Feature off (no bot token configured): stay quiet — a disabled
        # notifier must not log-spam every autonomous cycle.
        if getattr(gw, "transport", "unknown") is None:
            return False
        summary = summarize_pipeline_result(result)
        return bool(gw.notify("pipeline_result", summary))
    except Exception as exc:  # noqa: BLE001 - Telegram must never break autonomy
        logger.warning("Telegram pipeline report failed (%s); cycle unaffected", type(exc).__name__)
        return False
