# -*- coding: utf-8 -*-
"""Research Center router (UI/UX ide #6) — wires the existing ResearchEngine.

The engine (``src/research/engine.py``) already implements hypotheses,
strategy versions, experiments, deterministic EMA-crossover backtests and
comparison — but nothing used it. This router exposes it honestly:

- backtests run ONLY on real OHLC bars from the attached MT5 terminal
  (``connector.get_ohlc``, read-only — no orders, no re-bind); when live mode
  is off the endpoint refuses instead of simulating on random data;
- results live in the Python service memory; the payload says so;
- PnL is a price-difference measure (position sizing is not modelled) and the
  payload says so too.

The only seeded record is the baseline hypothesis/strategy version, which
*documents the engine's actual built-in simulation* (EMA crossover with the
real ``trading.indicators.ema``, default 3/8) — it fabricates no results.
"""

from __future__ import annotations

import math
import os
import re
import threading
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .engine import BacktestResult, Experiment, ResearchEngine
from .store import ResearchStore

router = APIRouter(prefix="/research", tags=["research"])

# Minimum bars for a statistically meaningful backtest + walk-forward split.
MIN_BARS_FOR_BACKTEST = 60
# How many of the most recent trades travel to the UI (payload stays small).
TRADES_PREVIEW = 10

_TIMEFRAMES = {"M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1", "MN1"}
_SYMBOL_RE = re.compile(r"^[A-Z0-9.#_]{1,16}$")

_engine: ResearchEngine | None = None
_engine_lock = threading.Lock()
# Provenance of the last backtest per experiment (symbol/timeframe/bars/account).
_RUNS: dict[str, dict[str, Any]] = {}


class ExperimentCreate(BaseModel):
    """Parameters for a new experiment (strategy parameter grid).

    The engine supports multiple strategy types; EMA-crossover parameters are
    shown for backward compatibility but RSI/MACD strategies use their own
    parameter sets (rsi_period, rsi_overbought, rsi_oversold, macd_fast_period,
    macd_slow_period, macd_signal_period).
    """

    fast_ema_period: int = Field(default=3, ge=1, le=200)
    slow_ema_period: int = Field(default=8, ge=2, le=400)
    atr_period: int = Field(default=14, ge=2, le=100)
    atr_stop_multiplier: float = Field(default=2.0, gt=0, le=10)
    reward_risk_ratio: float = Field(default=2.0, gt=0, le=10)
    strategy_type: str = Field(default="ema_crossover", min_length=1, max_length=32)
    label: str = Field(default="", max_length=80)


class BacktestRequest(BaseModel):
    """Data selection for one backtest run.

    Supports two modes:
    1. Bar-count mode: specify `bars` (default, fetches last N bars).
    2. Date-range mode: specify both `start_date` and `end_date` (ISO format).
       When both dates provided, `bars` is ignored (or used as a safety cap).
    """

    symbol: str = Field(default="XAUUSD", min_length=1, max_length=16)
    timeframe: str = Field(default="H1", min_length=1, max_length=4)
    bars: int = Field(default=5000, ge=100, le=100000)
    start_date: str | None = Field(
        default=None,
        description="ISO datetime (UTC): '2023-01-01T00:00:00Z'. Requires end_date.",
    )
    end_date: str | None = Field(
        default=None,
        description="ISO datetime (UTC): '2024-12-31T23:59:59Z'. Requires start_date.",
    )


class CompareRequest(BaseModel):
    """Two experiment ids to compare side-by-side."""

    id_a: str
    id_b: str


# ---------------------------------------------------------------------------
# Engine singleton + baseline scaffolding
# ---------------------------------------------------------------------------


