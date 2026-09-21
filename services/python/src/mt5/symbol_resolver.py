# -*- coding: utf-8 -*-
"""Symbol resolution — auto-detect the broker's symbol naming.

Different brokers/accounts name the same instrument differently:

    XAUUSD, XAUUSDc, XAUUSD247c, XAUUSD.raw, XAUUSDm, XAUUSD-Pro, ...

A hardcoded ``"XAUUSD"`` therefore fails ("0 bars") on many accounts. This
module resolves a *requested base symbol* to the broker's actual symbol name by
scanning the attached terminal's symbol list and picking the best match.

Resolution order (first hit wins), always preferring an exact match:

1. exact match (case-insensitive),
2. base + common suffix/prefix variants (deterministic list),
3. the shortest symbol that starts with the base and is "visually closest",
4. a name-normalised match (strip ``.``, ``-``, ``_``, spaces).

Results are cached per attached terminal (keyed by base symbol) so repeated
lookups are cheap; the cache is cleared whenever the binding changes.
"""

from __future__ import annotations

import logging
import re
import threading
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "resolve_symbol",
    "clear_symbol_cache",
    "candidate_matches",
]

_lock = threading.Lock()
# base (upper) -> resolved broker symbol (upper), scoped by nothing (cleared on
# binding change).
_cache: dict[str, str] = {}

# Common broker decorations, in preference order.
_COMMON_SUFFIXES = (
    "",  # exact
    "c",
    "m",
    "247c",
    ".raw",
    ".r",
    ".pro",
    "-pro",
    "pro",
    "_raw",
    "raw",
    "cash",
    "spot",
    "ecn",
)
_COMMON_PREFIXES = ("", "x", "#")


def _normalise(name: str) -> str:
    """Lowercase and strip separators for fuzzy comparison."""
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _available_symbols() -> list[str]:
    """Return the attached terminal's symbol names (original casing), or []."""
    try:
        from . import connector

        if not connector.is_live_mode():
            return []
        import MetaTrader5 as mt5

        raw = mt5.symbols_get()
        if raw is None:
            return []
        return [str(s.name) for s in raw]
    except Exception:  # noqa: BLE001 - resolution must never hard-fail
        return []


def candidate_matches(base: str, symbols: list[str]) -> list[str]:
    """Return plausible broker symbols for *base*, best match first.

    Comparison is case-insensitive but the RETURNED names preserve the
    broker's original casing — MT5 symbol lookups are case-sensitive.

    Exposed for testing — pure function over the provided symbol list.
    """
    base_up = (base or "").strip().upper()
    if not base_up:
        return []

    # Map upper→original so we can return the broker's exact spelling.
    by_upper: dict[str, str] = {}
    for s in symbols:
        if s and s.upper() not in by_upper:
            by_upper[s.upper()] = s

    seen: set[str] = set()
    out: list[str] = []

    def add(upper_name: str) -> None:
        original = by_upper.get(upper_name)
        if original and original.upper() not in seen:
            seen.add(original.upper())
            out.append(original)

    # 1. Exact match.
    if base_up in by_upper:
        return [by_upper[base_up]]

    # 2. Deterministic suffix/prefix variants.
    for suffix in _COMMON_SUFFIXES:
        for prefix in _COMMON_PREFIXES:
            variant = f"{prefix}{base_up}{suffix}".upper()
            if variant in by_upper:
                add(variant)

    # 3. Starts-with candidates, shortest first (closest to the base).
    prefixed = sorted(
        (u for u in by_upper if u.startswith(base_up)),
        key=lambda u: (len(u), u),
    )
    for u in prefixed:
        add(u)

    # 4. Normalised match (ignore dots/dashes/underscores).
    norm_base = _normalise(base_up)
    norm_matches = sorted(
        (u for u in by_upper if _normalise(u) == norm_base),
        key=lambda u: (len(u), u),
    )
    for u in norm_matches:
        add(u)

    # 5. Normalised starts-with (last resort).
    norm_prefixed = sorted(
        (u for u in by_upper if _normalise(u).startswith(norm_base)),
        key=lambda u: (len(u), u),
    )
    for u in norm_prefixed:
        add(u)

    return out


def resolve_symbol(base: str) -> str:
    """Resolve *base* to the broker's actual symbol name.

    Returns *base* unchanged when resolution is impossible (simulation mode, no
    matches, terminal unreachable) so callers keep their existing behaviour.
    """
    base_up = (base or "").strip().upper()
    if not base_up:
        return base

    with _lock:
        cached = _cache.get(base_up)
    if cached:
        return cached

    symbols = _available_symbols()
    if not symbols:
        return base

    matches = candidate_matches(base_up, symbols)
    if not matches:
        return base

    resolved = matches[0]
    with _lock:
        _cache[base_up] = resolved
    if resolved != base_up:
        logger.info("Symbol resolved: %s -> %s", base_up, resolved)
    return resolved


def clear_symbol_cache() -> None:
    """Drop the resolution cache (call on terminal switch/reconnect)."""
    with _lock:
        _cache.clear()


def cache_info() -> dict[str, Any]:
    """Return a copy of the current resolution cache (debug/health)."""
    with _lock:
        return dict(_cache)
