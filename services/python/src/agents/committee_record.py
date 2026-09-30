# -*- coding: utf-8 -*-
"""Committee cycle record + natural human-facing narrative (TASK 03).

This module has two responsibilities, both deterministic and analysis-only:

1. :func:`build_committee_record` — assemble the canonical structured record
   every committee cycle MUST persist:

   ``event, agents_called, agents_skipped, agent_outputs, conflicts,
   evidence, supervisor_reasoning, decision, confidence, signal_id``.

2. :func:`render_committee_narrative` — turn that structured record into a
   NATURAL human-facing message (the "OVERWATCH / Structure sees ..." style),
   never a canned template such as ``"Konsensus: BUY (...)"``.

Design rules:

* The machine representation (the structured record) is the source of truth
  and stays deterministic — same inputs yield the same output.
* The narrative is DERIVED from real agent evidence (signal + reasoning); it
  never invents evidence and never adds fake conversational fluff.
* No execution / MT5 imports. This module cannot create an order.
"""

from __future__ import annotations

from typing import Any, Optional

__all__ = [
    "build_committee_record",
    "render_committee_narrative",
]

# Human callsigns for the committee bubbles (mirror the UI/backend display
# names so the narrative reads like the actual team, not routing keys).
_CALLSIGNS: dict[str, str] = {
    "supervisor": "OVERWATCH",
    "market_lead": "MARKET-LEAD",
    "risk_lead": "RISK-LEAD",
    "review_lead": "REVIEW-LEAD",
    "technical_analyst": "TREND-SCAN",
    "structure_analyst": "STRUCTURE",
    "momentum_analyst": "MOMENTUM",
    "volatility_analyst": "VOLATILITY",
    "news_sentiment": "NEWS",
    "fundamental_analyst": "MACRO",
    "post_trade_review": "REVIEW",
}

# Observable label for a specialist whose signal is not directional.
_SIGNAL_PHRASE: dict[str, str] = {
    "BULLISH": "sees the setup as bullish",
    "STRONG_BULLISH": "sees a strong bullish setup",
    "BUY": "supports a long entry",
    "BEARISH": "sees the setup as bearish",
    "STRONG_BEARISH": "sees a strong bearish setup",
    "SELL": "supports a short entry",
    "NEUTRAL": "has no directional preference",
}


def _callsign(name: str) -> str:
    """Human callsign for a routing name (de-snaked fallback)."""
    if not name:
        return "AGENT"
    if name in _CALLSIGNS:
        return _CALLSIGNS[name]
    return name.replace("_", " ").upper()


def _lead_has_speaking_specialist(
    outputs: dict[str, Any], lead_name: str, specialist_names: set[str]
) -> bool:
    """True when this lead has at least one speaking specialist present."""
    lead_out = outputs.get(lead_name)
    if not isinstance(lead_out, dict):
        return False
    specs = lead_out.get("specialist_results") or {}
    for spec_name in specs:
        if spec_name in specialist_names:
            return True
    return False


def _as_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _direction_of(signal: Any) -> str:
    """Map a raw signal to BULLISH / BEARISH / NEUTRAL."""
    upper = str(signal or "").upper()
    if "BULL" in upper or upper in ("BUY", "LONG"):
        return "BULLISH"
    if "BEAR" in upper or upper in ("SELL", "SHORT"):
        return "BEARISH"
    return "NEUTRAL"


def _agent_reasoning(output: Any) -> str:
    """Extract the most informative human-readable reasoning line.

    Prefers a concrete, evidence-carrying line and skips boilerplate headers
    (e.g. ``"Regime pasar terdeteksi: ..."``) — so the narrative reads like a
    statement of evidence, not a machine summary.
    """
    if not isinstance(output, dict):
        return ""
    raw = output.get("reasoning", output.get("reasons", ""))
    if isinstance(raw, (list, tuple)):
        parts = [str(r).strip() for r in raw if str(r).strip()]
    else:
        parts = [str(raw).strip()] if str(raw).strip() else []
    if not parts:
        return ""
    boilerplate = ("regime pasar terdeteksi", "regime:", "spesialis tidak dipanggil")
    # Prefer the FIRST line that is not boilerplate; fall back to the first.
    for line in parts:
        low = line.lower()
        if not any(marker in low for marker in boilerplate):
            return line
    return parts[0]


