# -*- coding: utf-8 -*-
"""Tests for the signal lifecycle (FOKUS #3).

One edit-in-place Telegram message per signal:

* a BUY/SELL cycle approved + executed sends exactly ONE message carrying
  "SIGNAL FINAL" and the ticket,
* a same-direction follow-up never sends a second message,
* a risk-gate REJECTED signal is consumed silently (no message),
* TP1/TP2/TPmax/SL hits edit the SAME message — never a new one,
* ``on_review`` appends the review, marks SELESAI, and clears the state so the
  NEXT signal may open a fresh message,
* a broken transport never raises (fail-safe),
* ``render_signal_message`` is pure and honours hit markers / missing levels.

No network and no MT5 are used. A guard test enforces that the module never
imports execution/MT5 code.
"""

from __future__ import annotations

import ast
import inspect

import pytest
from src.telegram import gateway as gateway_module  # noqa: F401 - sanity import
from src.telegram import signal_lifecycle as signal_lifecycle_module
from src.telegram.gateway import TelegramGateway
from src.telegram.notifier import set_gateway, set_signal_gateway
from src.telegram.signal_lifecycle import (
    SignalLifecycleTracker,
    SignalState,
    get_signal_lifecycle,
    render_signal_message,
    reset_signal_lifecycle,
)

CHAT = "1"


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------
class FakeTransport:
    """Records sends + edits; hands out incrementing message ids."""

    def __init__(self, fail: bool = False) -> None:
        self.sent: list[tuple[object, str]] = []
        self.edits: list[tuple[object, int, str]] = []
        self._next_id = 1000
        self.fail = fail

    def send_message(self, chat_id, text):
        if self.fail:
            raise RuntimeError("telegram down")
        self.sent.append((chat_id, text))
        self._next_id += 1
        return self._next_id

    def edit_message_text(self, chat_id, message_id, text):
        if self.fail:
            raise RuntimeError("telegram down")
        self.edits.append((chat_id, message_id, text))
        return True


@pytest.fixture(autouse=True)
def _reset_state():
    """Clean gateway + lifecycle singletons per test."""
    set_gateway(None)
    set_signal_gateway(None)
    reset_signal_lifecycle()
    yield
    set_gateway(None)
    set_signal_gateway(None)
    reset_signal_lifecycle()


def _gateway(transport) -> TelegramGateway:
    gateway = TelegramGateway(transport=transport, allowlist=[CHAT])
    set_gateway(gateway)
    set_signal_gateway(None)
    return gateway


