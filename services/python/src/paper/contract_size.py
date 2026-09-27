# -*- coding: utf-8 -*-
"""Contract-size resolution for P&L maths (paper/simulated execution).

Background (P&L sanity fix):
    The paper account and simulated execution hard-coded
    ``contract_size = 100000`` — a *forex* convention. For non-forex symbols
    (XAUUSD, BTCUSD, indices) this inflated P&L by orders of magnitude, which
    produced nonsense review/lesson data (e.g. ``PnL=-100657.51`` for a few
    lots). The live path already resolves the real broker contract size via
    ``market.symbol_spec.get_symbol_spec``; this helper centralises the same
    logic (with a fail-safe default) so the paper path agrees with the live one.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

__all__ = ["resolve_contract_size", "DEFAULT_CONTRACT_SIZE"]

# Used only when the broker spec is unavailable — *not* a hard-coded assumption.
DEFAULT_CONTRACT_SIZE = 100000.0


def resolve_contract_size(symbol: str, default: float = DEFAULT_CONTRACT_SIZE) -> float:
    """Return the broker contract size for ``symbol`` (fail-safe).

    Queries :func:`market.symbol_spec.get_symbol_spec` for the real per-symbol
    contract size. Falls back to ``default`` when the spec is missing/zero so
    P&L never silently becomes zero.
    """
    try:
        from ..market.symbol_spec import get_symbol_spec

        spec = get_symbol_spec(symbol) or {}
        value = float(spec.get("contract_size") or 0.0)
        if value > 0:
            return value
    except Exception as exc:  # noqa: BLE001 - P&L maths must never crash
        logger.debug("Could not resolve contract size for %s: %s", symbol, exc)
    return float(default)
