# -*- coding: utf-8 -*-
"""FIX B test: RiskMonitor emits RISK_* events when thresholds breached.

The supervisor only routes to RiskLead when a RISK_* event reaches the
EventQueue. This test verifies that :class:`RiskMonitor` emits
RISK_DRAWDOWN / RISK_EXPOSURE / RISK_MARGIN events via its ``on_emit`` callback
when account drawdown/exposure/margin cross the configured thresholds.
"""

from __future__ import annotations

from typing import Any

from risk.monitor import RiskMonitor


class _CapturingEmit:
    """Callable capturing (event_type, data) pairs emitted by the monitor."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, event_type: str, data: dict[str, Any]) -> None:
        self.events.append((event_type, data))


def _make_monitor(emit: _CapturingEmit, **kwargs: Any) -> RiskMonitor:
    """Build a RiskMonitor with small thresholds and the given emit callback."""
    defaults: dict[str, Any] = {
        "check_interval_s": 1.0,
        "drawdown_threshold": 0.05,  # 5%
        "exposure_threshold": 0.30,  # 30%
        "margin_threshold": 0.20,  # 20% free margin
        "on_emit": emit,
    }
    defaults.update(kwargs)
    return RiskMonitor(**defaults)


def test_drawdown_breach_emits_risk_drawdown() -> None:
    """Equity well below balance → RISK_DRAWDOWN fired."""
    emit = _CapturingEmit()
    monitor = _make_monitor(emit)
    monitor._get_account_info = (  # type: ignore[assignment]  # noqa: SLF001
        lambda: {
            "equity": 9000.0,
            "balance": 10000.0,
            "margin": 0.0,
            "margin_free": 9000.0,
        }
    )
    monitor._check_once()  # noqa: SLF001 - test hook

    types = [e[0] for e in emit.events]
    assert "RISK_DRAWDOWN" in types
    dd_event = next(e for e in emit.events if e[0] == "RISK_DRAWDOWN")
    assert dd_event[1]["drawdown"] > 0.05
    assert dd_event[1]["threshold"] == 0.05


def test_exposure_breach_emits_risk_exposure() -> None:
    """Margin/equity above threshold → RISK_EXPOSURE fired."""
    emit = _CapturingEmit()
    monitor = _make_monitor(emit)
    monitor._get_account_info = (  # type: ignore[assignment]  # noqa: SLF001
        lambda: {
            "equity": 10000.0,
            "balance": 10000.0,
            "margin": 5000.0,
            "margin_free": 5000.0,
        }
    )
    monitor._check_once()  # noqa: SLF001 - test hook

    types = [e[0] for e in emit.events]
    assert "RISK_EXPOSURE" in types


def test_margin_breach_emits_risk_margin() -> None:
    """Free margin/equity below threshold → RISK_MARGIN fired."""
    emit = _CapturingEmit()
    monitor = _make_monitor(emit)
    monitor._get_account_info = (  # type: ignore[assignment]  # noqa: SLF001
        lambda: {
            "equity": 10000.0,
            "balance": 10000.0,
            "margin": 9000.0,
            "margin_free": 1000.0,
        }
    )
    monitor._check_once()  # noqa: SLF001 - test hook

    types = [e[0] for e in emit.events]
    assert "RISK_MARGIN" in types


def test_no_breach_no_event() -> None:
    """Healthy account → no RISK_* events emitted."""
    emit = _CapturingEmit()
    monitor = _make_monitor(emit)
    monitor._get_account_info = (  # type: ignore[assignment]  # noqa: SLF001
        lambda: {
            "equity": 10000.0,
            "balance": 10000.0,
            "margin": 1000.0,
            "margin_free": 9000.0,
        }
    )
    monitor._check_once()  # noqa: SLF001 - test hook

    assert emit.events == []


def test_mt5_unavailable_is_fail_safe() -> None:
    """Missing MT5 returns {} — monitor must not raise."""
    emit = _CapturingEmit()
    monitor = _make_monitor(emit)
    monitor._get_account_info = lambda: {}  # type: ignore[assignment]  # noqa: SLF001

    monitor._check_once()  # noqa: SLF001 - test hook
    assert emit.events == []
    assert monitor.stats()["checks"] == 1
    assert monitor.stats()["errors"] == 0


def test_monitor_start_stop_lifecycle() -> None:
    """start()/stop()/is_running() behave idempotently."""
    monitor = _make_monitor(_CapturingEmit())
    assert monitor.is_running() is False

    monitor.start()
    assert monitor.is_running() is True

    # Double-start is idempotent (no error, no second thread).
    monitor.start()
    assert monitor.is_running() is True

    monitor.stop()
    assert monitor.is_running() is False

    # Double-stop is idempotent.
    monitor.stop()
    assert monitor.is_running() is False


if __name__ == "__main__":  # pragma: no cover
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
