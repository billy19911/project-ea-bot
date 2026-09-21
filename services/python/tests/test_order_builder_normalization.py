# -*- coding: utf-8 -*-
"""Tests for order volume/price normalisation to broker constraints (audit P1-4)."""

from __future__ import annotations

import pytest

from execution.order_builder import OrderBuilder


def _spec(symbol: str) -> dict:
    return {
        "symbol": symbol,
        "digits": 2,
        "volume_min": 0.01,
        "volume_max": 10.0,
        "volume_step": 0.01,
    }


def test_volume_snapped_to_step() -> None:
    builder = OrderBuilder(symbol_spec_provider=_spec)
    req = builder.build_order_request(
        {"symbol": "XAUUSD", "order_type": "BUY", "volume": 0.123, "price": 2000.567}
    )
    assert req.volume == pytest.approx(0.12, abs=1e-9)
    assert req.price == 2000.57  # rounded to 2 digits


def test_volume_clamped_to_min() -> None:
    builder = OrderBuilder(symbol_spec_provider=_spec)
    req = builder.build_order_request(
        {"symbol": "XAUUSD", "order_type": "BUY", "volume": 0.001, "price": 2000.0}
    )
    assert req.volume == 0.01


def test_volume_clamped_to_max() -> None:
    builder = OrderBuilder(symbol_spec_provider=_spec)
    req = builder.build_order_request(
        {"symbol": "XAUUSD", "order_type": "BUY", "volume": 50.0, "price": 2000.0}
    )
    assert req.volume == 10.0


def test_sl_tp_rounded_to_digits() -> None:
    builder = OrderBuilder(symbol_spec_provider=_spec)
    req = builder.build_order_request(
        {
            "symbol": "XAUUSD",
            "order_type": "BUY",
            "volume": 0.1,
            "price": 2000.0,
            "sl": 1990.123456,
            "tp": 2020.987654,
        }
    )
    assert req.sl == 1990.12
    assert req.tp == 2020.99


def test_no_provider_keeps_values_unchanged() -> None:
    builder = OrderBuilder()
    req = builder.build_order_request(
        {"symbol": "XAUUSD", "order_type": "BUY", "volume": 0.123, "price": 2000.567}
    )
    assert req.volume == 0.123
    assert req.price == 2000.567


def test_spec_provider_error_is_fail_safe() -> None:
    def boom(symbol):
        raise RuntimeError("spec down")

    builder = OrderBuilder(symbol_spec_provider=boom)
    req = builder.build_order_request(
        {"symbol": "XAUUSD", "order_type": "BUY", "volume": 0.123, "price": 2000.567}
    )
    # Values unchanged — the order is not dropped.
    assert req.volume == 0.123
    assert req.price == 2000.567


def test_runtime_order_builder_has_spec_provider() -> None:
    from orchestration.runtime import OrchestrationRuntime

    runtime = OrchestrationRuntime()
    assert runtime.pipeline.order_builder.symbol_spec_provider is not None


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
