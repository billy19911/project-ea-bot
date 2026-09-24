# -*- coding: utf-8 -*-
"""Tests for the Research Center router (UI/UX ide #6).

The router wires the existing ResearchEngine to the UI. Honesty rules pinned
here:

* backtest refuses (ok:false) when live mode is off — never simulates on
  fabricated data;
* backtest refuses when the terminal returns too few real bars;
* metrics payloads are JSON-safe (non-finite profit_factor becomes null);
* experiment/compare validation errors surface as 400/404, not 500.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.main import app  # noqa: E402
from src.mt5 import connector  # noqa: E402

client = TestClient(app)


class _Bar:
    """Minimal OHLC stand-in (only `close` is read by the router)."""

    def __init__(self, close: float) -> None:
        self.close = close


@pytest.fixture(autouse=True)
def _reset_engine_state(tmp_path: Path):
    """Give every test a fresh engine + run registry (module-level singletons).

    Also points the persistence store at a throwaway path so tests never read
    or write the operator's real research_state.jsonl.
    """
    from src.research import endpoints as research_endpoints

    state_path = tmp_path / "research_state.jsonl"
    previous_state = os.environ.get("RESEARCH_STATE_PATH")
    os.environ["RESEARCH_STATE_PATH"] = str(state_path)
    research_endpoints._engine = None
    research_endpoints._RUNS.clear()
    yield
    if previous_state is None:
        os.environ.pop("RESEARCH_STATE_PATH", None)
    else:
        os.environ["RESEARCH_STATE_PATH"] = previous_state
    research_endpoints._engine = None
    research_endpoints._RUNS.clear()


def _create_experiment(fast: int = 3, slow: int = 8) -> str:
    res = client.post(
        "/research/experiments", json={"fast_ema_period": fast, "slow_ema_period": slow}
    )
    assert res.status_code == 200, res.text
    return res.json()["experiment"]["id"]


def test_overview_reports_real_counts_and_notes():
    res = client.get("/research/overview")
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    # Baseline hypothesis/strategy version is seeded (documents the real engine).
    assert data["hypotheses"] == 1
    assert data["experiments"] == 0
    assert data["baseline"]["strategy_version"] == "baseline"
    # Honest notes must be present for the UI.
    assert "memori" in data["engine_note"]
    assert "read-only" in data["data_note"]


def test_overview_reports_persistence_state(monkeypatch):
    """Overview must honestly report whether state is persisted (JSONL) or not."""
    from src.research import endpoints as research_endpoints

    monkeypatch.setattr(research_endpoints, "_engine", None)
    data = client.get("/research/overview").json()
    assert data["persisted"] is True


def test_backtest_provenance_records_requested_vs_actual_bars(monkeypatch):
    """Provenance must carry requested vs actual bars plus first/last bar time."""
    from datetime import datetime, timezone

    class _TimedBar:
        def __init__(self, close: float, idx: int) -> None:
            self.close = close
            self.time = datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp() + idx * 3600

    closes = [100.0 + (i % 10) for i in range(120)]
    bars = [_TimedBar(c, i) for i, c in enumerate(closes)]
    monkeypatch.setattr(connector, "is_live_mode", lambda: True)
    monkeypatch.setattr(connector, "get_ohlc", lambda *a, **k: bars)
    exp_id = _create_experiment()
    res = client.post(
        f"/research/experiments/{exp_id}/backtest",
        json={"symbol": "XAUUSD", "timeframe": "H1", "bars": 300},
    )
    assert res.status_code == 200, res.text
    provenance = res.json()["provenance"]
    assert provenance["requested_bars"] == 300
    assert provenance["bars"] == 120
    assert provenance["source"] == "live"
    assert provenance["first_bar_time"] == bars[0].time
    assert provenance["last_bar_time"] == bars[-1].time


def test_create_experiment_rejects_inverted_emas():
    res = client.post("/research/experiments", json={"fast_ema_period": 10, "slow_ema_period": 5})
    assert res.status_code == 400
    assert "slow_ema_period" in res.json()["detail"]


def test_create_experiment_registers_real_strategy_version():
    exp_id = _create_experiment(4, 12)
    from src.research.endpoints import get_research_engine

    engine = get_research_engine()
    # Version key encodes the full parameter grid.
    version_key = "ema-4-12-atr14-sl2.0-rr2.0"
    assert engine.get_strategy_version(version_key) is not None
    assert engine.get_experiment(exp_id) is not None
    # Same parameter grid reuses the version key (no duplicate).
    _create_experiment(4, 12)
    assert len(engine.list_experiments()) == 2


def test_backtest_refuses_when_live_mode_off(monkeypatch):
    monkeypatch.setattr(connector, "is_live_mode", lambda: False)
    exp_id = _create_experiment()
    res = client.post(
        f"/research/experiments/{exp_id}/backtest",
        json={"symbol": "XAUUSD", "timeframe": "H1", "bars": 500},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is False
    assert "mode data live" in data["reason"]


def test_backtest_refuses_on_too_few_real_bars(monkeypatch):
    monkeypatch.setattr(connector, "is_live_mode", lambda: True)
    monkeypatch.setattr(connector, "get_ohlc", lambda *a, **k: [_Bar(1.0)] * 10)
    exp_id = _create_experiment()
    res = client.post(
        f"/research/experiments/{exp_id}/backtest",
        json={"symbol": "XAUUSD", "timeframe": "H1", "bars": 500},
    )
    data = res.json()
    assert data["ok"] is False
    assert "minimum 60" in data["reason"]


def test_backtest_runs_on_real_bars_and_is_json_safe(monkeypatch):
    # Deterministic wave: EMA crossover trades must be produced.
    closes = [100.0 + (i % 10) for i in range(200)]
    monkeypatch.setattr(connector, "is_live_mode", lambda: True)
    monkeypatch.setattr(connector, "get_ohlc", lambda *a, **k: [_Bar(c) for c in closes])
    exp_id = _create_experiment()
    res = client.post(
        f"/research/experiments/{exp_id}/backtest",
        json={"symbol": "XAUUSD", "timeframe": "H1", "bars": 200},
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["ok"] is True
    assert data["metrics"]["total_trades"] > 0
    assert data["provenance"]["symbol"] == "XAUUSD"
    assert data["provenance"]["bars"] == 200
    assert data["provenance"]["source"] == "live"
    # Walk-forward windows come from the real engine split.
    assert len(data["walk_forward"]["windows"]) == 2

    # Detail endpoint returns the stored result + provenance.
    detail = client.get(f"/research/experiments/{exp_id}").json()
    assert detail["metrics"]["total_trades"] == data["metrics"]["total_trades"]
    assert detail["provenance"]["bars"] == 200
    # Trades preview is capped and JSON-safe.
    assert len(detail["trades_preview"]) <= 10
    assert detail["trades_total"] == data["metrics"]["total_trades"]


def test_backtest_rejects_bad_symbol_and_timeframe(monkeypatch):
    monkeypatch.setattr(connector, "is_live_mode", lambda: True)
    exp_id = _create_experiment()
    bad_symbol = client.post(
        f"/research/experiments/{exp_id}/backtest",
        json={"symbol": "BAD SYMBOL!", "timeframe": "H1", "bars": 500},
    )
    assert bad_symbol.status_code == 400
    bad_tf = client.post(
        f"/research/experiments/{exp_id}/backtest",
        json={"symbol": "XAUUSD", "timeframe": "H9", "bars": 500},
    )
    assert bad_tf.status_code == 400


def test_backtest_unknown_experiment_is_404():
    res = client.post(
        "/research/experiments/does-not-exist/backtest",
        json={"symbol": "XAUUSD", "timeframe": "H1", "bars": 500},
    )
    assert res.status_code == 404


def test_compare_requires_results_and_is_json_safe(monkeypatch):
    closes = [100.0 + (i % 7) for i in range(150)]
    monkeypatch.setattr(connector, "is_live_mode", lambda: True)
    monkeypatch.setattr(connector, "get_ohlc", lambda *a, **k: [_Bar(c) for c in closes])
    exp_a = _create_experiment(2, 6)
    exp_b = _create_experiment(5, 15)

    # Before results exist -> honest 400.
    early = client.post("/research/compare", json={"id_a": exp_a, "id_b": exp_b})
    assert early.status_code == 400

    for exp_id in (exp_a, exp_b):
        client.post(
            f"/research/experiments/{exp_id}/backtest",
            json={"symbol": "XAUUSD", "timeframe": "H1", "bars": 150},
        )

    res = client.post("/research/compare", json={"id_a": exp_a, "id_b": exp_b})
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["ok"] is True
    assert data["experiment_1"]["id"] == exp_a
    assert data["experiment_2"]["id"] == exp_b
    assert "difference" in data

    same = client.post("/research/compare", json={"id_a": exp_a, "id_b": exp_a})
    assert same.status_code == 400


def test_ranking_orders_and_splits_insufficient_sample():
    """Two synthetic results: a strong 12-trade run ranks; a 5-trade run is split out."""
    from datetime import datetime, timezone

    from src.research.endpoints import _ensure_baseline, get_research_engine
    from src.research.engine import BacktestResult

    engine = get_research_engine()
    hypothesis_id = _ensure_baseline(engine)
    engine.create_strategy_version("strong", {"fast_ema_period": 2, "slow_ema_period": 4})
    engine.create_strategy_version("weak", {"fast_ema_period": 2, "slow_ema_period": 4})
    strong = engine.create_experiment(hypothesis_id, "strong")
    weak = engine.create_experiment(hypothesis_id, "weak")

    engine._backtest_results[strong.id] = BacktestResult(
        total_trades=12,
        win_rate=60.0,
        profit_factor=2.5,
        sharpe_ratio=1.0,
        max_drawdown=5.0,
        expectation=1.0,
        net_pnl=120.0,
        trades=[],
        walk_forward={},
    )
    engine._backtest_results[weak.id] = BacktestResult(
        total_trades=5,
        win_rate=80.0,
        profit_factor=4.0,
        sharpe_ratio=1.0,
        max_drawdown=1.0,
        expectation=1.0,
        net_pnl=50.0,
        trades=[],
        walk_forward={},
    )
    engine.record_run_provenance(
        strong.id,
        {
            "symbol": "XAUUSD",
            "source": "live",
            "ran_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
    )

    data = client.get("/research/ranking").json()
    assert data["advisory"] is True
    assert len(data["ranked"]) == 1
    assert data["ranked"][0]["id"] == strong.id
    assert data["ranked"][0]["rank"] == 1
    assert data["ranked"][0]["provenance"]["source"] == "live"
    assert len(data["insufficient_sample"]) == 1
    assert data["insufficient_sample"][0]["id"] == weak.id
    assert "minimum 10" in data["insufficient_sample"][0]["reason"]
