# -*- coding: utf-8 -*-
"""Symbol specification abstraction (Phase 1 Hardening).

Centralises *all* broker per-symbol metadata the risk/money-management/execution
layers need, so the risk engine never hardcodes broker assumptions.

Canonical fields (``SymbolSpecification``):

    symbol, asset_class, point, digits, tick_size, tick_value,
    contract_size, min_volume, max_volume, volume_step,
    spread_limit, commission, commission_source

Sources & precedence (highest wins):

    1. BROKER  — live MT5 ``symbol_info`` (authoritative).
    2. CONFIG  — operator/asset-class overrides (``spread_limit``,
                 ``commission``, and the ``_ASSET_CLASS_*`` fallbacks).
    3. UNKNOWN — explicit, recorded, and never silently treated as safe.

The prefix-based asset-class fallback (BTC/XAU/FX) is preserved ONLY as the
last-resort spec for a broker whose symbol is unknown; it is documented as a
fallback and is always labelled ``source="fallback"`` so callers can tell the
difference between a real broker spec and a guess.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from ..mt5.connector import get_symbol_info

__all__ = [
    "SymbolSpecification",
    "get_symbol_specification",
    "get_symbol_spec",
    "classify_asset_class",
    "COMMISSION_SOURCE_BROKER",
    "COMMISSION_SOURCE_CONFIG",
    "COMMISSION_SOURCE_UNKNOWN",
]

# Commission provenance markers (Phase 1 Hardening §3).
COMMISSION_SOURCE_BROKER = "BROKER"
COMMISSION_SOURCE_CONFIG = "CONFIG"
COMMISSION_SOURCE_UNKNOWN = "UNKNOWN"

# Default values for fields not exposed by the current MT5 wrapper.
_DEFAULTS: Dict[str, Any] = {
    "volume_min": 0.01,
    "volume_max": 100.0,
    "volume_step": 0.01,
    "stops_level": 0,
    "freeze_level": 0,
    "filling_mode": "instant",
    "margin_mode": "gross",
    "swap_long": 0.0,
    "swap_short": 0.0,
}

# Emergency asset-class fallback limits. Preserved as a documented fallback —
# NOTE: the permanent architecture is broker ``symbol_info`` + operator CONFIG.
_ASSET_CLASS_SPREAD_LIMIT: Dict[str, float] = {
    "BTC": 8000.0,
    "XAU": 200.0,
    "FX": 5.0,
    "OTHER": 50000.0,
}

# Prefix → asset class mapping (fallback classifier only).
_ASSET_CLASS_PREFIXES = (
    ("XAU", "XAU"),
    ("GOLD", "XAU"),
    ("BTC", "BTC"),
    ("ETH", "BTC"),
)


def classify_asset_class(symbol: str) -> str:
    """Best-effort asset-class classification from a symbol name.

    Fallback only — a real broker spec should drive decisions where available.
    FX is the default when nothing else matches (majors dominate).
    """
    sym = str(symbol or "").upper()
    for prefix, cls in _ASSET_CLASS_PREFIXES:
        if sym.startswith(prefix) or prefix in sym:
            return cls
    # FX majors / crosses: 6-letter alpha pairs like EURUSD.
    if len(sym) >= 6 and sym[:6].isalpha():
        return "FX"
    return "OTHER"


@dataclass(frozen=True)
class SymbolSpecification:
    """Normalised broker symbol metadata consumed by risk/exec/money layers."""

    symbol: str
    asset_class: str = "OTHER"
    point: float = 0.0
    digits: int = 5
    tick_size: float = 0.0
    tick_value: float = 0.0
    contract_size: float = 0.0
    min_volume: float = 0.01
    max_volume: float = 100.0
    volume_step: float = 0.01
    spread_limit: float = 0.0
    commission: float = 0.0
    commission_source: str = COMMISSION_SOURCE_UNKNOWN
    source: str = "fallback"
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "asset_class": self.asset_class,
            "point": self.point,
            "digits": self.digits,
            "tick_size": self.tick_size,
            "tick_value": self.tick_value,
            "contract_size": self.contract_size,
            "min_volume": self.min_volume,
            "max_volume": self.max_volume,
            "volume_step": self.volume_step,
            "spread_limit": self.spread_limit,
            "commission": self.commission,
            "commission_source": self.commission_source,
            "source": self.source,
        }


def _num(value: Any, default: float) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out


def _build_from_broker(
    symbol: str, config: Optional[Dict[str, Any]]
) -> Optional[SymbolSpecification]:
    """Build a spec from live broker symbol_info (+ CONFIG overrides)."""
    info = get_symbol_info(symbol)
    if info is None:
        return None
    base = info.model_dump() if hasattr(info, "model_dump") else dict(info)
    asset_class = classify_asset_class(symbol)

    # Broker commission: MT5 symbol_info generally does NOT expose commission;
    # if a future wrapper provides it we honour it, else CONFIG, else UNKNOWN.
    broker_commission = base.get("commission")
    if broker_commission is not None:
        commission = _num(broker_commission, 0.0)
        commission_source = COMMISSION_SOURCE_BROKER
    elif config is not None and config.get("commission") is not None:
        commission = _num(config.get("commission"), 0.0)
        commission_source = COMMISSION_SOURCE_CONFIG
    else:
        commission = 0.0
        commission_source = COMMISSION_SOURCE_UNKNOWN

    point = _num(base.get("point"), 0.0)
    spec = SymbolSpecification(
        symbol=str(base.get("symbol") or symbol),
        asset_class=asset_class,
        point=point,
        digits=int(_num(base.get("digits"), 5)),
        tick_size=_num(base.get("tick_size"), point) or point,
        tick_value=_num(base.get("tick_value"), 0.0),
        contract_size=_num(base.get("contract_size"), 0.0),
        min_volume=_num(base.get("volume_min"), _DEFAULTS["volume_min"]),
        max_volume=_num(base.get("volume_max"), _DEFAULTS["volume_max"]),
        volume_step=_num(base.get("volume_step"), _DEFAULTS["volume_step"]),
        spread_limit=_resolve_spread_limit(asset_class, config),
        commission=commission,
        commission_source=commission_source,
        source="broker",
        raw=base,
    )
    return spec


def _resolve_spread_limit(asset_class: str, config: Optional[Dict[str, Any]]) -> float:
    """Resolve a spread limit: CONFIG explicit > asset-class fallback."""
    if config is not None and config.get("spread_limit") is not None:
        return _num(config.get("spread_limit"), _ASSET_CLASS_SPREAD_LIMIT.get(asset_class, 50000.0))
    return _ASSET_CLASS_SPREAD_LIMIT.get(asset_class, _ASSET_CLASS_SPREAD_LIMIT["OTHER"])


def _build_fallback(symbol: str, config: Optional[Dict[str, Any]]) -> SymbolSpecification:
    """Build a labelled fallback spec when the broker spec is unavailable.

    Never pretends to be a real broker spec: ``source="fallback"`` and the point
    is 0.0 so downstream fail-closed guards reject rather than invent values.
    """
    asset_class = classify_asset_class(symbol)
    commission = 0.0
    commission_source = COMMISSION_SOURCE_UNKNOWN
    if config is not None and config.get("commission") is not None:
        commission = _num(config.get("commission"), 0.0)
        commission_source = COMMISSION_SOURCE_CONFIG
    return SymbolSpecification(
        symbol=str(symbol),
        asset_class=asset_class,
        point=0.0,
        digits=5,
        tick_size=0.0,
        tick_value=0.0,
        contract_size=0.0,
        min_volume=_num((config or {}).get("volume_min"), _DEFAULTS["volume_min"]),
        max_volume=_num((config or {}).get("volume_max"), _DEFAULTS["volume_max"]),
        volume_step=_num((config or {}).get("volume_step"), _DEFAULTS["volume_step"]),
        spread_limit=_resolve_spread_limit(asset_class, config),
        commission=commission,
        commission_source=commission_source,
        source="fallback",
        raw={"symbol": symbol, **_DEFAULTS},
    )


def get_symbol_specification(
    symbol: str,
    config: Optional[Dict[str, Any]] = None,
) -> SymbolSpecification:
    """Return the best available :class:`SymbolSpecification` for *symbol*.

    Precedence: BROKER symbol_info → fallback (asset-class). A ``config`` dict
    (operator override) may supply ``commission`` and ``spread_limit``; explicit
    CONFIG wins over the asset-class fallback but never over a real broker value
    for volume/point metadata.
    """
    symbol = str(symbol or "")
    if not symbol:
        return _build_fallback("", config)
    broker = _build_from_broker(symbol, config)
    if broker is not None:
        return broker
    return _build_fallback(symbol, config)


def get_symbol_spec(symbol: str) -> Dict[str, Any]:
    """Backward-compatible dict accessor (kept for existing importers).

    Returns the normalised ``SymbolSpecification`` as a plain dict. Fields are
    the canonical ones plus a ``spread`` alias for older callers.
    """
    spec = get_symbol_specification(symbol)
    data = spec.to_dict()
    data["spread"] = data["spread_limit"]
    data["volume_min"] = spec.min_volume
    data["volume_max"] = spec.max_volume
    data["volume_step"] = spec.volume_step
    return data
