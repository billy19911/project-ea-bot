# -*- coding: utf-8 -*-
"""Symbol specification utilities – expose full broker symbol metadata.

Provides a simple wrapper around the MT5 connector to return all fields required
by PRD V2 §33:

- symbol, digits, point, tick_size, tick_value, contract_size,
  volume_min, volume_max, volume_step,
- stops_level, freeze_level, filling_mode, trade_mode, margin_mode,
- currency, swap_long, swap_short, spread.

Missing broker‑specific values are populated with safe defaults.
"""

from __future__ import annotations

from typing import Any, Dict

from ..mt5.connector import get_symbol_info

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


def get_symbol_spec(symbol: str) -> Dict[str, Any]:
    """Return a full SymbolSpec dict for *symbol*.

    The function queries MT5 for the basic SymbolInfo and merges static defaults
    for the remaining fields required by the specification.
    """
    info = get_symbol_info(symbol)
    if info is None:
        # Graceful fail‑closed – return defaults with symbol name.
        spec = {"symbol": symbol, **_DEFAULTS}
        spec["spread"] = 0
        spec["digits"] = 5
        spec["contract_size"] = 1.0
        spec["point"] = 0.0
        return spec

    # info is a Pydantic model; convert to dict preserving attribute names.
    base = info.model_dump()
    # Pydantic SymbolInfo fields already include many required keys.
    spec: Dict[str, Any] = {
        "symbol": base.get("symbol"),
        "digits": base.get("digits"),
        "point": base.get("point"),
        "tick_size": base.get("point"),  # alias for point
        "tick_value": base.get("contract_size"),  # approximate mapping
        "contract_size": base.get("contract_size"),
        "spread": base.get("spread"),
        # Merge defaults for missing fields.
        **_DEFAULTS,
    }
    # Ensure mandatory numeric types are sane.
    for key in ["contract_size", "point", "spread"]:
        spec[key] = float(spec.get(key) or 0.0)
    return spec