def _ensure_baseline(engine: ResearchEngine) -> str:
    """Ensure the baseline hypothesis/strategy version exist; return hyp id.

    The baseline documents the engine's real built-in strategy: EMA crossover
    computed with the project's real indicator implementation (defaults 3/8).
    """
    existing = engine.list_hypotheses()
    if existing:
        return existing[0].id
    hyp = engine.create_hypothesis(
        name="EMA crossover",
        description=(
            "Sinyal dari perpotongan EMA cepat & lambat pada bar harga nyata "
            "terminal MT5 (simulasi deterministik bawaan engine)."
        ),
        entry_rules=[
            "EMA cepat memotong ke atas EMA lambat -> posisi long",
            "EMA cepat memotong ke bawah EMA lambat -> posisi short",
        ],
        exit_rules=[
            "Perpotongan berlawanan menutup posisi",
            "Posisi terbuka ditutup pada bar terakhir",
        ],
        parameters={"fast_ema_period": 3, "slow_ema_period": 8},
    )
    if engine.get_strategy_version("baseline") is None:
        engine.create_strategy_version(
            "baseline",
            {"fast_ema_period": 3, "slow_ema_period": 8},
            "Parameter EMA bawaan engine (3/8).",
        )
    return hyp.id


def get_research_engine() -> ResearchEngine:
    """Return the process-wide ResearchEngine (created on first use)."""
    global _engine
    with _engine_lock:
        if _engine is None:
            engine = ResearchEngine(
                store=ResearchStore(os.environ.get("RESEARCH_STATE_PATH"))
            )
            _ensure_baseline(engine)
            _engine = engine
        return _engine


# ---------------------------------------------------------------------------
# Serialisation helpers (JSON-safe: non-finite floats become null)
# ---------------------------------------------------------------------------


