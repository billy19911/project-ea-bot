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
    monkeypatch.setenv("ENGINE_V2_STORE_PATH", str(tmp_path / "learning_engine_v2.jsonl"))


@pytest.fixture(autouse=True)
def _isolate_signal_registry():
    """Reset the process-wide signal registry between tests.

    The registry gates re-analysis while a symbol has a live signal, and it is
    intentionally process-wide in production. Tests must not leak signal state
    (a PENDING signal from one test would gate the next).
    """
    from orchestration.signal_registry import reset_signal_registry

    reset_signal_registry()
    yield
    reset_signal_registry()


@pytest.fixture(autouse=True)
def _isolate_order_state_ledger(tmp_path, monkeypatch):
    """Isolate the process-wide order-state ledger between tests.

    Phase 1 Item #6 made ``ExecutionEngine._is_duplicate`` also consult the
    durable order-state store so a restarted process does NOT forget an
    already-submitted order. That store is intentionally process-wide in
    production, so without isolation a test that dispatches an order leaks a
    "duplicate" marker into the next test (and would read the operator's real
    ``logs/order_state.jsonl``).

    This fixture points the store path at a throwaway file and detaches/resets
    the module-level ledger before AND after every test.
    """
    monkeypatch.setenv("ORDER_STATE_PATH", str(tmp_path / "order_state.jsonl"))
    try:
        from execution.state_machine import reset_store, set_store
    except Exception:  # pragma: no cover - import identity fallback
        from src.execution.state_machine import reset_store, set_store  # type: ignore

    reset_store()
    set_store(None)
    yield
    reset_store()
    set_store(None)


@pytest.fixture(autouse=True)
def _isolate_review_and_trade_ledger(tmp_path, monkeypatch):
    """Isolate the process-wide review store + trade ledger between tests.

    TASK 01 wired both as process-wide singletons at app startup. Tests that
    boot the real FastAPI app (``TestClient(main.app)``) would otherwise
    rehydrate ``logs/reviews.jsonl`` (the operator's real file, or another
    test's leftovers) and ``/v2/r-performance`` would report ``NO_DATA`` for
    seeded in-process records because the durable branch skips the fallback.
    Point both paths at throwaway files and detach the singletons before AND
    after every test.
    """
    monkeypatch.setenv("REVIEW_STORE_PATH", str(tmp_path / "reviews.jsonl"))
    monkeypatch.setenv("TRADE_LEDGER_PATH", str(tmp_path / "trade_ledger.jsonl"))
    try:
        from persistence.review_store import set_review_store
        from persistence.trade_ledger import set_trade_ledger
    except Exception:  # pragma: no cover - import identity fallback
        from src.persistence.review_store import set_review_store  # type: ignore
        from src.persistence.trade_ledger import set_trade_ledger  # type: ignore

    set_review_store(None)
    set_trade_ledger(None)
    yield
    set_review_store(None)
    set_trade_ledger(None)