def collect_conflicts(agent_outputs: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Return directional conflicts across the contributing agents.

    A conflict is any pair of agents whose signals point in opposite
    directions. Deterministic ordering (by name pairs).
    """
    conflicts: list[dict[str, Any]] = []
    items = [
        (name, _direction_of((out or {}).get("signal")))
        for name, out in (agent_outputs or {}).items()
        if isinstance(out, dict)
    ]
    for i, (name_a, dir_a) in enumerate(items):
        if dir_a == "NEUTRAL":
            continue
        for name_b, dir_b in items[i + 1 :]:
            if dir_b == "NEUTRAL":
                continue
            if dir_a != dir_b:
                conflicts.append(
                    {
                        "between": sorted([name_a, name_b]),
                        "detail": f"{_callsign(name_a)}={dir_a} vs {_callsign(name_b)}={dir_b}",
                    }
                )
    return conflicts


def collect_evidence(agent_outputs: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Collect a bounded, deterministic list of evidence items per agent."""
    evidence: list[dict[str, Any]] = []
    for name, out in (agent_outputs or {}).items():
        if not isinstance(out, dict):
            continue
        for item in out.get("evidence") or []:
            if isinstance(item, dict):
                content = str(
                    item.get("content") or item.get("reason") or item.get("reasoning") or ""
                ).strip()
            else:
                content = str(item or "").strip()
            if content:
                evidence.append({"agent": name, "content": content})
        reasoning = _agent_reasoning(out)
        if reasoning:
            evidence.append({"agent": name, "content": reasoning})
    return evidence


def build_committee_record(
    *,
    event: dict[str, Any],
    agent_outputs: dict[str, dict[str, Any]],
    decision: str,
    confidence: float,
    signal_id: str = "",
    supervisor_reasoning: str = "",
    agents_called: Optional[list[str]] = None,
    agents_skipped: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Assemble the canonical structured committee-cycle record.

    ``agent_outputs`` is the flat map of agent-name → output dict (leads
    expanded to their specialists upstream). Every field is guaranteed present
    so downstream persistence and the control-plane trace are deterministic.
    """
    outputs = {
        str(name): out for name, out in (agent_outputs or {}).items() if isinstance(out, dict)
    }
    # Derive called/skipped from the outputs when not explicitly supplied.
    if agents_called is None:
        called = list(outputs.keys())
    else:
        called = [str(n) for n in agents_called]
    skipped = [str(n) for n in (agents_skipped or [])]
    return {
        "event": {
            "event_id": str(event.get("event_id") or event.get("id") or ""),
            "event_type": str(event.get("event_type") or ""),
            "symbol": str(event.get("symbol") or ""),
        },
        "agents_called": called,
        "agents_skipped": skipped,
        "agent_outputs": outputs,
        "conflicts": collect_conflicts(outputs),
        "evidence": collect_evidence(outputs),
        "supervisor_reasoning": str(supervisor_reasoning or ""),
        "decision": str(decision or "WAIT").upper(),
        "confidence": round(_as_float(confidence), 4),
        "signal_id": str(signal_id or ""),
    }


def render_committee_narrative(record: dict[str, Any]) -> str:
    """Render a structured record as a natural human-facing message.

    Output shape (derived from real evidence, no template labels)::

        OVERWATCH

        Structure sees a bullish break above the recent range, but the
        breakout is still close to the previous resistance zone.

        Momentum agrees with the direction, although strength is not extreme.

        Committee view:
        BUY remains valid, but only if price holds above the breakout level.
    """
    if not isinstance(record, dict):
        return ""
    outputs = record.get("agent_outputs") or {}
    called = record.get("agents_called") or list(outputs.keys())
    conflicts = record.get("conflicts") or []
    decision = str(record.get("decision") or "WAIT").upper()
    event = record.get("event") or {}
    symbol = str(event.get("symbol") or "").strip()
    reasoning = str(record.get("supervisor_reasoning") or "").strip()

    # Department leads whose specialists ALSO speak are redundant in a
    # narrative — skip the lead so the committee reads like individual
    # specialists rather than a summary-of-a-summary.
    lead_keys = {
        name
        for name, out in outputs.items()
        if isinstance(out, dict) and out.get("role") == "department_lead"
    }
    specialist_names = set(outputs.keys()) - lead_keys
    speak = [
        name
        for name in called
        if name in specialist_names
        or not _lead_has_speaking_specialist(outputs, name, specialist_names)
    ]

    lines: list[str] = ["OVERWATCH", ""]

    # One short paragraph per contributing agent, drawn from real evidence.
    for name in speak:
        out = outputs.get(name)
        if not isinstance(out, dict):
            continue
        signal = _direction_of(out.get("signal"))
        phrase = _SIGNAL_PHRASE.get(str(out.get("signal") or "").upper(), _SIGNAL_PHRASE[signal])
        detail = _agent_reasoning(out)
        line = f"{_callsign(name)} {phrase}"
        if detail:
            # Keep it a sentence; trim a trailing period to avoid "..".
            detail = detail.rstrip(". ")
            line = f"{line}; {detail}"
        lines.append(f"{line}.")
        lines.append("")

    # Conflicts are surfaced explicitly when present.
    if conflicts:
        lines.append("Disagreement:")
        for conflict in conflicts:
            lines.append(f"- {conflict.get('detail', '')}")
        lines.append("")

    # The committee view: decision + the supervisor's own reasoning.
    header = "Committee view:"
    if symbol:
        header = f"Committee view ({symbol}):"
    lines.append(header)
    verdict = {
        "BUY": "BUY remains valid",
        "SELL": "SELL remains valid",
        "WAIT": "I am not treating this as a clean entry yet",
        "NO_TRADE": "No trade",
    }.get(decision, decision)
    if reasoning:
        lines.append(f"{verdict}. {reasoning}")
    else:
        lines.append(f"{verdict}.")
    return "\n".join(lines).rstrip() + "\n"
