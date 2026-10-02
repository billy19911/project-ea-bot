# -*- coding: utf-8 -*-
"""Phase 4 — Entry Engine stage vocabulary (Setup → Zone → Trigger).

Single authoritative source of truth for the three deterministic entry stages
required by the audit plan Phase 4:

    Stage A  SETUP_VALID        HTF bias + regime + structure + valid zone +
                                invalidation. No order yet.
    Stage B  ENTRY_ARMED        Price reached the validated OB/FVG/structure
                                zone. A zone touch ALONE is NOT executable.
    Stage C  ENTRY_TRIGGERED    Deterministic trigger confirmation
                                (rejection / displacement / micro BOS /
                                momentum shift / candle close) + acceptable
                                spread/volatility. Only this stage may be
                                handed to the Risk Gate → Order Builder.

Rules:

* ``SETUP_VALID`` and ``ENTRY_ARMED`` are NOT executable — they are wait states.
* ``ENTRY_TRIGGERED`` is the ONLY executable stage.
* Stage progression is monotonic and never skips a stage.

This module is pure vocabulary/helpers; it never executes, sets volume, or
touches MT5.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "STAGE_SETUP",
    "STAGE_ZONE",
    "STAGE_TRIGGER",
    "STAGE_SETUP_VALID",
    "STAGE_ENTRY_ARMED",
    "STAGE_ENTRY_TRIGGERED",
    "STAGE_ORDER",
    "stage_for_zone_state",
    "is_executable",
    "describe",
]

# Coarse stage ids.
STAGE_SETUP = "SETUP"
STAGE_ZONE = "ZONE"
STAGE_TRIGGER = "TRIGGER"

# Explicit stage outcomes surfaced to the operator/telemetry.
STAGE_SETUP_VALID = "SETUP_VALID"
STAGE_ENTRY_ARMED = "ENTRY_ARMED"
STAGE_ENTRY_TRIGGERED = "ENTRY_TRIGGERED"

#: Ordered stages. Progression is monotonic — never skip a stage.
STAGE_ORDER = (STAGE_SETUP, STAGE_ZONE, STAGE_TRIGGER)

#: The single executable stage.
_EXECUTABLE_STAGE = STAGE_TRIGGER


def is_executable(stage: str) -> bool:
    """True only for the TRIGGER stage (Stage C).

    Fail-closed: an unknown/empty stage is never executable.
    """
    return str(stage or "").strip().upper() == _EXECUTABLE_STAGE


def stage_for_zone_state(
    *,
    setup_valid: bool,
    at_zone: bool,
    trigger_confirmed: bool,
) -> str:
    """Map the deterministic A/B/C inputs to the coarse stage id.

    Ordering matters: a confirmed trigger implies the earlier stages held.
    """
    if trigger_confirmed and setup_valid and at_zone:
        return STAGE_TRIGGER
    if at_zone and setup_valid:
        return STAGE_ZONE
    if setup_valid:
        return STAGE_SETUP
    return STAGE_SETUP


def describe(stage: str) -> dict[str, Any]:
    """Return the explicit outcome label for a coarse stage id."""
    mapping = {
        STAGE_SETUP: STAGE_SETUP_VALID,
        STAGE_ZONE: STAGE_ENTRY_ARMED,
        STAGE_TRIGGER: STAGE_ENTRY_TRIGGERED,
    }
    coarse = str(stage or "").strip().upper()
    return {
        "stage": coarse,
        "outcome": mapping.get(coarse, STAGE_SETUP_VALID),
        "executable": is_executable(coarse),
    }
