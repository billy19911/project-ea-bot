# -*- coding: utf-8 -*-
"""Tests for the Telegram gateway (P0-4 / PRD_V2 §21 & §32.18).

The gateway is a read-only control/communication surface. It must: route
commands to injected providers, refuse unauthorized chats without leaking data,
explain decisions using structured summaries (never raw chain-of-thought),
format alerts, swallow transport failures, and never import execution/MT5
modules.
"""

from __future__ import annotations

import ast
import inspect

from src.telegram import TelegramGateway
from src.telegram import gateway as gateway_module

AUTHORIZED = 12345
UNAUTHORIZED = 99999


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------
class RecordingTransport:
    """In-memory transport capturing sent messages."""

    def __init__(self, fail: bool = False) -> None:
        self.sent: list[tuple[object, str]] = []
        self.fail = fail

    def send_message(self, chat_id: object, text: str) -> None:
        if self.fail:
            raise RuntimeError("telegram network down")
        self.sent.append((chat_id, text))


class CountingProvider:
    """Callable provider that records how many times it was invoked."""

    def __init__(self, value: object) -> None:
        self.value = value
        self.calls = 0

    def __call__(self) -> object:
        self.calls += 1
        return self.value


def make_gateway(**overrides) -> tuple[TelegramGateway, RecordingTransport]:
    transport = RecordingTransport()
    providers = {
        "transport": transport,
        "allowlist": [AUTHORIZED],
        "status_provider": lambda: {"state": "RUNNING", "mode": "paper"},
        "positions_provider": lambda: {"positions": ["EURUSD BUY 0.10"]},
        "risk_provider": lambda: {"exposure": "1.2%", "daily_loss": "0.0%"},
        "decision_trace_provider": lambda: {
            "summary": "No trade: spread too wide.",
            "decision": "NO_TRADE",
            "evidence": ["spread 3.2 pips > threshold 2.0", "news blackout active"],
            "reasoning": "SECRET_INTERNAL_CHAIN_OF_THOUGHT_should_never_be_echoed",
        },
        "review_provider": lambda: {"summary": "Trade #42 WIN PnL=15.00"},
    }
    providers.update(overrides)
    return TelegramGateway(**providers), transport


# ---------------------------------------------------------------------------
# Command routing
# ---------------------------------------------------------------------------
def test_status_routes_to_provider() -> None:
    gateway, _ = make_gateway()
    out = gateway.handle_message(AUTHORIZED, "/status")
    assert "RUNNING" in out
    assert "paper" in out


def test_positions_routes_to_provider() -> None:
    gateway, _ = make_gateway()
    out = gateway.handle_message(AUTHORIZED, "/positions")
    assert "EURUSD BUY 0.10" in out


def test_risk_routes_to_provider() -> None:
    gateway, _ = make_gateway()
    out = gateway.handle_message(AUTHORIZED, "/risk")
    assert "1.2%" in out


def test_review_routes_to_provider() -> None:
    gateway, _ = make_gateway()
    out = gateway.handle_message(AUTHORIZED, "/review")
    assert "Trade #42 WIN" in out


def test_help_lists_commands() -> None:
    gateway, _ = make_gateway()
    out = gateway.handle_message(AUTHORIZED, "/help")
    for cmd in ("/status", "/positions", "/risk", "/why", "/review", "/help"):
        assert cmd in out


def test_unknown_command_returns_help() -> None:
    gateway, _ = make_gateway()
    out = gateway.handle_message(AUTHORIZED, "/nonsense")
    assert "/status" in out


def test_command_parsing_ignores_args() -> None:
    gateway, _ = make_gateway()
    out = gateway.handle_message(AUTHORIZED, "/status   extra args here")
    assert "RUNNING" in out


# ---------------------------------------------------------------------------
# /why — structured summary + evidence, NO chain-of-thought
# ---------------------------------------------------------------------------
def test_why_returns_structured_summary_and_evidence() -> None:
    gateway, _ = make_gateway()
    out = gateway.handle_message(AUTHORIZED, "/why")
    assert "No trade: spread too wide." in out
    assert "NO_TRADE" in out
    assert "spread 3.2 pips" in out


