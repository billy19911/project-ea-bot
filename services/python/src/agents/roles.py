# -*- coding: utf-8 -*-
"""Canonical committee roles (Phase 3 §3) — evidence-producing specialists.
Each role is a thin, DETERMINISTIC analyzer that emits a normalized
:class:`RoleOutput` carrying canonical :class:`EvidenceItem`s. Roles NEVER vote,
never choose final direction as authority, never set volume, never touch MT5.
Design:
* A role wraps a deterministic analysis function (``analyser(context) -> dict``)
  and normalizes the result into a :class:`RoleOutput` with an EvidenceBundle.
* Existing production specialists (structure/momentum/volatility/news) are
  adapted via :func:`role_from_specialist` so the same evidence contract is
  produced without rewriting them.
* The four new roles with genuine gaps (REGIME, LIQUIDITY, ENTRY, CHALLENGER)
  are implemented here as deterministic logic over the market context.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from .canonical import Conflict, EvidenceBundle, EvidenceItem, EvidenceKind, Freshness

logger = logging.getLogger(__name__)
__all__ = [
    "RoleOutput",
    "CommitteeRole",
    "RegimeRole",
    "StructureRole",
    "LiquidityRole",
    "MomentumRole",
    "VolatilityRole",
    "NewsRole",
    "EntryRole",
    "ChallengerRole",
    "role_from_specialist",
    "CANONICAL_ROLES",
]
# Canonical role ids (§3).
ROLE_REGIME = "regime"
ROLE_STRUCTURE = "structure"
ROLE_LIQUIDITY = "liquidity"
ROLE_MOMENTUM = "momentum"
ROLE_VOLATILITY = "volatility"
ROLE_NEWS = "news"
ROLE_ENTRY = "entry"
ROLE_CHALLENGER = "challenger"
CANONICAL_ROLES = (
    ROLE_REGIME,
    ROLE_STRUCTURE,
    ROLE_LIQUIDITY,
    ROLE_MOMENTUM,
    ROLE_VOLATILITY,
    ROLE_NEWS,
    ROLE_ENTRY,
    ROLE_CHALLENGER,
)
# Challenger outcomes (§3.8).
CHALLENGE_PASSED = "CHALLENGE_PASSED"
CHALLENGE_FAILED = "CHALLENGE_FAILED"
CHALLENGE_UNRESOLVED = "CHALLENGE_UNRESOLVED"


@dataclass
class RoleOutput:
    """Normalized evidence-based specialist output (Phase 3 §4).
    Attributes:
        role: Canonical role id (regime/structure/...).
        signal: Directional interpretation or role-specific state
            (e.g. "BULLISH", "TRENDING", "ENTRY_READY", "UNKNOWN"). NOT a vote.
        confidence_dimensions: {evidence_quality, data_quality, setup_quality}.
        evidence: Canonical evidence bundle (provenance + quality + freshness).
        conflicts: Structurally detected conflicts (may be empty).
        invalidators: Conditions that would invalidate this role's conclusion.
        reason_codes: Machine-readable reason tags.
        data_quality: Coarse quality marker (e.g. "OK"/"UNKNOWN"/"STALE").
        freshness: FRESH / STALE.
        error: True when the role failed (data_quality→UNKNOWN, never faked).
        role_specific: Extra role fields (e.g. challenger outcome).
    """

    role: str
    signal: str = "NEUTRAL"
    confidence_dimensions: dict[str, float] = field(default_factory=dict)
    evidence: EvidenceBundle = field(default_factory=EvidenceBundle)
    conflicts: list[Conflict] = field(default_factory=list)
    invalidators: list[str] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)
    data_quality: str = "OK"
    freshness: Freshness = Freshness.FRESH
    error: bool = False
    role_specific: dict[str, Any] = field(default_factory=dict)

    @property
    def evidence_refs(self) -> list[str]:
        return [item.content for item in self.evidence.items()]

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "signal": self.signal,
            "confidence_dimensions": dict(self.confidence_dimensions),
            "evidence": self.evidence.to_dict(),
            "conflicts": [c.to_dict() for c in self.conflicts],
            "invalidators": list(self.invalidators),
            "reason_codes": list(self.reason_codes),
            "data_quality": self.data_quality,
            "freshness": self.freshness.value,
            "error": self.error,
            "role_specific": dict(self.role_specific),
        }


def _error_output(role: str, reason: str) -> RoleOutput:
    """Fail-safe output for a failed role: UNKNOWN, never a fabricated signal."""
    bundle = EvidenceBundle()
    bundle.add(
        EvidenceItem(
            kind=EvidenceKind.FACT,
            content=f"[ROLE_ERROR] {reason}",
            source=role,
            quality=0.0,
            domain=role,
        )
    )
    return RoleOutput(
        role=role,
        signal="UNKNOWN",
        confidence_dimensions={"evidence_quality": 0.0, "data_quality": 0.0},
        evidence=bundle,
        reason_codes=["ROLE_ERROR"],
        data_quality="UNKNOWN",
        error=True,
    )


class CommitteeRole:
    """Base role wrapping a deterministic analyser into a RoleOutput.
    Subclasses provide ``analyze_impl(context) -> dict`` returning at least
    ``{"signal": str, "evidence": [ {content,...} ]}``. The base class never
    raises: a failure yields an UNKNOWN/error RoleOutput (fail-safe §18).
    """

    role: str = "base"

    def analyze(self, context: dict[str, Any]) -> RoleOutput:
        try:
            raw = self.analyze_impl(context or {})
        except Exception as exc:  # noqa: BLE001 - role failure must never break the cycle
            logger.warning("Role %s failed: %s", self.role, exc)
            return _error_output(self.role, str(exc))
        if not isinstance(raw, dict):
            return _error_output(self.role, "analyser returned a non-dict result")
        return self._normalize(raw, context or {})

    def analyze_impl(self, context: dict[str, Any]) -> dict[str, Any]:  # pragma: no cover
        raise NotImplementedError

    # ------------------------------------------------------------------
    def _normalize(self, raw: dict[str, Any], context: dict[str, Any]) -> RoleOutput:
        bundle = EvidenceBundle()
        signal = str(raw.get("signal", "NEUTRAL") or "NEUTRAL").upper()
        try:
            confidence = float(raw.get("confidence", 0.0) or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = min(1.0, max(0.0, confidence))
        data_quality = str(raw.get("data_quality", "OK") or "OK").upper()
        age = raw.get("age_seconds")
        try:
            age_val = float(age) if age is not None else None
        except (TypeError, ValueError):
            age_val = None
        freshness = (
            str(raw.get("freshness", "fresh")).lower()
            if raw.get("freshness")
            else ("stale" if (age_val is not None and age_val > 300) else "fresh")
        )
        freshness_enum = Freshness.STALE if freshness == "stale" else Freshness.FRESH
        # Primary interpretation item.
        bundle.add(
            EvidenceItem(
                kind=EvidenceKind.INTERPRETATION,
                content=f"{self.role}={signal}",
                source=self.role,
                quality=confidence if data_quality == "OK" else 0.0,
                age_seconds=age_val,
                domain=self.role,
            )
        )
        # Explicit facts.
        for ev in raw.get("evidence") or []:
            if isinstance(ev, dict):
                content = str(ev.get("content") or ev.get("reason") or "").strip()
                if not content:
                    continue
                try:
                    q = float(ev.get("quality", confidence) or confidence)
                except (TypeError, ValueError):
                    q = confidence
                try:
                    kind = EvidenceKind(str(ev.get("kind", "FACT")).upper())
                except ValueError:
                    kind = EvidenceKind.FACT
                bundle.add(
                    EvidenceItem(
                        kind=kind,
                        content=content,
                        source=str(ev.get("source") or self.role),
                        timeframe=str(ev.get("timeframe") or raw.get("timeframe") or ""),
                        quality=min(1.0, max(0.0, q)),
                        age_seconds=age_val,
                        domain=self.role,
                        metric_name=ev.get("metric_name"),
                        metric_value=ev.get("metric_value"),
                    )
                )
            elif isinstance(ev, str) and ev.strip():
                bundle.add(
                    EvidenceItem(
                        kind=EvidenceKind.FACT,
                        content=ev.strip(),
                        source=self.role,
                        quality=confidence,
                        age_seconds=age_val,
                        domain=self.role,
                    )
                )
        evidence_quality = 0.0 if data_quality == "UNKNOWN" else confidence
        dims = {
            "evidence_quality": evidence_quality,
            "data_quality": (
                0.0
                if data_quality == "UNKNOWN"
                else float(raw.get("data_quality_score", 1.0 if data_quality == "OK" else 0.5))
            ),
        }
        for k, v in (raw.get("confidence_dimensions") or {}).items():
            try:
                dims[k] = float(v)
            except (TypeError, ValueError):
                continue
        return RoleOutput(
            role=self.role,
            signal=signal,
            confidence_dimensions=dims,
            evidence=bundle,
            conflicts=list(raw.get("conflicts") or []),
            invalidators=[str(x) for x in (raw.get("invalidators") or [])],
            reason_codes=[str(x) for x in (raw.get("reason_codes") or [])],
            data_quality=data_quality,
            freshness=freshness_enum,
            error=False,
            role_specific=dict(raw.get("role_specific") or {}),
        )


# ----------------------------------------------------------------------
# REGIME (§3.1)
# ----------------------------------------------------------------------
class RegimeRole(CommitteeRole):
    """Classify the market regime: trending/ranging/breakout/compression/..."""

    role = ROLE_REGIME
    ADX_TREND = 25.0
    ADX_RANGE = 18.0

    def analyze_impl(self, context: dict[str, Any]) -> dict[str, Any]:
        adx = _extract_float(context, ("adx", "adx_value"))
        trend = _extract_trend(context)
        atr = _extract_float(context, ("atr",))
        atr_prev = _extract_float(context, ("atr_prev", "prev_atr"))
        if adx is None and not trend:
            return {
                "signal": "UNKNOWN",
                "confidence": 0.0,
                "data_quality": "UNKNOWN",
                "evidence": [],
                "reason_codes": ["NO_REGIME_INPUT"],
            }
        directional = trend in (
            "UP",
            "DOWN",
            "BULLISH",
            "BEARISH",
            "STRONG_BULLISH",
            "STRONG_BEARISH",
        )
        if adx is not None and adx >= self.ADX_TREND and directional:
            regime = "TRENDING"
        elif adx is not None and adx < self.ADX_RANGE and not directional:
            regime = "RANGING"
        elif directional:
            regime = "TRENDING"
        else:
            regime = "BALANCED"
        # Expansion/compression from ATR delta when available.
        if atr is not None and atr_prev is not None and atr_prev > 0:
            ratio = atr / atr_prev
            if ratio >= 1.3:
                regime = "EXPANSION"
            elif ratio <= 0.7:
                regime = "COMPRESSION"
        confidence = 0.6 if adx is not None else 0.4
        return {
            "signal": regime,
            "confidence": confidence,
            "evidence": [
                {
                    "content": f"regime={regime} (adx={adx}, trend={trend or 'NA'})",
                    "metric_name": "adx",
                    "metric_value": adx,
                }
            ],
            "invalidators": [
                "ADX reverses below range threshold",
                "trend flips opposite direction",
            ],
            "reason_codes": [f"REGIME_{regime}"],
        }


# ----------------------------------------------------------------------
# STRUCTURE / MOMENTUM / VOLATILITY / NEWS — adapter from specialists
# ----------------------------------------------------------------------
class _SpecialistRole(CommitteeRole):
    """Adapt an existing specialist agent's ``analyze()`` into a RoleOutput."""

    def __init__(self, role: str, specialist: Any) -> None:
        self.role = role
        self._specialist = specialist

    def analyze_impl(self, context: dict[str, Any]) -> dict[str, Any]:
        raw = self._specialist.analyze(context)
        if not isinstance(raw, dict):
            return {"signal": "UNKNOWN", "confidence": 0.0, "data_quality": "UNKNOWN"}
        out = dict(raw)
        out.setdefault("domain", self.role)
        # Map specialist key_levels / evidence into canonical evidence facts.
        evidence = out.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            evidence = []
            for kl in out.get("key_levels") or []:
                if isinstance(kl, dict) and kl.get("price") is not None:
                    evidence.append(
                        {
                            "content": f"{kl.get('level_type', 'level')}@{kl.get('price')} "
                            f"(strength {kl.get('strength', '?')})",
                            "metric_name": "price",
                            "metric_value": kl.get("price"),
                        }
                    )
            reason = out.get("reasoning") or out.get("reason")
            if reason:
                evidence.append({"content": str(reason)})
            out["evidence"] = evidence
        if str(out.get("signal", "")).upper() == "UNKNOWN":
            out["data_quality"] = "UNKNOWN"
        return out


