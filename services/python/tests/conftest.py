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


@pytest.fixture(autouse=True)
def _isolate_lesson_stores(tmp_path, monkeypatch):
    """Point every learning JSONL store at a throwaway path for every test.

    Critical data-hygiene guard: tests that boot the real FastAPI app
    (``TestClient(main.app)``) run the lifespan, which builds
    ``JsonlLessonStore()`` / ``JsonlEngineV2Store()`` from their default paths.
    Before this fixture those defaults were *relative* and resolved to the
    operator's real ``services/python/logs/lessons.jsonl``, so placeholder
    records (``trade_id="T-1"``, ``lesson="s"``) leaked into production
    learning data (783 records, ~309 of them test junk).

    Anchoring the env vars at a tmp path makes a test run structurally unable
    to touch real lesson/engine-v2 files.
    """
    monkeypatch.setenv("LESSON_STORE_PATH", str(tmp_path / "lessons.jsonl"))
    monkeypatch.setenv(
        "ENGINE_V2_STORE_PATH", str(tmp_path / "learning_engine_v2.jsonl")
    )
