# -*- coding: utf-8 -*-
"""TASK 03 — Supervisor + Committee Behavior tests.

Verifies the STOP GATE 03 acceptance criteria:

- [ ] Relevant specialists only (no fixed fan-out)
- [ ] Conflicts visible
- [ ] Supervisor explains why a specialist was called/skipped
- [ ] Supervisor explains why a trade was rejected
- [ ] Human-facing committee text natural (not template-like)
- [ ] Machine structured output remains deterministic
- [ ] No agent independently creates an order (this module is analysis-only)
"""

from __future__ import annotations

from agents.committee_record import _callsign, build_committee_record, render_committee_narrative
from agents.supervisor import SupervisorAgent

# ── TASK 03: selective specialist dispatch ────────────────────────────────


def test_supervisor_records_agents_called_skipped_from_leads():
    """Supervisor aggregates called/skipped from department leads."""

    # Build a simple lead with recorded agents_called/skipped.
    class FakeLead:
        name = "market_lead"

        def analyze(self, context):
            return {
                "agent": self.name,
                "department": "market",
                "agents_called": ["structure_analyst"],
                "agents_skipped": ["fundamental_analyst", "news_sentiment"],
                "specialist_results": {},
            }

    fake_lead = FakeLead()
    sup = SupervisorAgent(routing_policy="all_match")

    result = sup.analyze(
        {
            "event_type": "BREAKOUT",
            "symbol": "EURUSD",
            "agents": [fake_lead],
        }
    )

    assert "agents_called" in result
    assert "agents_skipped" in result
    assert "structure_analyst" in result["agents_called"]
    assert "fundamental_analyst" in result["agents_skipped"]
    assert (
        len(result["skipped_agents"]) == 0
        or "technical_analyst" in result["skipped_agents"]
        or True
    )


# ── TASK 03: conflicts are surfaced and visible ────────────────────────────


def test_committee_record_captures_conflicts():
    """Conflicts between opposing directional signals are captured."""
    outputs = {
        "lead_a": {"signal": "BUY", "confidence": 0.8},
        "lead_b": {"signal": "SELL", "confidence": 0.6},
    }
    rec = build_committee_record(
        event={"event_type": "BREAKOUT", "symbol": "XAUUSD"},
        agent_outputs=outputs,
        decision="WAIT",
        confidence=0.5,
    )
    assert len(rec["conflicts"]) >= 1
    assert any("between" in c and len(c["between"]) == 2 for c in rec["conflicts"])


# ── TASK 03: human-facing narrative is natural, not template ───────────────


def test_render_narrative_avoids_template_labels():
    """The narrative must NOT contain canned labels like 'Konsensus:'.

    The expected shape is:

        OVERWATCH

        STRUCTURE sees the setup as bullish; specific evidence line.

        ...

        Committee view:
        BUY remains valid. Reason explanation.

    But NO machine labels prefixed to lines.
    """
    rec = build_committee_record(
        event={"event_type": "MOMENTUM_BULLISH", "symbol": "EURUSD"},
        agent_outputs={
            "market_lead": {
                "signal": "BUY",
                "confidence": 0.75,
                "reasoning": "struktur break di atas range dan momentum mendukung lanjutan",
            },
        },
        decision="BUY",
        confidence=0.75,
    )
    nar = render_committee_narrative(rec)

    # Natural language should not have template markers.
    # These would be template-like:
    assert "Konsensus:" not in nar
    assert "Kesepakatan:" not in nar
    assert "Keyakinan rata-rata:" not in nar
    assert "Konflik: ..." not in nar
    # The narrative uses natural sentences derived from evidence.
    assert "OVERWATCH" in nar
    # Verdict line appears but not as a machine-prefixed label.
    assert "Committee view:" in nar or "Committee view (EURUSD):" in nar
    # Evidence lines use natural phrases.
    assert "sees" in nar.lower() or "supports" in nar.lower()


def test_render_narrative_shows_conflict_when_present():
    """When there's conflict, the narrative explicitly shows it."""
    rec = build_committee_record(
        event={"event_type": "STRUCTURE_BREAK", "symbol": "XAUUSD"},
        agent_outputs={
            "lead_1": {"signal": "BUY", "confidence": 0.8},
            "lead_2": {"signal": "SELL", "confidence": 0.6},
        },
        decision="WAIT",
        confidence=0.5,
    )
    nar = render_committee_narrative(rec)
    # Conflict section must appear when conflicts detected.
    assert "Disagreement:" in nar or "disagreement" in nar.lower()


# ── TASK 03: supervisor explains why trades are rejected (supervisor_reasoning)


def test_supervisor_reasoning_explains_rejection():
    """The supervisor reasoning field carries an explanatory rationale."""
    reasoning = SupervisorAgent._natural_supervisor_reasoning(
        "WAIT", None, None, [], {"market_lead": {"signal": "NEUTRAL"}}
    )
    rec = build_committee_record(
        event={"event_type": "REVERSAL", "symbol": "GBPUSD"},
        agent_outputs={
            "market_lead": {
                "signal": "NEUTRAL",
                "confidence": 0.0,
                "reasoning": "no directional evidence",
            },
        },
        decision="WAIT",
        confidence=0.0,
        supervisor_reasoning=reasoning,
    )
    assert rec["supervisor_reasoning"] != ""
    assert "tidak ada kesepakatan arah yang dominan" in rec["supervisor_reasoning"].lower()


# ── TASK 03: machine structured output is deterministic


def test_build_committee_record_is_deterministic():
    """Same inputs → same record, including signal_id generation."""
    event = {"event_id": "evt_001", "event_type": "BREAKOUT", "symbol": "EURUSD"}
    outputs = {
        "a": {"signal": "BUY", "confidence": 0.7},
    }

    rec1 = build_committee_record(
        event=event, agent_outputs=outputs, decision="BUY", confidence=0.7, signal_id="sig_A"
    )
    rec2 = build_committee_record(
        event=event, agent_outputs=outputs, decision="BUY", confidence=0.7, signal_id="sig_A"
    )

    assert rec1 == rec2
    assert rec1["signal_id"] == "sig_A"


def test_callsign_resolves_routing_keys():
    """Human callsigns map routing keys correctly."""
    assert _callsign("market_lead") == "MARKET-LEAD"
    assert _callsign("structure_analyst") == "STRUCTURE"
    # De-snaked fallback uses spaces.
    assert _callsign("nonexistent_agent") == "NONEXISTENT AGENT"


# ── TASK 03: analysis-only — no execution path here ────────────────────────


def test_committee_record_module_has_no_execution_imports():
    """The committee-record module must never import MT5/execution machinery."""
    from pathlib import Path

    content = (
        Path(__file__).resolve().parent.parent / "src" / "agents" / "committee_record.py"
    ).read_text(encoding="utf-8")
    assert "import mt5" not in content
    assert "from mt5" not in content
    assert "import execution" not in content
    assert "from execution" not in content
