# -*- coding: utf-8 -*-
"""Phase 4 — Entry Engine acceptance tests (three deterministic stages).

    Stage A (Setup)   -> SETUP_VALID      : HTF bias + structure + zone + invalidation
    Stage B (Zone)    -> ENTRY_ARMED      : price reaches the validated OB/FVG zone
    Stage C (Trigger) -> ENTRY_TRIGGERED  : deterministic confirmation, then Risk Gate

A zone touch ALONE must never be executable. Stages are surfaced on the cycle
result so the operator can see exactly which stage gated the entry.
"""

from __future__ import annotations

import pytest

from orchestration import entry_stage as entry_stage_mod
from trading import entry_lifecycle as lifecycle_mod
from trading import entry_zone as ez

# Ordering is the contract: A < B < C, and only C may proceed to execution.
STAGE_SETUP = entry_stage_mod.STAGE_SETUP
STAGE_ZONE = entry_stage_mod.STAGE_ZONE
STAGE_TRIGGER = entry_stage_mod.STAGE_TRIGGER


# ── stage vocabulary + ordering ─────────────────────────────────────────
def test_stage_vocabulary_is_explicit() -> None:
    assert entry_stage_mod.STAGE_ORDER == (STAGE_SETUP, STAGE_ZONE, STAGE_TRIGGER)
    assert entry_stage_mod.STAGE_SETUP_VALID == "SETUP_VALID"
    assert entry_stage_mod.STAGE_ENTRY_ARMED == "ENTRY_ARMED"
    assert entry_stage_mod.STAGE_ENTRY_TRIGGERED == "ENTRY_TRIGGERED"


def test_only_trigger_stage_is_executable() -> None:
    assert entry_stage_mod.is_executable(STAGE_TRIGGER) is True
    assert entry_stage_mod.is_executable(STAGE_SETUP) is False
    assert entry_stage_mod.is_executable(STAGE_ZONE) is False


def test_zone_touch_alone_is_not_executable() -> None:
    """EntryRole: a zone touch without trigger confirmation must not be ready."""
    from agents.roles import EntryRole

    out = EntryRole().analyze(
        {
            "setup": {"missing_conditions": [], "direction": "BUY"},
            "zone_touched": True,
            "trigger_confirmed": False,
        }
    )
    assert out.signal != "ENTRY_READY"


# ── lifecycle idempotency (§40/§41) ─────────────────────────────────────
def test_lifecycle_blocks_duplicate_entry_key() -> None:
    manager = lifecycle_mod.EntryLifecycleManager()
    manager.register("setup_1", "XAUUSD", "BUY")
    first = manager.claim_entry("setup_1", trigger_id="trigger_1", candle_ts=1000)
    second = manager.claim_entry("setup_1", trigger_id="trigger_1", candle_ts=1000)
    assert first is True
    assert second is False


def test_lifecycle_allows_new_candle_key() -> None:
    manager = lifecycle_mod.EntryLifecycleManager()
    manager.register("setup_1", "XAUUSD", "BUY")
    a = manager.claim_entry("setup_1", trigger_id="trigger_1", candle_ts=1000)
    b = manager.claim_entry("setup_1", trigger_id="trigger_1", candle_ts=1060)
    assert a is True and b is True


# ── deterministic SL/TP math (§ Stage C) ────────────────────────────────
def test_rr_math_is_consistent() -> None:
    """1.5 ATR SL and 4.5 ATR TP must be exactly 3R."""
    entry, atr = 2500.0, 2.0
    stop = entry - 1.5 * atr
    target = entry + 4.5 * atr
    risk = abs(entry - stop)
    reward = abs(target - entry)
    assert pytest.approx(reward / risk) == 3.0


def test_entry_plan_levels_are_deterministic() -> None:
    plan = ez.EntryPlan(
        direction="BUY",
        entry=2500.0,
        stop_loss=2497.0,
        take_profit=2506.0,
        zone_top=2501.0,
        zone_bottom=2499.0,
        risk_distance=3.0,
        reward_distance=6.0,
        rr=2.0,
    )
    assert plan.risk_distance == pytest.approx(abs(plan.entry - plan.stop_loss))
    assert plan.rr == pytest.approx(plan.reward_distance / plan.risk_distance)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