class StructureRole(_SpecialistRole):
    def __init__(self, specialist: Any) -> None:
        super().__init__(ROLE_STRUCTURE, specialist)


class MomentumRole(_SpecialistRole):
    def __init__(self, specialist: Any) -> None:
        super().__init__(ROLE_MOMENTUM, specialist)


class VolatilityRole(_SpecialistRole):
    def __init__(self, specialist: Any) -> None:
        super().__init__(ROLE_VOLATILITY, specialist)


class NewsRole(_SpecialistRole):
    """News specialist adapted to canonical role.
    UNKNOWN must remain UNKNOWN (§3.6): a news signal that is UNKNOWN or empty
    is reported with ``data_quality='UNKNOWN'`` and NEVER converted to CLEAR.
    """

    def __init__(self, specialist: Any) -> None:
        super().__init__(ROLE_NEWS, specialist)

    def analyze_impl(self, context: dict[str, Any]) -> dict[str, Any]:
        out = super().analyze_impl(context)
        sig = str(out.get("signal", "UNKNOWN")).upper()
        # Normalize the news state vocabulary; UNKNOWN stays UNKNOWN.
        if sig in ("", "NEUTRAL", "NONE"):
            out["signal"] = "UNKNOWN"
            out["data_quality"] = "UNKNOWN"
        if str(out.get("data_quality", "")).upper() == "UNKNOWN":
            out["confidence"] = 0.0
        return out


