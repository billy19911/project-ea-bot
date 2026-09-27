# -*- coding: utf-8 -*-
"""Tests for the per-symbol signal registry (FOKUS #2).

The registry is the authoritative gate that stops the committee from being
re-convened while a signal for a symbol is already live, and stops a failing
execution from re-emitting the identical signal every cycle.
"""

from __future__ import annotations

from orchestration.signal_registry import (
    SignalPhase,
    SignalRegistry,
    get_signal_registry,
    reset_signal_registry,
    set_signal_registry,
)


class _Clock:
    """Controllable monotonic-ish clock for cooldown tests."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


# ---------------------------------------------------------------------------
# Phase transitions
# ---------------------------------------------------------------------------
def test_open_signal_is_pending_and_gates():
    reg = SignalRegistry()
    reg.open_signal("EURUSD", "BUY", confidence=0.8)

    record = reg.get("EURUSD")
    assert record is not None
    assert record.phase == SignalPhase.PENDING
    assert reg.has_active("EURUSD") is True

    convene, reason = reg.should_convene("EURUSD")
    assert convene is False
    assert "masih aktif" in reason


def test_reopening_same_direction_refreshes_not_replaces():
    reg = SignalRegistry()
    first = reg.open_signal("EURUSD", "BUY", confidence=0.5)
    second = reg.open_signal("EURUSD", "BUY", confidence=0.9)

    assert first is second  # same object, refreshed in place
    assert second.confidence == 0.9


def test_mark_open_then_closed_clears_gate():
    reg = SignalRegistry()
    reg.open_signal("EURUSD", "BUY")
    reg.mark_open("EURUSD", ticket=12345)

    assert reg.get("EURUSD").phase == SignalPhase.OPEN
    assert reg.has_active("EURUSD") is True

    reg.mark_closed("EURUSD")
    assert reg.get("EURUSD").phase == SignalPhase.CLOSED
    assert reg.has_active("EURUSD") is False
    convene, _ = reg.should_convene("EURUSD")
    assert convene is True


def test_failed_execution_enters_cooldown():
    clock = _Clock()
    reg = SignalRegistry(clock=clock, failure_cooldown_s=600.0)

    reg.open_signal("EURUSD", "BUY")
    reg.mark_failed("EURUSD", "EXECUTION NOT ARMED")

    assert reg.get("EURUSD").phase == SignalPhase.FAILED
    convene, reason = reg.should_convene("EURUSD")
    assert convene is False
    assert "gagal" in reason

    # After the cooldown elapses the symbol may be analysed again.
    clock.advance(601.0)
    convene, _ = reg.should_convene("EURUSD")
    assert convene is True


def test_skipped_does_not_block_forever():
    reg = SignalRegistry()
    reg.open_signal("EURUSD", "BUY")
    reg.mark_skipped("EURUSD", "ditolak risk gate")

    assert reg.get("EURUSD").phase == SignalPhase.SKIPPED
    # Terminal, not active, and not in failure cooldown → may convene again.
    assert reg.has_active("EURUSD") is False
    convene, _ = reg.should_convene("EURUSD")
    assert convene is True


def test_independent_symbols_do_not_interfere():
    reg = SignalRegistry()
    reg.open_signal("EURUSD", "BUY")
    reg.open_signal("XAUUSD", "SELL")

    assert reg.has_active("EURUSD") is True
    assert reg.has_active("XAUUSD") is True
    reg.mark_closed("EURUSD")
    assert reg.has_active("EURUSD") is False
    assert reg.has_active("XAUUSD") is True


def test_symbol_key_is_case_insensitive():
    reg = SignalRegistry()
    reg.open_signal("eurusd", "BUY")
    assert reg.has_active("EURUSD") is True
    assert reg.get("Eurusd") is not None


def test_snapshot_lists_all():
    reg = SignalRegistry()
    reg.open_signal("EURUSD", "BUY")
    reg.open_signal("XAUUSD", "SELL")
    snap = reg.snapshot()
    assert len(snap) == 2
    assert {s["symbol"] for s in snap} == {"EURUSD", "XAUUSD"}


def test_transition_without_open_is_ignored():
    reg = SignalRegistry()
    # A close for a symbol we never opened must not invent state.
    assert reg.mark_closed("GBPUSD") is None
    assert reg.get("GBPUSD") is None


# ---------------------------------------------------------------------------
# Process-wide singleton
# ---------------------------------------------------------------------------
def test_process_wide_singleton_shared():
    reset_signal_registry()
    a = get_signal_registry()
    b = get_signal_registry()
    assert a is b


def test_set_signal_registry_overrides():
    custom = SignalRegistry()
    set_signal_registry(custom)
    assert get_signal_registry() is custom
    reset_signal_registry()
