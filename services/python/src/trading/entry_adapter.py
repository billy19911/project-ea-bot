# -*- coding: utf-8 -*-
"""Canonical trigger→EntryAssessment adapter (Phase 4.5 §3).
Single direction only::
    TriggerResult (+ Zone + lifecycle status)
        ↓  adapt_trigger_to_assessment()
    EntryAssessment (canonical entry contract)
The Trigger Engine stays the trigger data source; this adapter only SHAPES its
output into the canonical contract. It never invents confirmation: when the
required triggers are not all met (or any blocking condition is present) the
assessment is WAIT_TRIGGER/INVALID/EXPIRED — never ENTRY_READY.
"""
from __future__ import annotations

import time
from typing import Optional

from agents.canonical import EntryAssessment
from trading.entry_config import EntryEngineConfig, TriggerConfig
from trading.entry_zones import Zone
from trading.trigger_engine import TriggerResult

__all__ = ["adapt_trigger_to_assessment"]


def adapt_trigger_to_assessment(
    *,
    setup_id: str,
    symbol: str,
    direction: str,
    zone: Optional[Zone],
    trigger: TriggerResult,
    setup_type: str = "CONTINUATION",
    timeframe_context: str = "M15",
    timeframe_trigger: str = "M5",
    timeframe_micro: str = "M1",
    config: Optional[EntryEngineConfig] = None,
    lifecycle_status: str = "CANDIDATE",
    now_ts: Optional[float] = None,
) -> EntryAssessment:
    """Build a canonical EntryAssessment from trigger evaluation (§3, §23).
    Status rules (fail-closed):
    * lifecycle INVALID/EXPIRED → INVALID/EXPIRED (terminal, never ENTRY_READY).
    * any blocking condition → WAIT_TRIGGER (forbidden wins over met triggers).
    * required triggers all met → ENTRY_READY (trigger_confirmed=True).
    * otherwise → WAIT_TRIGGER with explicit missing_triggers.
    """
    cfg = config or EntryEngineConfig()
    trig_cfg: TriggerConfig = cfg.trigger
    required = list(cfg.required_for(setup_type))
    met = dict(trigger.conditions_met)
    detected = [t for t in required if met.get(t, False)]
    missing = [t for t in required if not met.get(t, False)]
    blocking = list(trigger.blocking)
    now = float(now_ts if now_ts is not None else time.time())
    fresh = (
        trigger.is_fresh(trig_cfg.trigger_max_age_s, now_ts=now)
        if trigger.trigger_time_ts
        else False
    )
    life = str(lifecycle_status or "CANDIDATE").upper()
    if life == "INVALID":
        status, confirmed, reason = "INVALID", False, "setup invalidated"
    elif life == "EXPIRED":
        status, confirmed, reason = "EXPIRED", False, "setup expired"
    elif blocking:
        status, confirmed, reason = "WAIT_TRIGGER", False, f"blocked: {','.join(blocking)}"
    elif required and not missing:
        status, confirmed, reason = "ENTRY_READY", True, f"confirmed: {','.join(detected)}"
    else:
        status, confirmed, reason = "WAIT_TRIGGER", False, f"missing: {','.join(missing)}"
    trig_id = "+".join(detected) if detected else ""
    return EntryAssessment(
        entry_assessment_id=f"ea_{setup_id}",
        setup_id=setup_id,
        symbol=symbol,
        direction=str(direction).upper(),
        entry_zone_type=(zone.zone_type if zone else "ORDER_BLOCK"),
        zone_touched=bool(met.get("zone_touch", False)),
        trigger_required=",".join(required),
        trigger_status=status,
        entry_quality=round(len(detected) / max(len(required), 1), 4),
        invalidation=(zone.invalidation_rule if zone else ""),
        supporting_evidence_refs=[],
        contradicting_evidence_refs=[],
        triggers_detected=detected,
        missing_triggers=missing,
        blocking_conditions=blocking,
        trigger_time_ts=trigger.trigger_time_ts,
        trigger_price=trigger.trigger_price,
        zone_id=(zone.zone_id if zone else ""),
        trigger_id=trig_id,
        trigger_type=trig_id,
        trigger_confirmed=confirmed,
        evaluation_ts=now,
        fresh=fresh if confirmed else True,
        expired=(life == "EXPIRED"),
        invalidated=(life == "INVALID"),
        mitigation_state=(zone.mitigation if zone else "FRESH"),
        retest_count=(zone.touch_count if zone else 0),
        timeframe_context=timeframe_context,
        timeframe_trigger=timeframe_trigger,
        timeframe_micro=timeframe_micro,
        evidence_refs=[e.type for e in trigger.evidence],
        reason_codes=[f"ENTRY_{status}", reason],
    )