# ----------------------------------------------------------------------
# LIQUIDITY (§3.2) — new deterministic role (gap)
# ----------------------------------------------------------------------
class LiquidityRole(CommitteeRole):
    """Detect liquidity pools / equal highs-lows / sweep candidates.
    Never converts liquidity detection into an entry signal (§3.2).
    """

    role = ROLE_LIQUIDITY
    EQUAL_TOL = 1e-4

    def analyze_impl(self, context: dict[str, Any]) -> dict[str, Any]:
        highs = list(context.get("highs") or [])
        lows = list(context.get("lows") or [])
        if len(highs) < 6 or len(lows) < 6:
            return {
                "signal": "UNKNOWN",
                "confidence": 0.0,
                "data_quality": "UNKNOWN",
                "evidence": [],
                "reason_codes": ["INSUFFICIENT_DATA"],
            }
        swing_highs = _swings(highs, "high")
        swing_lows = _swings(lows, "low")
        eq_highs = _equal_levels(swing_highs, self.EQUAL_TOL)
        eq_lows = _equal_levels(swing_lows, self.EQUAL_TOL)
        signal = "NEUTRAL"
        evidence: list[dict[str, Any]] = []
        if eq_lows:
            signal = "BUY_SIDE_LIQUIDITY"  # stops below → magnet up
            evidence.append(
                {
                    "content": f"equal lows (sell-side liquidity) at {eq_lows}",
                    "metric_name": "eq_lows",
                    "metric_value": eq_lows[0],
                }
            )
        if eq_highs:
            signal = "SELL_SIDE_LIQUIDITY" if signal == "NEUTRAL" else "BOTH_SIDES"
            evidence.append(
                {
                    "content": f"equal highs (buy-side liquidity) at {eq_highs}",
                    "metric_name": "eq_highs",
                    "metric_value": eq_highs[0],
                }
            )
        return {
            "signal": signal,
            "confidence": 0.5,
            "evidence": evidence or [{"content": "no equal highs/lows detected"}],
            "invalidators": ["liquidity already swept without displacement"],
            "reason_codes": [f"LIQUIDITY_{signal}"],
        }


