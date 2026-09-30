# -*- coding: utf-8 -*-
"""Phase 3 — event dispatch tests (§28): triggers, levels, no-change gating."""
from __future__ import annotations

import pytest

from src.agents.event_dispatch import LEVEL_ENTRY, decide_dispatch


def test_bos_dispatches_structure_specialist():
    d = decide_dispatch("BOS", state_changed=True)
    assert d.run_committee is True
    assert "structure" in d.roles


def test_choch_dispatches_structure_specialist():
    d = decide_dispatch("CHOCH", state_changed=True)
    assert d.run_committee is True
    assert "structure" in d.roles


def test_liquidity_sweep_dispatches_liquidity():
    d = decide_dispatch("LIQUIDITY_SWEEP", state_changed=True)
    assert d.run_committee is True
    assert "liquidity" in d.roles


def test_news_event_dispatches_news_only():
    d = decide_dispatch("NEWS_HIGH_IMPACT", state_changed=True)
    assert d.run_committee is True
    assert "news" in d.roles


def test_volatility_spike_dispatches_volatility():
    d = decide_dispatch("VOLATILITY_SPIKE", state_changed=True)
    assert d.run_committee is True
    assert "volatility" in d.roles


def test_position_event_is_deterministic_only():
    for evt in ("POSITION_OPENED", "POSITION_CLOSED", "TRADE_CLOSE"):
        d = decide_dispatch(evt, state_changed=True)
        assert d.run_committee is False


def test_no_state_change_uses_cache():
    d = decide_dispatch("BOS", state_changed=False)
    assert d.run_committee is False
    assert d.use_cache is True


def test_setup_formed_goes_to_market_lead():
    d = decide_dispatch("SETUP_FORMED", state_changed=True)
    assert d.run_committee is True
    assert d.level == 2


def test_trigger_approaching_with_setup_goes_entry():
    d = decide_dispatch("TRIGGER_APPROACHING", state_changed=True, has_setup=True)
    assert d.run_committee is True
    assert d.level == LEVEL_ENTRY
    assert "entry" in d.roles


def test_regime_change_dispatches_regime():
    d = decide_dispatch("REGIME_CHANGE", state_changed=True)
    assert d.run_committee is True
    assert "regime" in d.roles


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