def test_why_never_echoes_internal_reasoning() -> None:
    gateway, _ = make_gateway()
    out = gateway.handle_message(AUTHORIZED, "/why")
    assert "SECRET_INTERNAL_CHAIN_OF_THOUGHT" not in out
    assert "reasoning" not in out.lower()


# ---------------------------------------------------------------------------
# Allowlist
# ---------------------------------------------------------------------------
def test_unauthorized_chat_refused() -> None:
    gateway, _ = make_gateway()
    out = gateway.handle_message(UNAUTHORIZED, "/status")
    assert "Unauthorized" in out


def test_unauthorized_chat_makes_no_provider_calls() -> None:
    status_provider = CountingProvider({"state": "RUNNING"})
    decision_provider = CountingProvider({"summary": "x", "evidence": []})
    gateway, _ = make_gateway(
        status_provider=status_provider,
        decision_trace_provider=decision_provider,
    )

    gateway.handle_message(UNAUTHORIZED, "/status")
    gateway.handle_message(UNAUTHORIZED, "/why")

    assert status_provider.calls == 0
    assert decision_provider.calls == 0


# ---------------------------------------------------------------------------
# notify — formatting + resilience
# ---------------------------------------------------------------------------
def test_notify_formats_proposal() -> None:
    gateway, transport = make_gateway()
    ok = gateway.notify("trade_proposal", {"symbol": "EURUSD", "side": "BUY"})
    assert ok is True
    assert transport.sent
    _, text = transport.sent[0]
    assert "Trade Proposal" in text
    assert "EURUSD" in text
    assert "BUY" in text


def test_notify_formats_execution() -> None:
    gateway, transport = make_gateway()
    gateway.notify("execution", "Filled 0.10 lots @ 1.0850")
    _, text = transport.sent[0]
    assert "Execution" in text
    assert "1.0850" in text


def test_notify_formats_risk_alert() -> None:
    gateway, transport = make_gateway()
    gateway.notify("risk_alert", {"message": "daily loss limit hit"})
    _, text = transport.sent[0]
    assert "Risk Alert" in text
    assert "daily loss limit hit" in text


def test_notify_uses_explicit_chat_id() -> None:
    gateway, transport = make_gateway()
    gateway.notify("system_alert", {"m": "x"}, chat_id=555)
    assert transport.sent[0][0] == 555


def test_notify_swallows_transport_failure() -> None:
    failing = RecordingTransport(fail=True)
    gateway, _ = make_gateway(transport=failing)
    # Must not raise even though the transport blows up.
    ok = gateway.notify("system_alert", {"m": "x"})
    assert ok is False


def test_notify_without_transport_returns_false() -> None:
    gateway, _ = make_gateway(transport=None)
    assert gateway.notify("system_alert", {"m": "x"}) is False


# ---------------------------------------------------------------------------
# Safety invariant — no execution / MT5 imports
# ---------------------------------------------------------------------------
def test_gateway_does_not_import_execution_or_mt5() -> None:
    """The telegram module must not depend on execution/MT5 code paths."""
    source = inspect.getsource(gateway_module)
    assert "import src.execution" not in source
    assert "from src.execution" not in source
    assert "import src.mt5" not in source
    assert "from src.mt5" not in source
    assert "MetaTrader5" not in source


def test_gateway_module_not_importing_mt5_at_runtime() -> None:
    """The gateway module's own imports must not reference MT5/execution."""
    # Inspect the module's import statements rather than the global sys.modules
    # (other test modules may legitimately import MT5).
    names: set[str] = set()
    tree = ast.parse(inspect.getsource(gateway_module))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module)
    assert not any(n.startswith("src.mt5") for n in names)
    assert not any(n.startswith("src.execution") for n in names)
    assert not any(n.startswith("MetaTrader5") for n in names)


def test_gateway_has_no_execution_methods() -> None:
    """The gateway exposes read/notify only — no order placement API."""
    forbidden = ("place_order", "send_order", "execute", "open_position", "close_position")
    for name in forbidden:
        assert not hasattr(TelegramGateway, name), f"unexpected method: {name}"
