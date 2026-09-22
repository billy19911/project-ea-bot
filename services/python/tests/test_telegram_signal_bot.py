# -*- coding: utf-8 -*-
"""Tests for the dedicated Telegram *signal* bot (third bot, XynnSignal).

Goal: cycle reports (digest + market analysis) move to a separate bot so the
primary bot's chat stays clean. Rules under test:

* ``build_signal_gateway_from_env`` — no token → ``None`` (feature off),
  token → real transport, chat ids from ``TELEGRAM_SIGNAL_CHAT_IDS`` (falling
  back to the primary allowlist),
* ``get_report_gateway`` — prefers the signal bot; falls back to the primary
  gateway when the signal bot is missing or half-configured (never silences),
* ``queue_pipeline_result`` / ``notify_pipeline_result`` — deliver through the
  signal bot when configured (primary transport untouched),
* ``/telegram/status`` — honestly reports the signal bot state.

No network and no MT5 are used.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from src.main import app
from src.telegram import TelegramGateway
from src.telegram.notifier import (
    PipelineDigest,
    build_signal_gateway_from_env,
    get_report_gateway,
    notify_pipeline_result,
    queue_pipeline_result,
    reset_digest,
    reset_signal_gateway,
    set_digest,
    set_gateway,
    set_signal_gateway,
)

PRIMARY = 111
SIGNAL = 222

client = TestClient(app)


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------
class RecordingTransport:
    """In-memory transport capturing (chat_id, text) tuples."""

    def __init__(self) -> None:
        self.sent: list[tuple[object, str]] = []

    def send_message(self, chat_id: object, text: str) -> None:
        self.sent.append((chat_id, text))


def _summary(**overrides) -> dict:
    base = {
        "event_type": "MOMENTUM_BULLISH",
        "decision": "NO_TRADE",
        "status": "NO_TRADE",
        "confidence": 0.6,
        "summary": "market_lead: BULLISH (conf=0.60)",
        "risk_reason": "no actionable proposal",
        "executed": False,
        "trace_id": "trace-sig",
        "symbol": "XAUUSD",
        "queued_at": 1_700_000_000.0,
    }
    base.update(overrides)
    return base


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch):
    """Give each test clean primary + signal singletons and no leaked env."""
    for name in ("TELEGRAM_SIGNAL_BOT_TOKEN", "TELEGRAM_SIGNAL_CHAT_IDS"):
        monkeypatch.delenv(name, raising=False)
    set_gateway(None)
    reset_signal_gateway()
    reset_digest()
    yield
    set_gateway(None)
    reset_signal_gateway()
    reset_digest()


# ---------------------------------------------------------------------------
# build_signal_gateway_from_env
# ---------------------------------------------------------------------------
def test_signal_gateway_without_token_is_none(monkeypatch) -> None:
    assert build_signal_gateway_from_env() is None


def test_signal_gateway_with_token_builds_transport(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_SIGNAL_BOT_TOKEN", "999:XYZ")
    monkeypatch.setenv("TELEGRAM_SIGNAL_CHAT_IDS", "222,333")

    gateway = build_signal_gateway_from_env()

    assert gateway is not None
    assert gateway.transport is not None
    assert gateway.allowlist == {"222", "333"}


def test_signal_gateway_falls_back_to_primary_allowlist(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_SIGNAL_BOT_TOKEN", "999:XYZ")
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "111,222")

    gateway = build_signal_gateway_from_env()

    assert gateway is not None
    assert gateway.allowlist == {"111", "222"}


# ---------------------------------------------------------------------------
# get_report_gateway
# ---------------------------------------------------------------------------
def test_report_gateway_prefers_signal_bot() -> None:
    primary_transport = RecordingTransport()
    signal_transport = RecordingTransport()
    set_gateway(TelegramGateway(transport=primary_transport, allowlist=[PRIMARY]))
    set_signal_gateway(TelegramGateway(transport=signal_transport, allowlist=[SIGNAL]))

    gateway = get_report_gateway()

    assert gateway is not None
    assert gateway.transport is signal_transport


def test_report_gateway_falls_back_without_signal_token() -> None:
    primary_transport = RecordingTransport()
    set_gateway(TelegramGateway(transport=primary_transport, allowlist=[PRIMARY]))

    gateway = get_report_gateway()

    assert gateway is not None
    assert gateway.transport is primary_transport


def test_report_gateway_falls_back_when_signal_half_configured(monkeypatch) -> None:
    """Signal token but no recipients at all → fall back (never silence)."""
    monkeypatch.setenv("TELEGRAM_SIGNAL_BOT_TOKEN", "999:XYZ")
    monkeypatch.delenv("TELEGRAM_SIGNAL_CHAT_IDS", raising=False)
    monkeypatch.delenv("TELEGRAM_ALLOWED_CHAT_IDS", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_IDS", raising=False)
    reset_signal_gateway()

    primary_transport = RecordingTransport()
    set_gateway(TelegramGateway(transport=primary_transport, allowlist=[PRIMARY]))

    gateway = get_report_gateway()

    assert gateway is not None
    assert gateway.transport is primary_transport


# ---------------------------------------------------------------------------
# Routing: reports go to the signal bot, primary stays clean
# ---------------------------------------------------------------------------
def test_digest_routes_to_signal_bot() -> None:
    """An injected signal gateway receives the digest; primary stays clean."""
    primary_transport = RecordingTransport()
    signal_transport = RecordingTransport()
    set_gateway(TelegramGateway(transport=primary_transport, allowlist=[PRIMARY]))
    set_signal_gateway(TelegramGateway(transport=signal_transport, allowlist=[SIGNAL]))
    set_digest(PipelineDigest(max_items=5))

    assert queue_pipeline_result(_summary()) is True
    assert signal_transport.sent == []  # waiting for the digest window

    from src.telegram.notifier import flush_pipeline_digest

    assert flush_pipeline_digest() is True
    assert primary_transport.sent == []  # primary bot stays clean
    chat_id, text = signal_transport.sent[0]
    assert str(chat_id) == str(SIGNAL)
    assert "Ringkasan Siklus" in text


def test_urgent_decision_routes_to_signal_bot() -> None:
    primary_transport = RecordingTransport()
    signal_transport = RecordingTransport()
    set_gateway(TelegramGateway(transport=primary_transport, allowlist=[PRIMARY]))
    set_signal_gateway(TelegramGateway(transport=signal_transport, allowlist=[SIGNAL]))
    set_digest(PipelineDigest(max_items=5))

    assert queue_pipeline_result(_summary(decision="BUY")) is True

    assert primary_transport.sent == []  # primary bot stays clean
    assert len(signal_transport.sent) == 1  # bypassed the digest, still signal bot


def test_notify_pipeline_result_routes_to_signal_bot() -> None:
    primary_transport = RecordingTransport()
    signal_transport = RecordingTransport()
    set_gateway(TelegramGateway(transport=primary_transport, allowlist=[PRIMARY]))
    set_signal_gateway(TelegramGateway(transport=signal_transport, allowlist=[SIGNAL]))

    assert notify_pipeline_result(_summary()) is True
    assert primary_transport.sent == []
    assert signal_transport.sent


def test_reports_stay_on_primary_without_signal_token() -> None:
    primary_transport = RecordingTransport()
    set_gateway(TelegramGateway(transport=primary_transport, allowlist=[PRIMARY]))

    assert notify_pipeline_result(_summary()) is True
    assert len(primary_transport.sent) == 1  # legacy behaviour intact


# ---------------------------------------------------------------------------
# /telegram/status honesty
# ---------------------------------------------------------------------------
def test_telegram_status_reports_signal_bot_configured(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:ABC")
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "111")
    monkeypatch.setenv("TELEGRAM_SIGNAL_BOT_TOKEN", "999:XYZ")
    monkeypatch.setenv("TELEGRAM_SIGNAL_CHAT_IDS", "222")
    set_gateway(None)
    reset_signal_gateway()

    resp = client.get("/telegram/status")
    data = resp.json()

    assert data["signal_bot_configured"] is True
    assert data["connected"] is True  # primary bot unchanged


def test_telegram_status_signal_bot_absent(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:ABC")
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "111")
    monkeypatch.delenv("TELEGRAM_SIGNAL_BOT_TOKEN", raising=False)
    set_gateway(None)
    reset_signal_gateway()

    resp = client.get("/telegram/status")
    data = resp.json()

    assert data["signal_bot_configured"] is False