def _finite(value: Any, digits: int | None = None) -> float | None:
    """Coerce to a finite float, rounding when asked; ``None`` when not finite."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return round(number, digits) if digits is not None else number


def _sanitize(obj: Any) -> Any:
    """Recursively make a payload JSON-safe (inf/nan -> null)."""
    if isinstance(obj, dict):
        return {key: _sanitize(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(value) for value in obj]
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    return obj


def _metrics_dict(result: BacktestResult | None) -> dict[str, Any] | None:
    """Round a BacktestResult into the metrics payload (or None)."""
    if result is None:
        return None
    return {
        "total_trades": result.total_trades,
        "win_rate": _finite(result.win_rate, 2),
        "profit_factor": _finite(result.profit_factor, 4),
        "sharpe_ratio": _finite(result.sharpe_ratio, 4),
        "max_drawdown": _finite(result.max_drawdown, 2),
        "expectation": _finite(result.expectation, 4),
        "net_pnl": _finite(result.net_pnl, 2),
    }


def _experiment_row(engine: ResearchEngine, experiment: Experiment) -> dict[str, Any]:
    """One experiment as a UI row (with result summary when it exists).

    ``parameters`` shows the *effective* grid: the strategy version's
    parameters merged with any per-experiment overrides, so the UI can display
    the full configuration (EMA pair + ATR + stop + RR), not just overrides.
    """
    result = engine.get_backtest_result(experiment.id)
    effective: dict[str, Any] = {}
    version = engine.get_strategy_version(experiment.strategy_version)
    if version is not None:
        effective.update(version.parameters)
    effective.update(experiment.parameters)
    parameters = {
        key: value
        for key, value in effective.items()
        if isinstance(value, (int, float, str, bool))
    }
    return {
        "id": experiment.id,
        "name": experiment.name,
        "strategy_version": experiment.strategy_version,
        "strategy_type": getattr(experiment, "strategy_type", "ema_crossover"),
        "parameters": parameters,
        "status": experiment.status,
        "has_result": result is not None,
        "metrics": _metrics_dict(result),
    }


def _account_snapshot() -> dict[str, Any] | None:
    """Read-only snapshot of the attached account (provenance only)."""
    try:
        import MetaTrader5 as mt5
    except ImportError:
        return None
    info = mt5.account_info()
    if info is None:
        return None
    return {
        "login": getattr(info, "login", None),
        "server": getattr(info, "server", None),
        "currency": getattr(info, "currency", None),
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/strategies")
def list_strategies() -> dict[str, Any]:
    """List the strategy types the backtest engine supports."""
    return {
        "ok": True,
        "strategies": [
            {
                "id": "ema_crossover",
                "name": "EMA Crossover",
                "description": "Fast/slow EMA crossover on real closes.",
                "parameters": [
                    "fast_ema_period",
                    "slow_ema_period",
                    "atr_period",
                    "atr_stop_multiplier",
                    "reward_risk_ratio",
                ],
            },
            {
                "id": "rsi_reversal",
                "name": "RSI Reversal",
                "description": "RSI oversold/overbought reversal entry.",
                "parameters": [
                    "rsi_period",
                    "rsi_overbought",
                    "rsi_oversold",
                    "atr_period",
                    "atr_stop_multiplier",
                    "reward_risk_ratio",
                ],
            },
            {
                "id": "macd_crossover",
                "name": "MACD Crossover",
                "description": "MACD histogram zero-cross entry.",
                "parameters": [
                    "macd_fast_period",
                    "macd_slow_period",
                    "macd_signal_period",
                    "atr_period",
                    "atr_stop_multiplier",
                    "reward_risk_ratio",
                ],
            },
        ],
    }


@router.get("/overview")
def get_overview() -> dict[str, Any]:
    """Real counts + the honest notes the UI must show."""
    engine = get_research_engine()
    experiments = engine.list_experiments()
    completed = sum(
        1 for exp in experiments if engine.get_backtest_result(exp.id) is not None
    )
    hypotheses = engine.list_hypotheses()
    baseline = hypotheses[0] if hypotheses else None
    return {
        "ok": True,
        "hypotheses": len(hypotheses),
        "experiments": len(experiments),
        "completed": completed,
        "baseline": (
            {"id": baseline.id, "name": baseline.name, "strategy_version": "baseline"}
            if baseline
            else None
        ),
        "persisted": engine.persisted,
        "engine_note": (
            "Hasil backtest tersimpan di JSONL dan dipulihkan saat layanan restart; "
            "memori tetap cache aktif."
            if engine.persisted
            else "Persistensi gagal; hasil hanya tersimpan di memori layanan Python."
        ),
        "data_note": (
            "Backtest memakai bar harga nyata dari terminal MT5 yang terpasang "
            "(read-only). PnL = selisih harga per unit, bukan saldo akun; ukuran "
            "posisi tidak dimodelkan."
        ),
    }


@router.get("/experiments")
def list_experiments() -> dict[str, Any]:
    """All experiments, newest first, each with its result summary."""
    engine = get_research_engine()
    rows = [_experiment_row(engine, exp) for exp in reversed(engine.list_experiments())]
    return {"ok": True, "experiments": rows, "count": len(rows)}


@router.post("/experiments")
def create_experiment(payload: ExperimentCreate) -> dict[str, Any]:
    """Create an experiment across the full strategy parameter grid."""
    engine = get_research_engine()
    fast = int(payload.fast_ema_period)
    slow = int(payload.slow_ema_period)
    if slow <= fast:
        raise HTTPException(
            status_code=400,
            detail="slow_ema_period harus lebih besar dari fast_ema_period.",
        )
    params = {
        "fast_ema_period": fast,
        "slow_ema_period": slow,
        "atr_period": int(payload.atr_period),
        "atr_stop_multiplier": float(payload.atr_stop_multiplier),
        "reward_risk_ratio": float(payload.reward_risk_ratio),
    }
    baseline_id = _ensure_baseline(engine)
    # Version key encodes the full grid so distinct configs never collide.
    version_key = (
        f"ema-{fast}-{slow}-atr{params['atr_period']}"
        f"-sl{params['atr_stop_multiplier']}-rr{params['reward_risk_ratio']}"
    )
    if engine.get_strategy_version(version_key) is None:
        engine.create_strategy_version(
            version_key,
            params,
            payload.label
            or f"EMA {fast}/{slow} · ATR{params['atr_period']} · RR{params['reward_risk_ratio']}",
        )
    experiment = engine.create_experiment(
        baseline_id, version_key, {}, strategy_type=payload.strategy_type
    )
    return {"ok": True, "experiment": _experiment_row(engine, experiment)}


@router.get("/experiments/{experiment_id}")
def get_experiment_detail(experiment_id: str) -> dict[str, Any]:
    """Experiment detail: metrics, walk-forward windows, trades preview."""
    engine = get_research_engine()
    experiment = engine.get_experiment(experiment_id)
    if experiment is None:
        raise HTTPException(
            status_code=404, detail=f"Eksperimen tidak ditemukan: {experiment_id}"
        )
    result = engine.get_backtest_result(experiment_id)
    return {
        "ok": True,
        "experiment": _experiment_row(engine, experiment),
        "metrics": _metrics_dict(result),
        "walk_forward": _sanitize(result.walk_forward) if result else None,
        "trades_total": len(result.trades) if result else 0,
        "trades_preview": _sanitize(result.trades[-TRADES_PREVIEW:]) if result else [],
        "provenance": _RUNS.get(experiment_id)
        or engine.get_run_provenance(experiment_id),
    }


@router.post("/experiments/{experiment_id}/backtest")
def run_experiment_backtest(
    experiment_id: str, payload: BacktestRequest
) -> dict[str, Any]:
    """Run a deterministic backtest over REAL bars from the attached terminal.

    Sync endpoint on purpose: MT5 reads and the EMA simulation are blocking,
    so FastAPI runs this in its worker threadpool instead of the event loop.
    """
    engine = get_research_engine()
    experiment = engine.get_experiment(experiment_id)
    if experiment is None:
        raise HTTPException(
            status_code=404, detail=f"Eksperimen tidak ditemukan: {experiment_id}"
        )

    symbol = payload.symbol.strip().upper()
    timeframe = payload.timeframe.strip().upper()
    if not _SYMBOL_RE.match(symbol):
        raise HTTPException(status_code=400, detail="Simbol tidak valid.")
    if timeframe not in _TIMEFRAMES:
        raise HTTPException(
            status_code=400, detail=f"Timeframe tidak dikenal: {timeframe}"
        )

    from ..mt5 import connector

    if not connector.is_live_mode():
        return {
            "ok": False,
            "reason": (
                "MT5 tidak dalam mode data live — backtest hanya berjalan di "
                "atas bar nyata terminal."
            ),
        }

    # Determine mode: date-range or bar-count
    use_date_range = payload.start_date is not None and payload.end_date is not None
    if use_date_range:
        try:
            start_dt = datetime.fromisoformat(
                payload.start_date.replace("Z", "+00:00")
            ).replace(tzinfo=None)
            end_dt = datetime.fromisoformat(
                payload.end_date.replace("Z", "+00:00")
            ).replace(tzinfo=None)
        except (ValueError, AttributeError) as e:
            raise HTTPException(
                status_code=400, detail=f"Format tanggal tidak valid: {e}"
            )
        if start_dt >= end_dt:
            raise HTTPException(
                status_code=400, detail="start_date harus lebih awal dari end_date."
            )
        bars = connector.get_ohlc_range(symbol, timeframe, start_dt, end_dt)
    else:
        bars = connector.get_ohlc(symbol, timeframe, payload.bars)

    closes = [
        float(bar.close) for bar in bars if getattr(bar, "close", None) is not None
    ]
    highs = [float(bar.high) for bar in bars if getattr(bar, "high", None) is not None]
    lows = [float(bar.low) for bar in bars if getattr(bar, "low", None) is not None]
    if len(closes) < MIN_BARS_FOR_BACKTEST:
        return {
            "ok": False,
            "reason": (
                f"Data bar tidak cukup untuk {symbol} {timeframe}: {len(closes)} "
                f"bar terbaca (minimum {MIN_BARS_FOR_BACKTEST}). Periksa simbol "
                "di terminal MT5."
            ),
        }

    result = engine.run_backtest(
        experiment,
        closes,
        walk_forward=True,
        highs=highs if len(highs) == len(closes) else None,
        lows=lows if len(lows) == len(closes) else None,
    )

    provenance = {
        "symbol": symbol,
        "symbol_resolved": getattr(connector, "resolve_symbol", lambda value: None)(
            symbol
        ),
        "timeframe": timeframe,
        "bars": len(closes),
        "requested_bars": payload.bars if not use_date_range else None,
        "mode": "date_range" if use_date_range else "bar_count",
        "start_date": payload.start_date if use_date_range else None,
        "end_date": payload.end_date if use_date_range else None,
        "ran_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "live",
        "account": _account_snapshot(),
        "first_bar_time": getattr(bars[0], "time", None) if bars else None,
        "last_bar_time": getattr(bars[-1], "time", None) if bars else None,
    }
    provenance = _sanitize(provenance)
    _RUNS[experiment_id] = provenance
    engine.record_run_provenance(experiment_id, provenance)

    return {
        "ok": True,
        "experiment": _experiment_row(engine, experiment),
        "provenance": provenance,
        "metrics": _metrics_dict(result),
        "walk_forward": _sanitize(result.walk_forward),
        "trades_total": len(result.trades),
        "trades_preview": _sanitize(result.trades[-TRADES_PREVIEW:]),
    }


@router.get("/ranking")
def rank_experiments() -> dict[str, Any]:
    """Rank completed experiments by profit factor, then net PnL."""
    engine = get_research_engine()
    ranked: list[dict[str, Any]] = []
    insufficient: list[dict[str, Any]] = []
    for experiment in engine.list_experiments():
        result = engine.get_backtest_result(experiment.id)
        if result is None:
            continue
        entry = {
            "id": experiment.id,
            "name": experiment.name,
            "metrics": _metrics_dict(result),
            "provenance": engine.get_run_provenance(experiment.id),
        }
        if result.total_trades < 10:
            entry["reason"] = "total_trades kurang dari minimum 10"
            insufficient.append(entry)
        else:
            ranked.append(entry)
    ranked.sort(
        key=lambda item: (
            -(item["metrics"]["profit_factor"] or 0),
            -(item["metrics"]["net_pnl"] or 0),
        )
    )
    for rank, entry in enumerate(ranked, 1):
        entry["rank"] = rank
    return {
        "ok": True,
        "advisory": True,
        "note": "Peringkat informasional; tidak pernah mengaktifkan strategi otomatis.",
        "rule": "profit_factor desc, tie-break net_pnl desc, minimum 10 trades",
        "ranked": ranked,
        "insufficient_sample": insufficient,
    }


@router.get("/data-info")
def get_data_info(symbol: str = "XAUUSD", timeframe: str = "H1") -> dict[str, Any]:
    """Return metadata about available historical data for a symbol/timeframe.

    Query params:
        symbol: Symbol name (default XAUUSD).
        timeframe: MT5 timeframe label (default H1).

    Returns:
        Metadata dict with available depth, oldest/newest bars, max supported bars.
    """
    from ..mt5 import connector

    symbol = symbol.strip().upper()
    timeframe = timeframe.strip().upper()
    if not _SYMBOL_RE.match(symbol):
        raise HTTPException(status_code=400, detail="Simbol tidak valid.")
    if timeframe not in _TIMEFRAMES:
        raise HTTPException(
            status_code=400, detail=f"Timeframe tidak dikenal: {timeframe}"
        )

    info = connector.get_data_info(symbol, timeframe)
    return {
        "ok": True,
        "symbol": symbol,
        "timeframe": timeframe,
        "info": info,
    }


@router.post("/compare")
def compare_experiments(payload: CompareRequest) -> dict[str, Any]:
    """Compare two experiments that both have real backtest results."""
    engine = get_research_engine()
    if payload.id_a == payload.id_b:
        raise HTTPException(
            status_code=400, detail="Pilih dua eksperimen yang berbeda."
        )
    first = engine.get_experiment(payload.id_a)
    second = engine.get_experiment(payload.id_b)
    if first is None or second is None:
        raise HTTPException(
            status_code=404, detail="Salah satu eksperimen tidak ditemukan."
        )
    try:
        comparison = engine.compare_experiments(first, second)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, **_sanitize(comparison)}
