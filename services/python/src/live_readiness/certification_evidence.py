# -*- coding: utf-8 -*-
"""Evidence collection for the Production Certification Gate (PRD_V2 §50).

The gate is only truthful when it consumes **observed facts**. This module
builds the per-check evidence mapping from real in-process state and real
artifacts on disk. Honesty rules:

* An observed ``True`` means a real artefact/state was seen healthy.
* An observed ``False`` means a real artefact/state was seen unhealthy.
* ``None`` means **not run / unknown** — never a fabricated pass, and never
  silently preferred over a real failure.
* Each check carries a short human ``reason`` and an ``evidence_source`` so the
  UI can explain *why* a gate is not passed.

Nothing here executes a trade, arms a terminal, or mutates configuration.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

__all__ = ["collect_gate_evidence"]

# Minimum completed backtests with walk-forward evidence to accept a strategy.
_MIN_COMPLETED_BACKTESTS = 1
_MIN_SAMPLE_TRADES = 100


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _ev(value: bool | None, reason: str, source: str) -> dict[str, Any]:
    return {"value": value, "reason": reason, "evidence_source": source}


def _unknown(reason: str, source: str) -> dict[str, Any]:
    return _ev(None, reason, source)


@dataclass
class _ArtifactRule:
    """A Gate A evidence artefact: a report file that must exist + be fresh."""

    check: str
    patterns: tuple[str, ...]
    label: str


# Gate A looks for REAL local CI artifacts. Absent => unknown (never True).
_ARTIFACT_RULES: tuple[_ArtifactRule, ...] = (
    _ArtifactRule("python_tests", ("**/pytest*.txt", "**/python_tests*.json"), "laporan pytest"),
    _ArtifactRule("node_tests", ("**/node_tests*.json", "**/jest*.json"), "laporan node test"),
    _ArtifactRule("web_build", ("**/web_build*.txt", "**/next-build*.log"), "log build web"),
    _ArtifactRule("type_check", ("**/typecheck*.txt", "**/tsc*.txt"), "log type-check"),
    _ArtifactRule("lint", ("**/lint*.txt", "**/flake8*.txt", "**/eslint*.json"), "log lint"),
    _ArtifactRule("security_scan", ("**/security*.json", "**/bandit*.json"), "laporan security"),
)

# Directories that never contain real CI evidence: leftover pytest ``tmp_path``
# fixtures, virtualenvs, build outputs, caches, and hidden dirs (``.git`` etc.).
_EXCLUDED_DIRS: frozenset[str] = frozenset(
    {
        "temp_pytest",
        ".venv",
        "venv",
        "node_modules",
        ".next",
        "dist",
        "build",
        "__pycache__",
    }
)


def _find_artifact(root: Path, rule: _ArtifactRule) -> Optional[Path]:
    for pattern in rule.patterns:
        matches = sorted(root.glob(pattern))
        for match in matches:
            if not (match.is_file() and match.stat().st_size > 0):
                continue
            rel = match.relative_to(root)
            parts = rel.parts
            excluded = False
            for part in parts:
                if part in _EXCLUDED_DIRS or part.startswith("."):
                    excluded = True
                    break
            if excluded:
                continue
            return match
    return None


def _collect_gate_a(root: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for rule in _ARTIFACT_RULES:
        found = _find_artifact(root, rule)
        if found is None:
            out[rule.check] = _unknown(f"{rule.label} tidak ditemukan", "filesystem")
            continue
        try:
            rel = found.relative_to(root)
        except ValueError:  # pragma: no cover - defensive
            rel = found
        mtime = datetime.fromtimestamp(found.stat().st_mtime, tz=timezone.utc).isoformat(
            timespec="seconds"
        )
        out[rule.check] = _ev(
            True,
            f"{rule.label} ada (mtime {mtime})",
            f"file:{str(rel).replace(chr(92), '/')}",
        )
    return out


def _collect_gate_b(probes: dict[str, Callable[[], Any]]) -> dict[str, dict[str, Any]]:
    """Gate B — live runtime safety states.

    Each probe returns ``(value, reason, source)`` or a raw value. A probe that
    raises => unknown with the exception recorded (never a pass). Checks with
    no probe are explicitly unknown — never a silent False or True.
    """
    from .certification_gate import GATE_B_CHECKS

    out: dict[str, dict[str, Any]] = {
        check: _unknown("probe runtime tidak tersedia di proses ini", "runtime")
        for check in GATE_B_CHECKS
    }
    for check, probe in probes.items():
        try:
            result = probe()
        except Exception as exc:  # noqa: BLE001 - a broken probe is unknown
            out[check] = _unknown(f"probe gagal: {exc}", "runtime")
            continue
        if isinstance(result, dict):
            value = result.get("value")
            reason = str(result.get("reason") or "")
            source = str(result.get("evidence_source") or result.get("source") or "runtime")
            out[check] = _ev(value, reason, source)
        elif isinstance(result, tuple) and len(result) == 3:
            out[check] = _ev(result[0], str(result[1]), str(result[2]))
        else:
            out[check] = _ev(bool(result), "", "runtime")
    return out


def _research_evidence(
    research_records: Any = "__unset__",
) -> dict[str, dict[str, Any]]:
    """Gate C — real completed research results from the research engine.

    ``research_records`` defaults to the runtime inbox (``"__unset__"``). An
    empty *observable* store means "no completed backtests" (``False``); an
    unreachable store means unknown (``None``).
    """
    out: dict[str, dict[str, Any]] = {
        check: _unknown("mesin riset belum menghasilkan bukti", "research_engine")
        for check in (
            "backtest",
            "walk_forward",
            "monte_carlo",
            "parameter_sensitivity",
            "sufficient_sample",
        )
    }
    if research_records == "__unset__":
        try:
            store: Optional[list[dict[str, Any]]] = _research_results_store()
        except Exception as exc:  # noqa: BLE001
            for check in out:
                out[check] = _unknown(f"store riset tidak tersedia: {exc}", "research_engine")
            return out
    else:
        store = research_records
    if store is None:
        return out

    completed = 0
    walk_forward = 0
    monte_carlo = 0
    sensitivity = 0
    max_sample = 0
    for record in store:
        status = str(record.get("status") or "").upper()
        if status not in ("COMPLETED", "PASSED", "OK", "SUCCESS"):
            continue
        completed += 1
        metrics = record.get("metrics_summary") or record.get("metrics") or {}
        validation = record.get("validation_evidence") or {}
        if validation.get("walk_forward") or metrics.get("walk_forward"):
            walk_forward += 1
        if validation.get("monte_carlo") or metrics.get("monte_carlo"):
            monte_carlo += 1
        if validation.get("sensitivity") or metrics.get("parameter_sensitivity"):
            sensitivity += 1
        sample = int(metrics.get("trades") or metrics.get("sample_size") or 0)
        max_sample = max(max_sample, sample)

    if completed >= _MIN_COMPLETED_BACKTESTS:
        out["backtest"] = _ev(True, f"{completed} backtest selesai", "research_engine")
    else:
        out["backtest"] = _ev(False, "belum ada backtest selesai", "research_engine")

    out["walk_forward"] = (
        _ev(True, f"{walk_forward} hasil walk-forward", "research_engine")
        if walk_forward > 0
        else _ev(False, "belum ada hasil walk-forward", "research_engine")
    )
    out["parameter_sensitivity"] = (
        _ev(True, f"{sensitivity} hasil sensitivitas", "research_engine")
        if sensitivity > 0
        else _ev(False, "belum ada hasil sensitivitas", "research_engine")
    )
    out["monte_carlo"] = (
        _ev(True, f"{monte_carlo} hasil Monte Carlo", "research_engine")
        if monte_carlo > 0
        else _unknown("belum ada hasil Monte Carlo", "research_engine")
    )
    out["sufficient_sample"] = (
        _ev(True, f"sampel maksimum {max_sample} trade", "research_engine")
        if max_sample >= _MIN_SAMPLE_TRADES
        else _ev(False, f"sampel maksimum {max_sample} < {_MIN_SAMPLE_TRADES}", "research_engine")
    )
    return out


def _research_results_store() -> Optional[list[dict[str, Any]]]:
    """Best-effort read of completed research records from the runtime inbox."""
    try:
        from ..orchestration.runtime import get_runtime

        inbox = getattr(get_runtime(), "research_inbox", None)
        if inbox is not None and hasattr(inbox, "all"):
            return [i.to_dict() if hasattr(i, "to_dict") else dict(i) for i in inbox.all()]
    except Exception:  # noqa: BLE001
        return None
    return None


def _collect_gate_d() -> dict[str, dict[str, Any]]:
    """Gate D — operational drills. Unverifiable from this process => unknown."""
    out: dict[str, dict[str, Any]] = {}
    for check in (
        "mt5_restart",
        "pc_restart",
        "mt5_disconnect",
        "database_failure",
        "llm_failure",
        "nine_router_failure",
        "telegram_failure",
    ):
        out[check] = _unknown(
            "drill operasional belum dijalankan/diverifikasi dari proses ini", "ops_drill"
        )
    return out


def _collect_gate_e(execution_quality: Any, incident_manager: Any) -> dict[str, dict[str, Any]]:
    """Gate E — forward evidence from live stores."""
    out: dict[str, dict[str, Any]] = {}
    out["paper"] = _unknown("bukti paper trading belum tersedia", "forward_store")
    out["demo"] = _unknown("bukti demo trading belum tersedia", "forward_store")
    out["monitoring"] = _unknown("bukti monitoring kontinu belum tersedia", "forward_store")

    if execution_quality is not None:
        try:
            count = len(execution_quality.records())
        except Exception as exc:  # noqa: BLE001
            out["execution_quality"] = _unknown(
                f"analitik eksekusi gagal: {exc}", "execution_quality"
            )
        else:
            out["execution_quality"] = (
                _ev(True, f"{count} rekaman eksekusi", "execution_quality")
                if count > 0
                else _ev(False, "belum ada rekaman eksekusi", "execution_quality")
            )
    else:
        out["execution_quality"] = _unknown("analitik eksekusi tidak tersedia", "execution_quality")

    if incident_manager is not None:
        try:
            critical_open = bool(incident_manager.has_critical_open())
        except Exception as exc:  # noqa: BLE001
            out["no_critical_incident"] = _unknown(f"manajer insiden gagal: {exc}", "incidents")
        else:
            out["no_critical_incident"] = (
                _ev(True, "tidak ada insiden kritikal terbuka", "incidents")
                if not critical_open
                else _ev(False, "ada insiden kritikal terbuka", "incidents")
            )
    else:
        out["no_critical_incident"] = _unknown("manajer insiden tidak tersedia", "incidents")
    return out


def collect_gate_evidence(
    *,
    repo_root: Optional[Path] = None,
    gate_b_probes: Optional[dict[str, Callable[[], Any]]] = None,
    execution_quality: Any = None,
    incident_manager: Any = None,
    research_records: Any = "__unset__",
) -> dict[str, dict[str, dict[str, Any]]]:
    """Build the full certification evidence map ``{gate: {check: evidence}}``.

    Args:
        repo_root: Root used to look for Gate A CI artifacts. Defaults to the
            repository root derived from this file's location.
        gate_b_probes: Live runtime safety probes (see :func:`_collect_gate_b`).
        execution_quality: Shared :class:`ExecutionQualityAnalytics` singleton.
        incident_manager: Shared :class:`IncidentManager` singleton.

    Every check not backed by observed evidence is ``None`` (NOT_RUN) with a
    reason — never fabricated.
    """
    root = repo_root or Path(__file__).resolve().parents[4]
    gates: dict[str, dict[str, dict[str, Any]]] = {
        "A": _collect_gate_a(root),
        "B": _collect_gate_b(gate_b_probes or {}),
        "C": _research_evidence(research_records),
        "D": _collect_gate_d(),
        "E": _collect_gate_e(execution_quality, incident_manager),
    }
    return gates