# ----------------------------------------------------------------------
# ENTRY / TIMING (§3.7) — interface only (Phase 4 adds full trigger engine)
# ----------------------------------------------------------------------
class EntryRole(CommitteeRole):
    """Assess entry timing readiness for a setup candidate.
    Returns ENTRY_READY / WAIT_TRIGGER / INVALID / UNKNOWN. A zone touch alone
    is NOT entry confirmation (§20). Full trigger engine belongs to Phase 4.
    """

    role = ROLE_ENTRY

    def analyze_impl(self, context: dict[str, Any]) -> dict[str, Any]:
        """ENTRY_READY only when the deterministic trigger engine confirms.
        Consumes (in precedence order):
        1. ``trigger_result`` — a TriggerResult dict from the Phase 4 trigger
           engine (authoritative);
        2. legacy ``trigger_confirmed`` bool (caller-asserted, kept for compat).
        A zone touch alone is NEVER confirmation (§20).
        """
        setup = context.get("setup") or {}
        if not isinstance(setup, dict) or not setup:
            return {
                "signal": "UNKNOWN",
                "confidence": 0.0,
                "data_quality": "UNKNOWN",
                "evidence": [],
                "reason_codes": ["NO_SETUP"],
            }
        missing = list(setup.get("missing_conditions") or [])
        zone_touched = bool(context.get("zone_touched", False))
        # Phase 4: deterministic trigger engine result is authoritative.
        trig = context.get("trigger_result") or {}
        required = list(context.get("required_triggers") or setup.get("required_triggers") or [])
        confirmed = bool(context.get("trigger_confirmed", False))
        trig_met: dict[str, bool] = {}
        missing_trig: list[str] = []
        detected: list[str] = []
        blocking: list[str] = []
        if isinstance(trig, dict) and trig.get("conditions_met"):
            trig_met = {str(k): bool(v) for k, v in trig["conditions_met"].items()}
            detected = [k for k, v in trig_met.items() if v]
            if required:
                missing_trig = [t for t in required if not trig_met.get(t, False)]
            blocking = [str(b) for b in (trig.get("blocking") or [])]
        if missing:
            state = "WAIT_TRIGGER"
            reason = f"missing: {', '.join(missing)}"
        elif blocking:
            # Forbidden conditions (§21) block entry even with triggers met.
            state = "WAIT_TRIGGER"
            reason = f"blocked by: {', '.join(blocking)}"
        elif trig_met and required and not missing_trig:
            state = "ENTRY_READY"
            reason = f"triggers confirmed: {', '.join(detected)}"
        elif confirmed and not trig_met:
            # Legacy caller-asserted path (kept for backward compat).
            state = "ENTRY_READY"
            reason = "trigger confirmed (caller-asserted legacy path)"
        elif zone_touched:
            # Zone touch is NOT confirmation (§20).
            state = "WAIT_TRIGGER"
            reason = "zone touched but no confirmation trigger"
        else:
            trigger_status = str(
                context.get("trigger_status") or setup.get("trigger_status") or "MISSING"
            ).upper()
            state = "WAIT_TRIGGER"
            reason = f"trigger_status={trigger_status}"
        return {
            "signal": state,
            "confidence": 0.6 if state == "ENTRY_READY" else 0.3,
            "evidence": [{"content": f"entry={state}: {reason}"}],
            "invalidators": ["price closes beyond setup invalidation"],
            "reason_codes": [f"ENTRY_{state}"],
            "role_specific": {
                "trigger_status": state,
                "zone_touched": zone_touched,
                "triggers_detected": detected,
                "missing_triggers": missing_trig,
                "blocking_conditions": blocking,
                "trigger_time_ts": (
                    trig.get("trigger_time_ts", 0.0) if isinstance(trig, dict) else 0.0
                ),
                "trigger_price": trig.get("trigger_price", 0.0) if isinstance(trig, dict) else 0.0,
            },
        }


