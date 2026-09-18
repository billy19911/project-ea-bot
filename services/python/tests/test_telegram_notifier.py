# -*- coding: utf-8 -*-
"""Tests for the Telegram notifier + pipeline notification wiring (Phase 5).

Covers:

* ``summarize_pipeline_result`` — compact, honest summary of a pipeline record,
* ``notify_pipeline_result`` — fail-safe delivery through the shared gateway,
* ``build_gateway_from_env`` — env-driven gateway construction (no token = off),
* the ``result_hook`` on ``TradingPipeline`` — every cycle result is offered to
  the hook exactly once, and a broken hook never breaks the cycle,
* the runtime wiring — ``OrchestrationRuntime`` built pipelines notify through
  the shared gateway singleton.

No network and no MT5 are used.
"""

from __future__ import annotations

import pytest

from src.orchestration.pipeline import TradingPipeline
from src.orchestration.runtime import OrchestrationRuntime
from src.telegram import TelegramGateway
from src.telegram.notifier import (
    build_gateway_from_env,
    notify_pipeline_result,
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


class ExplodingGateway:
    """Gateway whose notify always raises (to prove fail-safety)."""

    def notify(self, *args, **kwargs) -> bool:
        raise RuntimeError("gateway down")


class _NeutralSupervisor:
    """Supervisor stub that returns a proposal-less NEUTRAL synthesis."""

    def analyze(self, context):
        return {
            "overall_signal": "NEUTRAL",
            "overall_confidence": 0.0,
            "agent_results": {},
            "summary": "stub summary",
        }


class _NeverCalledGate:
    """Risk gate stub that must never be invoked (no actionable proposal)."""

    def validate_proposal(self, *args):  # pragma: no cover - must not run
        raise AssertionError("risk gate should not be called for a NEUTRAL synthesis")


def _record(**overrides) -> dict:
    base = {
        "event_id": "evt-1",
        "event_type": "BREAKOUT",
        "decision": "BUY",
        "status": "BLOCKED",
        "confidence": 0.72,
        "summary": "market_lead: BULLISH (conf=0.70); risk_lead: NEUTRAL (conf=0.55)",
        "risk_reason": "spread too wide",
        "executed": False,
        "trace_id": "trace-9",
    }
    base.update(overrides)
    return base


@pytest.fixture(autouse=True)
def _reset_gateway():
    """Give each test a clean gateway singleton (unbuilt)."""
    set_gateway(None)
    yield
    set_gateway(None)


# ---------------------------------------------------------------------------
# summarize_pipeline_result
# ---------------------------------------------------------------------------
def test_summarize_contains_required_fields() -> None:
    summary = summarize_pipeline_result(_record())
    assert summary["event_type"] == "BREAKOUT"
    assert summary["decision"] == "BUY"
    assert summary["status"] == "BLOCKED"
    assert summary["confidence"] == 0.72
    assert summary["executed"] is False
    assert "BULLISH" in summary["summary"]
    assert summary["risk_reason"] == "spread too wide"


def test_summarize_is_fail_safe_on_empty_record() -> None:
    summary = summarize_pipeline_result({})
    assert summary["decision"] == ""
    assert summary["confidence"] == 0.0
    assert summary["executed"] is False


def test_summarize_truncates_long_summary() -> None:
    summary = summarize_pipeline_result(_record(summary="x" * 1000))
    assert len(summary["summary"]) <= 240


# ---------------------------------------------------------------------------
# notify_pipeline_result
# ---------------------------------------------------------------------------
def test_notify_sends_via_gateway() -> None:
    transport = RecordingTransport()
    gateway = TelegramGateway(transport=transport, allowlist=[AUTHORIZED])

    ok = notify_pipeline_result(_record(), gateway=gateway)

    assert ok is True
    assert transport.sent
    chat_id, text = transport.sent[0]
    assert str(chat_id) == str(AUTHORIZED)
    assert "Market Analysis" in text
    assert "BUY" in text


def test_notify_returns_false_without_transport() -> None:
    gateway = TelegramGateway(transport=None, allowlist=[AUTHORIZED])
    assert notify_pipeline_result(_record(), gateway=gateway) is False


def test_notify_returns_false_without_allowlist() -> None:
    transport = RecordingTransport()
    gateway = TelegramGateway(transport=transport, allowlist=[])
    assert notify_pipeline_result(_record(), gateway=gateway) is False
    assert transport.sent == []


def test_notify_never_raises_when_gateway_breaks() -> None:
    assert notify_pipeline_result(_record(), gateway=ExplodingGateway()) is False


def test_notify_uses_singleton_when_no_gateway_given() -> None:
    transport = RecordingTransport()
    set_gateway(TelegramGateway(transport=transport, allowlist=[AUTHORIZED]))
    assert notify_pipeline_result(_record()) is True
    assert transport.sent


# ---------------------------------------------------------------------------
# build_gateway_from_env
# ---------------------------------------------------------------------------
def test_build_gateway_from_env_without_token_is_disabled(monkeypatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_ALLOWED_CHAT_IDS", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_IDS", raising=False)

    gateway = build_gateway_from_env()
    assert gateway.transport is None


def test_build_gateway_from_env_with_token_builds_transport(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:ABC")
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "111,222")

    gateway = build_gateway_from_env()
    assert gateway.transport is not None
    assert gateway.allowlist == {"111", "222"}


# ---------------------------------------------------------------------------
# TradingPipeline.result_hook
# ---------------------------------------------------------------------------
def test_pipeline_result_hook_receives_each_result_once() -> None:
    seen: list = []
    pipeline = TradingPipeline(
        supervisor=_NeutralSupervisor(),
        risk_gate=_NeverCalledGate(),
        result_hook=seen.append,
    )

    result = pipeline.run({"event_type": "BREAKOUT", "symbol": "EURUSD"})

    assert len(seen) == 1
    assert seen[0] is result
    assert result.decision == "WAIT"


def test_pipeline_result_hook_failure_never_breaks_cycle() -> None:
    def boom(result):  # pragma: no cover - invoked, but must be swallowed
        raise RuntimeError("hook down")

    pipeline = TradingPipeline(
        supervisor=_NeutralSupervisor(),
        risk_gate=_NeverCalledGate(),
        result_hook=boom,
    )

    result = pipeline.run({"event_type": "BREAKOUT", "symbol": "EURUSD"})
    assert result.decision == "WAIT"


def test_pipeline_without_hook_behaves_unchanged() -> None:
    pipeline = TradingPipeline(supervisor=_NeutralSupervisor(), risk_gate=_NeverCalledGate())
    result = pipeline.run({"event_type": "BREAKOUT", "symbol": "EURUSD"})
    assert result.decision == "WAIT"


def test_pipeline_result_exposes_event_type_confidence_summary() -> None:
    pipeline = TradingPipeline(supervisor=_NeutralSupervisor(), risk_gate=_NeverCalledGate())
    result = pipeline.run({"event_type": "BREAKOUT", "symbol": "EURUSD"})

    assert result.event_type == "BREAKOUT"
    assert result.confidence == 0.0
    assert result.summary == "stub summary"

    payload = result.to_dict()
    assert payload["event_type"] == "BREAKOUT"
    assert payload["confidence"] == 0.0
    assert payload["summary"] == "stub summary"


# ---------------------------------------------------------------------------
# Runtime wiring — a cycle result is delivered to the shared gateway
# ---------------------------------------------------------------------------
def test_runtime_cycle_triggers_notification() -> None:
    transport = RecordingTransport()
    set_gateway(TelegramGateway(transport=transport, allowlist=[AUTHORIZED]))

    runtime = OrchestrationRuntime()
    runtime.run_cycle({"event_type": "BREAKOUT", "symbol": "EURUSD"})

    assert transport.sent, "expected a pipeline report to be delivered"
    _, text = transport.sent[0]
    assert "Market Analysis" in text


def test_runtime_cycle_survives_broken_gateway() -> None:
    set_gateway(ExplodingGateway())

    runtime = OrchestrationRuntime()
    record = runtime.run_cycle({"event_type": "BREAKOUT", "symbol": "EURUSD"})

    assert record["status"] in {"WAIT", "NO_TRADE", "BLOCKED", "ERROR", "EXECUTED"}
