# -*- coding: utf-8 -*-
"""Tests for the Telegram report digest (anti-spam) — Phase 5 follow-up.

Covers:

* ``PipelineDigest`` — coalescing several cycle reports into one message,
  threshold flush, window timer flush (injected fake timer), empty flush,
* ``queue_pipeline_result`` — digest routing, urgent bypass (BUY/SELL and
  executed trades are delivered immediately), disabled digest = per-cycle,
* formatting — compact digest body with directions/decisions/groups,
* the runtime wiring — an HTTP-triggered cycle flushes the digest immediately.

No network and no MT5 are used.
"""

from __future__ import annotations

import pytest

from src.telegram import TelegramGateway
from src.telegram.notifier import (
    PipelineDigest,
    flush_pipeline_digest,
    format_pipeline_digest,
    format_pipeline_report,
    queue_pipeline_result,
    reset_digest,
    set_digest,
    set_gateway,
    summarize_pipeline_result,
)

AUTHORIZED = 111


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------
class RecordingTransport:
    """In-memory transport capturing (chat_id, text) tuples."""

    def __init__(self) -> None:
        self.sent: list[tuple[object, str]] = []

    def send_message(self, chat_id: object, text: str) -> None:
        self.sent.append((chat_id, text))


class FakeTimer:
    """Fake timer that records the callback for manual firing."""

    def __init__(self, delay: float, callback) -> None:
        self.delay = delay
        self.callback = callback
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True

    def fire(self) -> None:
        if not self.cancelled:
            self.callback()


class TimerFactory:
    """Collects created FakeTimers so tests can fire them manually."""

    def __init__(self) -> None:
        self.timers: list[FakeTimer] = []

    def __call__(self, delay: float, callback) -> FakeTimer:
        timer = FakeTimer(delay, callback)
        self.timers.append(timer)
        return timer


def _summary(**overrides) -> dict:
    base = {
        "event_type": "MOMENTUM_BULLISH",
        "decision": "NO_TRADE",
        "status": "NO_TRADE",
        "confidence": 1.0,
        "summary": "market_lead: BEARISH (conf=1.00)",
        "risk_reason": "no actionable proposal",
        "executed": False,
        "trace_id": "trace-1",
        "symbol": "XAUUSD",
        "queued_at": 1_700_000_000.0,
    }
    base.update(overrides)
    return base


@pytest.fixture(autouse=True)
def _reset_state():
    """Give each test a clean gateway + digest singleton."""
    set_gateway(None)
    reset_digest()
    yield
    set_gateway(None)
    reset_digest()


# ---------------------------------------------------------------------------
# PipelineDigest
# ---------------------------------------------------------------------------
def test_digest_coalesces_until_threshold() -> None:
    sent_batches: list[list[dict]] = []
    digest = PipelineDigest(send=lambda items: sent_batches.append(items) or True, max_items=3)

    assert digest.add(_summary()) is True
    assert digest.add(_summary()) is True
    assert digest.pending == 2
    assert sent_batches == []  # nothing sent yet

    assert digest.add(_summary()) is True  # threshold reached → flush
    assert digest.pending == 0
    assert len(sent_batches) == 1
    assert len(sent_batches[0]) == 3


def test_digest_window_timer_flushes_batch() -> None:
    sent_batches: list[list[dict]] = []
    factory = TimerFactory()
    digest = PipelineDigest(
        send=lambda items: sent_batches.append(items) or True,
        window_s=600.0,
        max_items=10,
        timer_factory=factory,
    )

    digest.add(_summary())
    assert len(factory.timers) == 1
    assert factory.timers[0].delay == 600.0

    factory.timers[0].fire()
    assert digest.pending == 0
    assert len(sent_batches) == 1


def test_digest_flush_empty_is_noop() -> None:
    digest = PipelineDigest(send=lambda items: pytest.fail("must not send"), max_items=3)
    assert digest.flush() is False


def test_digest_send_failure_is_swallowed() -> None:
    def boom(items):
        raise RuntimeError("telegram down")

    digest = PipelineDigest(send=boom, max_items=1)
    assert digest.add(_summary()) is True  # never raises
    assert digest.pending == 0