# ----------------------------------------------------------------------
# CHALLENGER (§3.8 / §7) — attacks the hypothesis
# ----------------------------------------------------------------------
class ChallengerRole(CommitteeRole):
    """Adversarial reviewer: tries to PROVE the hypothesis wrong.
    Consumes a hypothesis (setup + supporting evidence) and returns
    CHALLENGE_PASSED / CHALLENGE_FAILED / CHALLENGE_UNRESOLVED with the
    strongest counter-arguments. It never votes; it surfaces contradictions.
    """

    role = ROLE_CHALLENGER

    def analyze_impl(self, context: dict[str, Any]) -> dict[str, Any]:
        hypothesis = context.get("hypothesis") or {}
        setup = context.get("setup") or {}
        role_outputs: dict[str, Any] = context.get("role_outputs") or {}
        direction = str(
            context.get("hypothesis_direction")
            or hypothesis.get("direction")
            or setup.get("direction")
            or ""
        ).upper()
        contradictions: list[str] = []
        # 1. Conflicting directional domains vs the hypothesis direction.
        want = (
            "BULLISH"
            if direction in ("BUY", "LONG", "BULLISH")
            else ("BEARISH" if direction in ("SELL", "SHORT", "BEARISH") else "")
        )
        if want:
            for role, out in role_outputs.items():
                sig = str(
                    getattr(out, "signal", "")
                    or (out.get("signal") if isinstance(out, dict) else "")
                ).upper()
                if role in (ROLE_REGIME, ROLE_STRUCTURE, ROLE_LIQUIDITY, ROLE_MOMENTUM):
                    if sig in ("BULLISH", "BEARISH") and sig != want:
                        contradictions.append(f"{role}={sig} contradicts {want} hypothesis")
        # 2. Stale evidence.
        for role, out in role_outputs.items():
            fresh = getattr(out, "freshness", None)
            fresh_val = getattr(fresh, "value", fresh) if fresh is not None else None
            if str(fresh_val).lower() == "stale":
                contradictions.append(f"{role} evidence is stale")
        # 3. Missing invalidation.
        if not (setup.get("invalidation") or context.get("invalidation")):
            contradictions.append("setup has no explicit invalidation level")
        # 4. News unknown is a risk marker.
        news = role_outputs.get(ROLE_NEWS)
        news_sig = getattr(news, "signal", None) if news is not None else None
        if str(news_sig).upper() in ("UNKNOWN", "NONE", ""):
            contradictions.append("news state UNKNOWN — risk not assessable")
        # 5. No supporting evidence at all.
        support = list(
            setup.get("supporting_evidence_refs") or hypothesis.get("supporting_evidence") or []
        )
        if not support:
            contradictions.append("hypothesis has no supporting evidence")
        hard = [
            c
            for c in contradictions
            if "contradicts" in c
            or "no explicit invalidation" in c
            or "no supporting evidence" in c
        ]
        if hard:
            outcome = CHALLENGE_FAILED
        elif contradictions:
            outcome = CHALLENGE_UNRESOLVED
        else:
            outcome = CHALLENGE_PASSED
        bundle = EvidenceBundle()
        for c in contradictions:
            bundle.add(
                EvidenceItem(
                    kind=EvidenceKind.INTERPRETATION,
                    content=c,
                    source=self.role,
                    quality=0.6,
                    domain=self.role,
                )
            )
        if not contradictions:
            bundle.add(
                EvidenceItem(
                    kind=EvidenceKind.INTERPRETATION,
                    content="no decisive counter-evidence found",
                    source=self.role,
                    quality=0.5,
                    domain=self.role,
                )
            )
        return {
            "signal": outcome,
            "confidence": 0.7 if outcome == CHALLENGE_FAILED else 0.4,
            "evidence": [{"content": c} for c in contradictions]
            or [{"content": "challenge found no fatal contradiction"}],
            "reason_codes": [f"CHALLENGE_{outcome}"],
            "role_specific": {"contradictions": contradictions, "outcome": outcome},
        }


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _extract_float(context: dict[str, Any], keys: tuple[str, ...]) -> Optional[float]:
    """Pull the first numeric value from context (direct or market_state)."""
    candidates: list[Any] = []
    for k in keys:
        candidates.append(context.get(k))
    ms = context.get("market_state")
    if ms is not None:
        for k in keys:
            if isinstance(ms, dict):
                candidates.append(ms.get(k))
            candidates.append(getattr(ms, k, None))
    for v in candidates:
        if v is None:
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return None


