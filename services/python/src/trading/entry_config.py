# -*- coding: utf-8 -*-
"""Entry engine configuration (Phase 4 §46) — centralized thresholds.

Single source of truth for OB/FVG detection, trigger evaluation, zone
lifecycle, spread/session/MTF policy. Follows the repository's plain-dataclass
config pattern (cf. agents/debate.DebateConfig). No thresholds are scattered
in detector code; every detector takes a config object.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = [
    "ZoneConfig",
    "TriggerConfig",
    "TimeframeConfig",
    "EntryEngineConfig",
    "DEFAULT_ENTRY_ENGINE_CONFIG",
]


@dataclass(frozen=True)
class ZoneConfig:
    """OB/FVG zone detection + lifecycle policy (§6–§11, §26–§29)."""

    # OB detection (§6–§8).
    ob_lookback: int = 20
    # Minimum displacement (in ATR multiples) for an OB to be структурно valid.
    ob_min_displacement_atr: float = 0.5
    # FVG detection (§9–§10).
    fvg_lookback: int = 15
    # Minimum gap size in ATR multiples; smaller gaps are noise, not setups.
    fvg_min_gap_atr: float = 0.1
    # Zone lifecycle (§26–§29).
    # Setup expiry in seconds after creation (0 = no time expiry).
    setup_expiry_s: float = 4 * 3600.0
    # Max zone touches before the zone is considered exhausted.
    max_retests: int = 1
    # Touch tolerance as a fraction of zone height (0 = exact band).
    touch_tolerance_frac: float = 0.0


@dataclass(frozen=True)
class TriggerConfig:
    """Trigger confirmation policy (§14–§25, §30–§33)."""

    # Required trigger names for ENTRY_READY (configurable per setup, §20).
    # Supported: zone_touch, rejection, displacement, micro_bos,
    #            momentum_shift, candle_close.
    required_triggers: tuple[str, ...] = ("zone_touch", "rejection", "candle_close")
    # Optional confirmations (descriptive only, never authoritative alone).
    optional_triggers: tuple[str, ...] = ("displacement", "momentum_shift")
    # Forbidden conditions block entry (§21).
    forbidden_conditions: tuple[str, ...] = (
        "spread_too_wide",
        "structure_invalidated",
        "news_high_impact",
    )
    # Rejection (§15): min wick/body ratio + close-back requirement.
    rejection_min_wick_ratio: float = 0.4
    # Displacement (§16): min body/ATR and range/ATR.
    displacement_min_body_atr: float = 0.5
    displacement_min_range_atr: float = 0.8
    # Micro BOS (§17): swing lookback on the trigger timeframe.
    micro_bos_lookback: int = 5
    # Momentum shift (§18): EMA fast/slow periods on trigger TF.
    momentum_fast: int = 8
    momentum_slow: int = 21
    # Candle close (§19): when True, ENTRY_READY requires a CLOSED candle.
    require_candle_close: bool = True
    # Trigger freshness (§25): max age in seconds before TRIGGER_EXPIRED.
    trigger_max_age_s: float = 15 * 60.0
    # Spread filter (§30): max spread in ATR multiples at trigger time.
    max_spread_atr: float = 0.25
    # Volatility filter (§31): trigger ATR must be within [min,max] multiple
    # of the context ATR; (0,0) disables.
    atr_min_mult: float = 0.0
    atr_max_mult: float = 0.0


@dataclass(frozen=True)
class TimeframeConfig:
    """Context vs trigger timeframe mapping (§11)."""

    context_timeframe: str = "M15"
    trigger_timeframe: str = "M5"
    micro_timeframe: str = "M1"


@dataclass(frozen=True)
class EntryEngineConfig:
    """Top-level entry engine configuration (§46)."""

    zone: ZoneConfig = field(default_factory=ZoneConfig)
    trigger: TriggerConfig = field(default_factory=TriggerConfig)
    timeframes: TimeframeConfig = field(default_factory=TimeframeConfig)
    # Per-setup required-trigger overrides: {setup_type: (triggers...)}.
    # Falls back to trigger.required_triggers when absent.
    setup_trigger_overrides: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def required_for(self, setup_type: str) -> tuple[str, ...]:
        """Required triggers for a setup type (override or default)."""
        override = self.setup_trigger_overrides.get(str(setup_type or "").upper())
        if override:
            return tuple(override)
        return tuple(self.trigger.required_triggers)


DEFAULT_ENTRY_ENGINE_CONFIG = EntryEngineConfig()
