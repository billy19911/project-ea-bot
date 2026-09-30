# -*- coding: utf-8 -*-
"""Event-driven committee dispatch (Phase 3 §15–§16).
The committee must NOT run every specialist on every M1 candle. This module
classifies events into ANALYSIS LEVELS and decides which work is needed:
    LEVEL 0 — DETERMINISTIC (cheap: price/spread/ATR/freshness — always on)
    LEVEL 1 — SPECIALIST (relevant role(s) for this trigger only)
    LEVEL 2 — MARKET LEAD (synthesize after specialists)
    LEVEL 3 — TARGETED CHALLENGE (only when conflict/uncertainty warrants it)
    LEVEL 4 — ENTRY COMMITTEE (only after a setup candidate exists)
Trigger taxonomy (§15):
    NEW_MARKET_CONTEXT / REGIME_CHANGE / STRUCTURE_BREAK / LIQUIDITY_EVENT /
    SETUP_FORMED / SETUP_INVALIDATED / TRIGGER_APPROACHING / NEWS_EVENT /
    POSITION_EVENT / REVIEW_EVENT
When nothing meaningful changed: ``NO_FULL_COMMITTEE`` — reuse cached role
outputs instead of re-invoking the committee.
"""
from __future__ import annotations

from dataclasses import dataclass, field

__all__ = [
    "EventClass",
    "DispatchDecision",
    "classify_event",
    "LEVEL_NAMES",
]
# Analysis levels (§16).
LEVEL_DETERMINISTIC = 0
LEVEL_SPECIALIST = 1
LEVEL_MARKET_LEAD = 2
LEVEL_CHALLENGE = 3
LEVEL_ENTRY = 4
LEVEL_NAMES = {
    0: "DETERMINISTIC",
    1: "SPECIALIST",
    2: "MARKET_LEAD",
    3: "TARGETED_CHALLENGE",
    4: "ENTRY_COMMITTEE",
}
# Canonical trigger taxonomy (§15).
TRIGGER_NEW_CONTEXT = "NEW_MARKET_CONTEXT"
TRIGGER_REGIME_CHANGE = "REGIME_CHANGE"
TRIGGER_STRUCTURE_BREAK = "STRUCTURE_BREAK"
TRIGGER_LIQUIDITY_EVENT = "LIQUIDITY_EVENT"
TRIGGER_SETUP_FORMED = "SETUP_FORMED"
TRIGGER_SETUP_INVALIDATED = "SETUP_INVALIDATED"
TRIGGER_APPROACHING = "TRIGGER_APPROACHING"
TRIGGER_NEWS_EVENT = "NEWS_EVENT"
TRIGGER_POSITION_EVENT = "POSITION_EVENT"
TRIGGER_REVIEW_EVENT = "REVIEW_EVENT"
# Event-type → (trigger, level, roles). Roles are CANONICAL role ids.
_EVENT_MAP: dict[str, tuple[str, int, tuple[str, ...]]] = {
    # Structure family → structure (+ regime context).
    "STRUCTURE_BREAK": (TRIGGER_STRUCTURE_BREAK, LEVEL_SPECIALIST, ("structure", "regime")),
    "STRUCTURE_ANALYSIS": (TRIGGER_NEW_CONTEXT, LEVEL_SPECIALIST, ("structure",)),
    "BOS": (TRIGGER_STRUCTURE_BREAK, LEVEL_SPECIALIST, ("structure", "regime")),
    "CHOCH": (TRIGGER_STRUCTURE_BREAK, LEVEL_SPECIALIST, ("structure", "regime")),
    "PRICE_ACTION": (TRIGGER_NEW_CONTEXT, LEVEL_SPECIALIST, ("structure", "momentum")),
    "LEVEL_SCAN": (TRIGGER_LIQUIDITY_EVENT, LEVEL_SPECIALIST, ("liquidity", "structure")),
    "MARKET_STRUCTURE": (TRIGGER_STRUCTURE_BREAK, LEVEL_SPECIALIST, ("structure", "regime")),
    # Regime / trend family.
    "TREND_DETECT": (TRIGGER_REGIME_CHANGE, LEVEL_SPECIALIST, ("regime", "momentum")),
    "TREND_BULLISH": (TRIGGER_REGIME_CHANGE, LEVEL_SPECIALIST, ("regime", "momentum")),
    "TREND_BEARISH": (TRIGGER_REGIME_CHANGE, LEVEL_SPECIALIST, ("regime", "momentum")),
    "REGIME_CHANGE": (TRIGGER_REGIME_CHANGE, LEVEL_SPECIALIST, ("regime",)),
    # Liquidity family.
    "LIQUIDITY_SWEEP": (TRIGGER_LIQUIDITY_EVENT, LEVEL_SPECIALIST, ("liquidity", "structure")),
    "STOP_RUN": (TRIGGER_LIQUIDITY_EVENT, LEVEL_SPECIALIST, ("liquidity",)),
    # Volatility family.
    "VOLATILITY_SPIKE": (TRIGGER_NEW_CONTEXT, LEVEL_SPECIALIST, ("volatility",)),
    "VOLATILITY_REGIME": (TRIGGER_NEW_CONTEXT, LEVEL_SPECIALIST, ("volatility", "regime")),
    # News family.
    "NEWS_HIGH_IMPACT": (TRIGGER_NEWS_EVENT, LEVEL_SPECIALIST, ("news",)),
    "NEWS_PROXIMITY": (TRIGGER_NEWS_EVENT, LEVEL_SPECIALIST, ("news",)),
    "MACRO_EVENT": (TRIGGER_NEWS_EVENT, LEVEL_SPECIALIST, ("news",)),
    # Position / review lifecycle.
    "POSITION_OPENED": (TRIGGER_POSITION_EVENT, LEVEL_DETERMINISTIC, ()),
    "POSITION_CLOSED": (TRIGGER_POSITION_EVENT, LEVEL_DETERMINISTIC, ()),
    "TRADE_CLOSE": (TRIGGER_REVIEW_EVENT, LEVEL_DETERMINISTIC, ()),
    "POST_TRADE_REVIEW": (TRIGGER_REVIEW_EVENT, LEVEL_DETERMINISTIC, ()),
    # Entry family → entry committee (Phase 4 consumes this in full).
    "TRIGGER_APPROACHING": (TRIGGER_APPROACHING, LEVEL_ENTRY, ("entry",)),
    "ZONE_TOUCH": (TRIGGER_APPROACHING, LEVEL_ENTRY, ("entry", "structure")),
    "SETUP_FORMED": (TRIGGER_SETUP_FORMED, LEVEL_MARKET_LEAD, ("regime", "structure", "momentum")),
    "SETUP_INVALIDATED": (TRIGGER_SETUP_INVALIDATED, LEVEL_DETERMINISTIC, ()),
    # Phase 4 §38: trigger-evaluation events go to the trigger engine via the
    # entry role (targeted dispatch — never the full committee).
    "TRIGGER_CANDIDATE": (TRIGGER_APPROACHING, LEVEL_ENTRY, ("entry",)),
    "MICRO_BOS": (TRIGGER_APPROACHING, LEVEL_ENTRY, ("entry", "structure")),
    "DISPLACEMENT": (TRIGGER_APPROACHING, LEVEL_ENTRY, ("entry", "momentum")),
    "REJECTION": (TRIGGER_APPROACHING, LEVEL_ENTRY, ("entry", "structure")),
    "CANDLE_CLOSE": (TRIGGER_APPROACHING, LEVEL_ENTRY, ("entry",)),
    "SETUP_EXPIRED": (TRIGGER_SETUP_INVALIDATED, LEVEL_DETERMINISTIC, ()),
}


