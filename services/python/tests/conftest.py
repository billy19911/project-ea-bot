"""Pytest configuration and shared fixtures."""

import sys
from pathlib import Path

import pytest

# Ensure src/ is on the path for imports
src_dir = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(src_dir))


@pytest.fixture(autouse=True)
def _clear_market_snapshot_cache():
    """Isolate the process-wide market snapshot cache between tests."""
    from trading.market_snapshot import clear_latest_snapshots

    clear_latest_snapshots()
    yield
    clear_latest_snapshots()


@pytest.fixture(autouse=True)
def _isolate_research_state(tmp_path, monkeypatch):
    """Point the research JSONL store at a throwaway path for every test.

    Without this, engines built with the default store would read/write the
    operator's real research_state.jsonl and leak state across tests.
    """
    monkeypatch.setenv("RESEARCH_STATE_PATH", str(tmp_path / "research_state.jsonl"))
