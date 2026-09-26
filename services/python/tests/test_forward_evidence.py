# -*- coding: utf-8 -*-
"""RED→GREEN tests for Gate E forward-testing evidence (CERT-E1).

Gate E's ``paper`` / ``demo`` / ``monitoring`` checks are backed by the real
forward-testing store ``docs/evidence/forward-testing.json`` (override:
``FORWARD_EVIDENCE_PATH`` env or the ``forward_path`` parameter of
``_collect_gate_e``). Each key holds
``{"status": "passed", "at": ..., "metrics": {...}}``.

Honesty rules verified here:
* a present ``status=passed`` entry → ``True`` (+ reason + metrics),
* an absent store / absent key → ``unknown`` (``None`` — never a fabricated
  pass),
* a non-``passed`` status → ``False``.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.live_readiness.certification_evidence import (
    _collect_gate_e,
    collect_gate_evidence,
)


def _write_store(path: Path, payload: dict) -> Path:
    store = path / "forward-testing.json"
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(json.dumps(payload), encoding="utf-8")
    return store


def test_absent_store_is_unknown(tmp_path: Path) -> None:
    """No store on disk => every forward key is unknown, never True."""
    evidence = _collect_gate_e(None, None, forward_path=tmp_path / "missing.json")
    for key in ("paper", "demo", "monitoring"):
        assert evidence[key]["value"] is None
        assert evidence[key]["evidence_source"] == "forward_store"


def test_passed_entry_is_true_with_reason_and_metrics(tmp_path: Path) -> None:
    """A passed entry => True + a reason carrying the timestamp + metrics."""
    store = _write_store(
        tmp_path,
        {
            "paper": {
                "status": "passed",
                "at": "2026-01-01T00:00:00+00:00",
                "metrics": {"trades": 24, "win_rate": 54.2, "net_pnl": 123.4},
            }
        },
    )
    evidence = _collect_gate_e(None, None, forward_path=store)
    assert evidence["paper"]["value"] is True
    assert "2026-01-01T00:00:00+00:00" in evidence["paper"]["reason"]
    assert "trades=24" in evidence["paper"]["reason"]
    # Keys not present in the store stay unknown (not fabricated).
    assert evidence["demo"]["value"] is None
    assert evidence["monitoring"]["value"] is None


def test_failed_status_is_false(tmp_path: Path) -> None:
    """A non-passed status => False (never silently unknown/passed)."""
    store = _write_store(
        tmp_path,
        {"demo": {"status": "failed", "at": "2026-01-01T00:00:00+00:00"}},
    )
    evidence = _collect_gate_e(None, None, forward_path=store)
    assert evidence["demo"]["value"] is False
    assert "failed" in evidence["demo"]["reason"]


def test_all_three_passed(tmp_path: Path) -> None:
    """A fully populated passing store flips paper/demo/monitoring to True."""
    store = _write_store(
        tmp_path,
        {
            "paper": {"status": "passed", "at": "t", "metrics": {"trades": 20}},
            "demo": {"status": "passed", "at": "t", "metrics": {"ticket": 1}},
            "monitoring": {"status": "passed", "at": "t", "metrics": {"ticks": 10}},
        },
    )
    evidence = _collect_gate_e(None, None, forward_path=store)
    for key in ("paper", "demo", "monitoring"):
        assert evidence[key]["value"] is True


def test_env_override_is_honored(tmp_path: Path, monkeypatch) -> None:
    """``FORWARD_EVIDENCE_PATH`` is used when ``forward_path`` is None."""
    store = _write_store(
        tmp_path, {"paper": {"status": "passed", "at": "t", "metrics": {}}}
    )
    monkeypatch.setenv("FORWARD_EVIDENCE_PATH", str(store))
    evidence = _collect_gate_e(None, None)
    assert evidence["paper"]["value"] is True


def test_malformed_store_is_unknown_not_crash(tmp_path: Path) -> None:
    """A broken JSON store degrades to unknown for all forward keys."""
    store = tmp_path / "forward-testing.json"
    store.write_text("{ not json", encoding="utf-8")
    evidence = _collect_gate_e(None, None, forward_path=store)
    for key in ("paper", "demo", "monitoring"):
        assert evidence[key]["value"] is None


def test_collect_gate_evidence_absent_store_keeps_gate_e_unknown(
    tmp_path: Path, monkeypatch
) -> None:
    """The full collector keeps forward keys unknown when the store is absent."""
    monkeypatch.setenv("FORWARD_EVIDENCE_PATH", str(tmp_path / "nope.json"))
    evidence = collect_gate_evidence(repo_root=tmp_path)
    for key in ("paper", "demo", "monitoring"):
        assert evidence["E"][key]["value"] is None