@dataclass
class EventClass:
    """Classified event: trigger + deepest required analysis level."""

    trigger: str
    level: int
    roles: tuple[str, ...] = ()
    raw_event_type: str = ""

    @property
    def level_name(self) -> str:
        return LEVEL_NAMES.get(self.level, "UNKNOWN")


@dataclass
class DispatchDecision:
    """What the committee should do for one classified event."""

    run_committee: bool
    level: int
    roles: tuple[str, ...] = field(default_factory=tuple)
    reason: str = ""
    use_cache: bool = False

    @property
    def level_name(self) -> str:
        return LEVEL_NAMES.get(self.level, "UNKNOWN")


def classify_event(event_type: str) -> EventClass:
    """Classify a raw event type into (trigger, level, roles).
    Unknown event types map to ``NEW_MARKET_CONTEXT`` with an empty role set —
    i.e. deterministic checks only, no committee. Never raises.
    """
    raw = str(event_type or "UNKNOWN").upper()
    hit = _EVENT_MAP.get(raw)
    if hit is not None:
        trigger, level, roles = hit
        return EventClass(trigger=trigger, level=level, roles=roles, raw_event_type=raw)
    # Prefix fallback: MARKET_* → structure+regime; RISK_* → deterministic.
    if raw.startswith("MARKET_"):
        return EventClass(TRIGGER_NEW_CONTEXT, LEVEL_SPECIALIST, ("structure", "regime"), raw)
    if raw.startswith(("RISK_", "DRAWDOWN_", "MARGIN_")):
        return EventClass(TRIGGER_POSITION_EVENT, LEVEL_DETERMINISTIC, (), raw)
    return EventClass(TRIGGER_NEW_CONTEXT, LEVEL_DETERMINISTIC, (), raw)


def decide_dispatch(
    event_type: str,
    *,
    state_changed: bool = True,
    has_setup: bool = False,
) -> DispatchDecision:
    """Decide whether the full committee is needed for ``event_type`` (§15).
    * Nothing meaningful changed → ``run_committee=False`` (use cache).
    * A setup exists + entry trigger approaching → ENTRY_COMMITTEE level.
    * Otherwise follow the classified level/roles.
    """
    classified = classify_event(event_type)
    if not state_changed:
        return DispatchDecision(
            run_committee=False,
            level=LEVEL_DETERMINISTIC,
            roles=(),
            reason="NO_FULL_COMMITTEE: no meaningful state change (cached evidence reused).",
            use_cache=True,
        )
    if has_setup and classified.trigger == TRIGGER_APPROACHING:
        return DispatchDecision(
            run_committee=True,
            level=LEVEL_ENTRY,
            roles=classified.roles or ("entry",),
            reason="ENTRY_COMMITTEE: setup exists and trigger approaching.",
        )
    if classified.level == LEVEL_DETERMINISTIC and not classified.roles:
        return DispatchDecision(
            run_committee=False,
            level=LEVEL_DETERMINISTIC,
            roles=(),
            reason=f"Deterministic-only trigger {classified.trigger}; no specialists needed.",
            use_cache=False,
        )
    return DispatchDecision(
        run_committee=True,
        level=classified.level,
        roles=classified.roles,
        reason=f"Trigger {classified.trigger} requires {classified.level_name}.",
    )
