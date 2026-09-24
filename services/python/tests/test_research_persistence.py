from __future__ import annotations

from pathlib import Path

from src.research.engine import ResearchEngine
from src.research.store import ResearchStore


def test_research_state_survives_engine_restart(tmp_path: Path):
    path = tmp_path / "research.jsonl"
    first = ResearchEngine(store=ResearchStore(path))
    hypothesis = first.create_hypothesis("Test", "desc")
    first.create_strategy_version("v1", {"fast_ema_period": 2, "slow_ema_period": 4})
    experiment = first.create_experiment(hypothesis.id, "v1")
    result = first.run_backtest(experiment, [100 + (i % 8) for i in range(80)])
    first.record_run_provenance(experiment.id, {"source": "synthetic", "bars": 80})

    second = ResearchEngine(store=ResearchStore(path))
    restored = second.get_experiment(experiment.id)
    assert restored is not None
    assert second.get_backtest_result(experiment.id).net_pnl == result.net_pnl
    assert second.get_run_provenance(experiment.id)["source"] == "synthetic"


def test_corrupt_lines_are_skipped(tmp_path: Path):
    path = tmp_path / "research.jsonl"
    path.write_text('{"type":"not-a-record"}\nnot json\n', encoding="utf-8")
    engine = ResearchEngine(store=ResearchStore(path))
    assert engine.list_experiments() == []


def test_write_failure_degrades_to_memory(tmp_path: Path):
    # A directory in place of the file makes every write attempt fail.
    path = tmp_path / "research.jsonl"
    path.mkdir()
    store = ResearchStore(path)
    engine = ResearchEngine(store=store)
    hypothesis = engine.create_hypothesis("Test", "desc")
    engine.create_strategy_version("v1")
    experiment = engine.create_experiment(hypothesis.id, "v1")
    engine.run_backtest(experiment, [100.0] * 20)
    assert engine.get_experiment(experiment.id) is not None
    assert store.persisted is False