def _extract_trend(context: dict[str, Any]) -> str:
    for key in ("trend", "direction"):
        v = context.get(key)
        if v:
            return str(v).upper()
    md = context.get("market_data")
    if isinstance(md, dict) and md.get("trend"):
        return str(md["trend"]).upper()
    ms = context.get("market_state")
    if ms is not None:
        t = ms.get("trend") if isinstance(ms, dict) else getattr(ms, "trend", None)
        if t:
            return str(t).upper()
    return ""


def _swings(series: list[float], kind: str) -> list[float]:
    """Simple fractal swing detection over a series."""
    out: list[float] = []
    for i in range(1, len(series) - 1):
        if kind == "high":
            if series[i] >= series[i - 1] and series[i] >= series[i + 1]:
                out.append(float(series[i]))
        else:
            if series[i] <= series[i - 1] and series[i] <= series[i + 1]:
                out.append(float(series[i]))
    return out


def _equal_levels(levels: list[float], tol: float) -> list[float]:
    """Return levels that appear at least twice within ``tol`` (relative)."""
    equal: list[float] = []
    used: set[int] = set()
    for i in range(len(levels)):
        if i in used:
            continue
        for j in range(i + 1, len(levels)):
            if j in used:
                continue
            base = max(abs(levels[i]), 1e-9)
            if abs(levels[i] - levels[j]) / base <= tol:
                equal.append(round(levels[i], 6))
                used.add(i)
                used.add(j)
                break
    return equal


def role_from_specialist(role: str, specialist: Any) -> CommitteeRole:
    """Factory adapting a production specialist into a canonical role."""
    mapping = {
        ROLE_STRUCTURE: StructureRole,
        ROLE_MOMENTUM: MomentumRole,
        ROLE_VOLATILITY: VolatilityRole,
        ROLE_NEWS: NewsRole,
    }
    cls = mapping.get(role)
    if cls is None:
        return _SpecialistRole(role, specialist)
    return cls(specialist)
