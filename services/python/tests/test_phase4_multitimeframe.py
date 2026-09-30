# -*- coding: utf-8 -*-
"""Phase 4 — multi-timeframe tests (§11, TEST 12/13)."""

from __future__ import annotations

import pytest

from src.trading.entry_config import EntryEngineConfig, TimeframeConfig, TriggerConfig
from src.trading.trigger_engine import evaluate_triggers


def _series(n=30, start=100.0, step=0.4):
    o = [start + i * step for i in range(n)]
    h = [x + 0.5 for x in o]
    lo = [x - 0.5 for x in o]
    c = [x + 0.3 for x in o]
    return o, h, lo, c


def test_context_bullish_trigger_unconfirmed_waits():
    """M15 bullish + M5 bullish attempt but M1 not confirmed → WAIT (no entry)."""
    o, h, lo, c = _series()
    # Trigger TF evaluated on flat micro bars: no BOS/displacement/rejection.
    flat = [100.0] * 10
    r = evaluate_triggers(
        direction="LONG",
        zone_top=200.0,
        zone_bottom=199.0,
        opens=flat,
        highs=[x + 0.1 for x in flat],
        lows=[x - 0.1 for x in flat],
        closes=flat,
        atr=1.0,
        timeframe="M1",
        is_closed=True,
    )
    assert r.conditions_met["rejection"] is False
    assert r.conditions_met["displacement"] is False
    assert r.conditions_met["micro_bos"] is False


def test_contradictory_timeframes_do_not_average():
    """M15 bullish vs M5 bearish invalidation → structure_invalidated blocks."""
    o, h, lo, c = _series(step=-0.6)  # bearish trigger series
    r = evaluate_triggers(
        direction="LONG",
        zone_top=c[-1] - 1,
        zone_bottom=c[-1] - 2,
        opens=o,
        highs=h,
        lows=lo,
        closes=c,
        atr=0.5,
        is_closed=True,
        structure_invalidated=True,
    )
    assert "structure_invalidated" in r.blocking


def test_timeframe_config_defaults_and_override():
    cfg = EntryEngineConfig()
    assert cfg.timeframes.context_timeframe == "M15"
    assert cfg.timeframes.trigger_timeframe == "M5"
    assert cfg.timeframes.micro_timeframe == "M1"
    custom = EntryEngineConfig(timeframes=TimeframeConfig("H1", "M15", "M5"))
    assert custom.timeframes.context_timeframe == "H1"


def test_required_triggers_configurable_per_setup():
    cfg = EntryEngineConfig(
        trigger=TriggerConfig(required_triggers=("zone_touch", "micro_bos")),
        setup_trigger_overrides={"BREAKOUT": ("zone_touch", "displacement")},
    )
    assert cfg.required_for("BREAKOUT") == ("zone_touch", "displacement")
    assert cfg.required_for("PULLBACK") == ("zone_touch", "micro_bos")
    assert cfg.required_for("UNKNOWN_TYPE") == ("zone_touch", "micro_bos")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