def _record(**overrides) -> dict:
    base = {
        "decision": "SELL",
        "status": "EXECUTED",
        "risk_approved": True,
        "executed": True,
        "execution_result": {"ticket": 12345678},
        "confidence": 0.86,
        "summary": "market_lead: BEARISH (conf=1.00)",
        "symbol": "XAUUSD",
        "levels": {
            "direction": "SELL",
            "entry": 4284.97,
            "sl": 4294.65,
            "tp1": 4275.29,
            "tp2": 4265.62,
            "tpmax": 4255.94,
        },
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# render_signal_message (pure)
# ---------------------------------------------------------------------------
def test_render_contains_signal_and_plan() -> None:
    state = SignalState(
        symbol="XAUUSD",
        direction="SELL",
        entry=4284.97,
        sl=4294.65,
        tp1=4275.29,
        tp2=4265.62,
        tpmax=4255.94,
        confidence=0.86,
        consensus="100%",
        created_at=1_700_000_000.0,
        status="ENTRY TERBUKA",
        status_detail="#12345678",
        hits={"tp1": False, "tp2": True, "tpmax": False, "sl": False},
        hit_times={"tp2": "22:58"},
        message_ids={"1": 5},
    )
    text = render_signal_message(state)

    assert "🎯 SIGNAL FINAL · XAUUSD SELL" in text
    assert "📐 RENCANA" in text
    assert "Entry : 4284.97" in text
    assert "SL    : 4294.65" in text
    assert "TPmax : 4255.94" in text
    assert "📌 Status: ENTRY TERBUKA #12345678" in text
    assert "✅ TP2 — HIT 22:58" in text
    assert "⏳ TP1" in text


def test_render_sl_marker_is_cross() -> None:
    state = SignalState(
        symbol="EURUSD",
        direction="BUY",
        sl=1.0950,
        entry=1.1000,
        hits={"tp1": False, "tp2": False, "tpmax": False, "sl": True},
        hit_times={"sl": "10:00"},
    )
    text = render_signal_message(state)
    assert "❌ SL — HIT 10:00" in text


def test_render_without_levels_omits_plan() -> None:
    state = SignalState(symbol="XAUUSD", direction="BUY", status="MENUNGGU EKSEKUSI")
    text = render_signal_message(state)
    assert "🎯 SIGNAL FINAL · XAUUSD BUY" in text
    assert "📐 RENCANA" not in text


def test_render_done_adds_review() -> None:
    state = SignalState(
        symbol="XAUUSD",
        direction="BUY",
        status="SELESAI",
        status_detail="WIN · PnL 12.0",
        review_text="WIN · strategy · good entry",
    )
    text = render_signal_message(state)
    assert "🏁 SELESAI" in text
    assert "📝 Review: WIN · strategy · good entry" in text


# ---------------------------------------------------------------------------
# observe_cycle_result
# ---------------------------------------------------------------------------
def test_approved_executed_sends_one_message() -> None:
    transport = FakeTransport()
    _gateway(transport)
    tracker = get_signal_lifecycle()

    assert tracker.observe_cycle_result(_record()) is True
    assert len(transport.sent) == 1
    _, text = transport.sent[0]
    assert "SIGNAL FINAL" in text
    assert "#12345678" in text


def test_same_direction_second_cycle_sends_no_new_message() -> None:
    transport = FakeTransport()
    _gateway(transport)
    tracker = get_signal_lifecycle()

    tracker.observe_cycle_result(_record())
    tracker.observe_cycle_result(_record(confidence=0.99))
    assert len(transport.sent) == 1


def test_rejected_signal_is_silent_but_consumed() -> None:
    transport = FakeTransport()
    _gateway(transport)
    tracker = get_signal_lifecycle()

    assert tracker.observe_cycle_result(_record(risk_approved=False)) is True
    assert transport.sent == []


def test_non_actionable_decision_not_consumed() -> None:
    transport = FakeTransport()
    _gateway(transport)
    tracker = get_signal_lifecycle()

    assert tracker.observe_cycle_result(_record(decision="WAIT")) is False
    assert tracker.observe_cycle_result(_record(decision="NO_TRADE")) is False


def test_empty_symbol_not_consumed() -> None:
    transport = FakeTransport()
    _gateway(transport)
    tracker = get_signal_lifecycle()
    assert tracker.observe_cycle_result(_record(symbol="")) is False


# ---------------------------------------------------------------------------
# observe_price — TP/SL markers edit the SAME message
# ---------------------------------------------------------------------------
def test_observe_price_tp1_edits_once_then_idempotent() -> None:
    transport = FakeTransport()
    _gateway(transport)
    tracker = get_signal_lifecycle()
    tracker.observe_cycle_result(_record())

    # SELL: TP1 hits when price <= 4275.29.
    assert tracker.observe_price("XAUUSD", 4275.0) is True
    assert len(transport.edits) == 1
    assert "✅ TP1" in transport.edits[0][2]

    # Same hit again → no additional edit.
    assert tracker.observe_price("XAUUSD", 4270.0) is False
    assert len(transport.edits) == 1


def test_observe_price_sl_hit_marks_cross() -> None:
    transport = FakeTransport()
    _gateway(transport)
    tracker = get_signal_lifecycle()
    tracker.observe_cycle_result(_record())

    # SELL: SL hits when price >= 4294.65.
    assert tracker.observe_price("XAUUSD", 4295.0) is True
    assert "❌ SL" in transport.edits[-1][2]


def test_observe_price_without_state_is_false() -> None:
    transport = FakeTransport()
    _gateway(transport)
    tracker = get_signal_lifecycle()
    assert tracker.observe_price("NOPE", 100.0) is False


# ---------------------------------------------------------------------------
# on_review
# ---------------------------------------------------------------------------
def test_on_review_appends_review_and_clears_state() -> None:
    transport = FakeTransport()
    _gateway(transport)
    tracker = get_signal_lifecycle()
    tracker.observe_cycle_result(_record())

    assert (
        tracker.on_review(
            {
                "trade_id": "12345678",
                "outcome": "LOSS",
                "root_cause": "strategy",
                "summary": "hit SL",
                "pnl": -25.0,
            }
        )
        is True
    )
    review_edit = transport.edits[-1][2]
    assert "📝 Review: LOSS · strategy · hit SL" in review_edit
    assert "SELESAI" in review_edit
    assert tracker.active_symbols() == []

    # After clearing, a fresh signal opens a NEW message.
    tracker.observe_cycle_result(_record())
    assert len(transport.sent) == 2


# ---------------------------------------------------------------------------
# Fail-safe
# ---------------------------------------------------------------------------
def test_broken_transport_never_raises() -> None:
    transport = FakeTransport(fail=True)
    _gateway(transport)
    tracker = get_signal_lifecycle()

    assert tracker.observe_cycle_result(_record()) is True  # consumed, not raised
    assert tracker.observe_price("XAUUSD", 1.0) in (True, False)


def test_no_transport_is_fail_safe() -> None:
    set_gateway(TelegramGateway(transport=None, allowlist=[CHAT]))
    tracker = get_signal_lifecycle()
    assert tracker.observe_cycle_result(_record()) is True
    assert tracker.active_symbols() == ["XAUUSD"]


def test_gateway_provider_exception_is_swallowed() -> None:
    def boom():
        raise RuntimeError("no gateway")

    tracker = SignalLifecycleTracker(gateway_provider=boom)
    assert tracker.observe_cycle_result(_record()) is True


# ---------------------------------------------------------------------------
# Safety invariant — no execution / MT5 imports
# ---------------------------------------------------------------------------
def test_signal_lifecycle_does_not_import_execution_or_mt5() -> None:
    source = inspect.getsource(signal_lifecycle_module)
    assert "src.execution" not in source
    assert "src.mt5" not in source
    assert "MetaTrader5" not in source

    names: set[str] = set()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module)
    assert not any(n.startswith("src.mt5") for n in names)
    assert not any(n.startswith("src.execution") for n in names)
    assert not any(n.startswith("MetaTrader5") for n in names)
