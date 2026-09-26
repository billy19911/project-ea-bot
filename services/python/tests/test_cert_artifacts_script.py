# -*- coding: utf-8 -*-
"""CERT-A1 — tests for the CI/Artifacts generator (Gate A evidence).

These tests are intentionally LIGHTWEIGHT: they never run the full pytest
suite (or any other heavy CI command) from inside pytest. They verify that:

* the generator script ``scripts/cert_artifacts.ps1`` exists and is non-empty;
* the six Gate A artifacts under ``reports/`` are parse-able — JSON files are
  valid JSON and text files are non-empty (when they have been generated).

The Gate A collector
(``services/python/src/live_readiness/certification_evidence.py``) globs for
``**/pytest*.txt``, ``**/node_tests*.json``, ``**/web_build*.txt``,
``**/typecheck*.txt``/``**/tsc*.txt``, ``**/lint*.txt``/``**/flake8*.txt`` and
``**/security*.json``/``**/bandit*.json`` — the artifact names below match.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# repo root = .../services/python/tests -> parents[3]
_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _REPO_ROOT / "scripts" / "cert_artifacts.ps1"
_REPORTS_DIR = _REPO_ROOT / "reports"

# Artifact name -> kind ("json" | "text"), matching the collector's globs.
_ARTIFACTS: dict[str, str] = {
    "pytest-report.txt": "text",
    "node_tests.json": "json",
    "web_build.txt": "text",
    "typecheck.txt": "text",
    "lint.txt": "text",
    "security.json": "json",
}


class TestGeneratorScript:
    """The generator script itself must exist and be non-trivial."""

    def test_script_exists_and_non_empty(self) -> None:
        assert _SCRIPT.is_file(), f"script tidak ditemukan: {_SCRIPT}"
        assert _SCRIPT.stat().st_size > 0

    def test_script_mentions_all_artifact_names(self) -> None:
        text = _SCRIPT.read_text(encoding="utf-8", errors="replace")
        for name in _ARTIFACTS:
            assert name in text, f"script tidak menulis artefak {name}"

    def test_reports_dir_is_not_excluded_by_collector(self) -> None:
        """``reports/`` must be at repo root and not inside an excluded dir."""
        excluded = {
            "temp_pytest",
            ".venv",
            "venv",
            "node_modules",
            ".next",
            "dist",
            "build",
            "__pycache__",
        }
        rel = _REPORTS_DIR.relative_to(_REPO_ROOT)
        for part in rel.parts:
            assert not part.startswith("."), f"dir tersembunyi: {part}"
            assert part not in excluded, f"dir di-exclude collector: {part}"


class TestGeneratedArtifacts:
    """Artifacts written to ``reports/`` must be parse-able and non-empty."""

    @pytest.mark.parametrize("name,kind", sorted(_ARTIFACTS.items()))
    def test_artifact_present_non_empty_and_parseable(
        self, name: str, kind: str
    ) -> None:
        path = _REPORTS_DIR / name
        if not path.is_file():
            pytest.skip(
                f"{name} belum digenerate — jalankan scripts/cert_artifacts.ps1"
            )

        assert path.stat().st_size > 0, f"{name} kosong"
        raw = path.read_text(encoding="utf-8", errors="replace")

        if kind == "json":
            data = json.loads(raw)  # raises on invalid JSON
            assert isinstance(data, (dict, list))
        else:
            assert raw.strip(), f"{name} hanya berisi whitespace"

    def test_node_tests_json_shape(self) -> None:
        path = _REPORTS_DIR / "node_tests.json"
        if not path.is_file():
            pytest.skip("node_tests.json belum digenerate")
        data = json.loads(path.read_text(encoding="utf-8"))
        for key in ("command", "exit_code", "output"):
            assert key in data, f"node_tests.json kurang field '{key}'"

    def test_security_json_shape(self) -> None:
        path = _REPORTS_DIR / "security.json"
        if not path.is_file():
            pytest.skip("security.json belum digenerate")
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "pip_audit" in data and "npm_audit" in data
        # pip_audit is either the "not installed" sentinel or a real report.
        pip = data["pip_audit"]
        assert isinstance(pip, dict)
        assert ("error" in pip) or ("findings" in pip) or ("output" in pip)
