# -*- coding: utf-8 -*-
"""Decision State (§9) — three separated decision dimensions.

Per PRD_V2 §9/§10.2 a decision is *not* a single fused label. It is three
orthogonal dimensions:

* ``market_bias`` — directional view of the market.
* ``setup`` — the structural pattern the strategy is trading.
* ``action`` — the concrete order intent.

Invariants (e.g. "BUY requires a non-NEUTRAL bias") are surfaced by
:meth:`DecisionState.validate`, which *returns* a list of violations rather
than raising, so callers can decide how strict to be.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class MarketBias(str, Enum):
    """Directional market bias."""

    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class SetupType(str, Enum):
    """Structural setup being traded."""

    BREAKOUT = "BREAKOUT"
    PULLBACK = "PULLBACK"
    RANGE = "RANGE"
    REVERSAL = "REVERSAL"
    NONE = "NONE"


class ActionType(str, Enum):
    """Concrete action intent."""

    BUY = "BUY"
    SELL = "SELL"
    WAIT = "WAIT"
    NO_TRADE = "NO_TRADE"


_ACTIONABLE = {ActionType.BUY, ActionType.SELL}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _coerce(enum_cls: type[Enum], value: Any) -> Any:
    """Coerce a string value into the given enum, leaving enums untouched."""
    if isinstance(value, enum_cls):
        return value
    return enum_cls(str(value).upper())


@dataclass
class DecisionState:
    """The three-dimension decision output with explainability.

    The constructor never raises on an inconsistent combination; use
    :meth:`validate` to inspect violations.
    """

    decision_id: str
    market_bias: MarketBias = MarketBias.NEUTRAL
    setup: SetupType = SetupType.NONE
    action: ActionType = ActionType.WAIT
    confidence: float = 0.0
    rationale: str = ""
    evidence_bundle_ref: Optional[str] = None
    created_at: str = field(default_factory=_now_iso)
    strategy_version: str = ""
    require_setup: bool = False

    def __post_init__(self) -> None:
        self.market_bias = _coerce(MarketBias, self.market_bias)
        self.setup = _coerce(SetupType, self.setup)
        self.action = _coerce(ActionType, self.action)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self) -> list[str]:
        """Return a list of invariant violations (empty when valid).

        Invariants:

        * A BUY/SELL action requires a non-NEUTRAL ``market_bias``.
        * When ``require_setup`` is enabled, an actionable order requires a
          ``setup`` other than ``NONE``.
        """
        violations: list[str] = []

        if self.action in _ACTIONABLE and self.market_bias == MarketBias.NEUTRAL:
            violations.append(f"Action {self.action.value} requires a non-NEUTRAL market_bias")

        if self.require_setup and self.action in _ACTIONABLE and self.setup == SetupType.NONE:
            violations.append(f"Action {self.action.value} requires a setup other than NONE")

        return violations

    def is_valid(self) -> bool:
        """True when no invariant is violated."""
        return not self.validate()

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialize the decision state."""
        return {
            "decision_id": self.decision_id,
            "market_bias": self.market_bias.value,
            "setup": self.setup.value,
            "action": self.action.value,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "evidence_bundle_ref": self.evidence_bundle_ref,
            "created_at": self.created_at,
            "strategy_version": self.strategy_version,
        }