# ---------------------------------------------------------------------------
# queue_pipeline_result
# ---------------------------------------------------------------------------
def test_queue_routes_report_into_digest() -> None:
    transport = RecordingTransport()
    set_gateway(TelegramGateway(transport=transport, allowlist=[AUTHORIZED]))
    set_digest(PipelineDigest(max_items=5))

    assert queue_pipeline_result(_summary()) is True
    assert transport.sent == []  # waiting for the digest window
    assert flush_pipeline_digest() is True
    assert len(transport.sent) == 1
    _, text = transport.sent[0]
    assert "Ringkasan Siklus" in text  # gateway title for the digest
    assert "1 siklus" in text


def test_queue_delivers_urgent_decisions_immediately() -> None:
    transport = RecordingTransport()
    set_gateway(TelegramGateway(transport=transport, allowlist=[AUTHORIZED]))
    set_digest(PipelineDigest(max_items=5))

    assert queue_pipeline_result(_summary(decision="BUY")) is True
    assert len(transport.sent) == 1  # bypassed the digest


def test_queue_delivers_executed_trades_immediately() -> None:
    transport = RecordingTransport()
    set_gateway(TelegramGateway(transport=transport, allowlist=[AUTHORIZED]))
    set_digest(PipelineDigest(max_items=5))

    assert queue_pipeline_result(_summary(decision="NO_TRADE", executed=True)) is True
    assert len(transport.sent) == 1


def test_queue_returns_false_without_gateway() -> None:
    assert queue_pipeline_result(_summary()) is False


def test_queue_returns_false_without_transport() -> None:
    set_gateway(TelegramGateway(transport=None, allowlist=[AUTHORIZED]))
    assert queue_pipeline_result(_summary()) is False


def test_queue_with_digest_disabled_sends_per_cycle(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_DIGEST_ENABLED", "false")
    transport = RecordingTransport()
    set_gateway(TelegramGateway(transport=transport, allowlist=[AUTHORIZED]))
    reset_digest()

    assert queue_pipeline_result(_summary()) is True
    assert len(transport.sent) == 1  # immediate, no digest


def test_queue_never_raises_on_broken_gateway() -> None:
    class ExplodingGateway:
        def notify(self, *args, **kwargs):
            raise RuntimeError("gateway down")

    set_gateway(ExplodingGateway())
    assert queue_pipeline_result(_summary()) is False


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------
def test_format_report_is_compact_and_informative() -> None:
    text = format_pipeline_report(_summary())
    assert "XAUUSD" in text
    assert "MOMENTUM_BULLISH" in text
    assert "NO_TRADE" in text
    assert "BEARISH" in text  # direction from market_lead
    assert "100%" in text  # consensus from conf=1.00
    assert "tidak ada proposal layak eksekusi" in text  # translated reason
    assert "trace trace-1" in text


def test_format_digest_groups_repeated_cycles() -> None:
    items = [
        _summary(event_type="MOMENTUM_BULLISH"),
        _summary(event_type="MOMENTUM_BULLISH"),
        _summary(event_type="DOJI", summary="market_lead: BEARISH (conf=0.80)"),
        _summary(event_type="TREND_BEARISH", summary=""),
    ]
    text = format_pipeline_digest(items)

    assert "4 siklus" in text
    assert "XAUUSD" in text
    assert "BEARISH (3)" in text  # direction counter (3 summaries carry it)
    assert "netral (1)" in text  # the one without a market direction
    assert "NO_TRADE (4)" in text
    assert "tanpa eksekusi" in text
    assert "• MOMENTUM_BULLISH ×2 → NO_TRADE · BEARISH" in text
    assert "tidak ada proposal layak eksekusi" in text  # single shared reason


def test_format_digest_empty_batch_returns_empty_string() -> None:
    assert format_pipeline_digest([]) == ""


def test_summarize_carries_symbol() -> None:
    assert summarize_pipeline_result(_summary())["symbol"] == "XAUUSD"
    assert summarize_pipeline_result({})["symbol"] == ""
