# -*- coding: utf-8 -*-
"""Tests for specialist output normalization (audit P2-5)."""

from __future__ import annotations

from agents.supervisor import SupervisorAgent, normalize_agent_output


def test_normalizes_reasons_list_to_reasoning_string():
    out = normalize_agent_output(
        {"agent": "momentum", "signal": "buy", "confidence": 0.7, "reasons": ["a", "b"]},
        "momentum",
    )
    assert out["signal"] == "BUY"
    assert out["confidence"] == 0.7
    assert out["reasoning"] == "a; b"
    assert out["reasons"] == ["a", "b"]
    assert out["evidence"] == []


def test_normalizes_reasoning_string_to_reasons_list():
    out = normalize_agent_output(
        {"signal": "SELL", "confidence": 0.5, "reasoning": "because"},
        "structure",
    )
    assert out["reasons"] == ["because"]
    assert out["reasoning"] == "because"


def test_backfills_agent_and_defaults_signal():
    out = normalize_agent_output({"confidence": 0.3}, "news")
    assert out["agent"] == "news"
    assert out["signal"] == "NEUTRAL"
    assert out["evidence"] == []


def test_clamps_confidence_and_handles_bad_values():
    out = normalize_agent_output({"signal": "BUY", "confidence": "not-a-number"})
    assert out["confidence"] == 0.0
    out2 = normalize_agent_output({"signal": "BUY", "confidence": 5.0})
    assert out2["confidence"] == 1.0


def test_non_dict_output_is_wrapped_fail_safe():
    out = normalize_agent_output(None, "ghost")
    assert out["agent"] == "ghost"
    assert out["signal"] == "NEUTRAL"
    assert out["reasoning"] == ""
    assert out["reasons"] == []
    assert out["evidence"] == []


def test_evidence_coerced_to_list():
    out = normalize_agent_output({"evidence": {"fact": "x"}})
    assert out["evidence"] == [{"fact": "x"}]
    out2 = normalize_agent_output({"evidence": ["a", "b"]})
    assert out2["evidence"] == ["a", "b"]


def test_supervisor_applies_normalization_to_agent_results():
    """A specialist returning only `reasons` is normalized on dispatch."""
    from agents.base import BaseAgent
    from agents.registry import AgentRegistry
    from agents.supervisor import AgentPriority

    class _Analyst(BaseAgent):
        def __init__(self):
            super().__init__(name="analyst", agent_type="analyst", priority=AgentPriority.NORMAL)

        def can_handle(self, event_type, context):
            return True

        def analyze(self, context):
            return {"signal": "bearish", "confidence": 0.6, "reasons": ["r1", "r2"]}

    registry = AgentRegistry()
    registry.register(_Analyst())
    sup = SupervisorAgent(routing_policy="all_match")
    sup._registry_cache = registry
    sup.add_route("BREAKOUT", ["analyst"])
    result = sup.analyze({"event_type": "BREAKOUT", "symbol": "EURUSD"})

    entry = result["agent_results"]["analyst"]
    assert entry["signal"] == "BEARISH"
    assert entry["reasoning"] == "r1; r2"
    assert entry["reasons"] == ["r1", "r2"]
    assert entry["evidence"] == []


if __name__ == "__main__":  # pragma: no cover
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
