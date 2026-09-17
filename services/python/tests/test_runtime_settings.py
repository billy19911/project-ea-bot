# -*- coding: utf-8 -*-
"""Tests for runtime settings (UI/UX ide #7).

These tests exist to prove the settings endpoint is NOT theatre: every
writable knob must be consumed by a real object, invalid input must be
rejected, and safety limits must stay read-only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.orchestration.runtime import get_runtime  # noqa: E402
from src.system.settings_store import KNOBS, RuntimeSettingsStore  # noqa: E402


@pytest.fixture()
def store(tmp_path: Path) -> RuntimeSettingsStore:
    """Isolated store backed by a temp file."""
    return RuntimeSettingsStore(path=str(tmp_path / "runtime_settings.json"))


class TestKnobValidation:
    def test_defaults_are_returned_without_file(self, store: RuntimeSettingsStore) -> None:
        values = store.snapshot().values
        assert values["supervisor_token_budget"] == 8000
        assert values["scheduler_poll_interval"] == 1.0

    def test_rejects_out_of_range(self, store: RuntimeSettingsStore) -> None:
        applied, errors = store.update({"supervisor_token_budget": 5})
        assert applied == {}
        assert errors and "rentang" in errors[0]

    def test_rejects_unknown_key(self, store: RuntimeSettingsStore) -> None:
        applied, errors = store.update({"max_daily_loss": 999999})
        assert applied == {}
        assert errors and "bukan setting" in errors[0]

    def test_rejects_non_numeric(self, store: RuntimeSettingsStore) -> None:
        applied, errors = store.update({"supervisor_token_budget": "banyak"})
        assert applied == {}
        assert errors

    def test_rejects_boolean(self, store: RuntimeSettingsStore) -> None:
        applied, errors = store.update({"supervisor_token_budget": True})
        assert applied == {}
        assert errors

    def test_accepts_valid_update_and_persists(self, store: RuntimeSettingsStore) -> None:
        applied, errors = store.update({"supervisor_token_budget": 12000})
        assert errors == []
        assert applied == {"supervisor_token_budget": 12000}
        # Persisted to disk, so a fresh store sees it.
        fresh = RuntimeSettingsStore(path=store._path)
        assert fresh.snapshot().values["supervisor_token_budget"] == 12000

    def test_corrupt_file_degrades_to_defaults(self, tmp_path: Path) -> None:
        path = tmp_path / "runtime_settings.json"
        path.write_text("{ not json", encoding="utf-8")
        store = RuntimeSettingsStore(path=str(path))
        assert store.snapshot().values["supervisor_token_budget"] == 8000

    def test_hand_edited_junk_is_ignored(self, tmp_path: Path) -> None:
        path = tmp_path / "runtime_settings.json"
        path.write_text(
            json.dumps(
                {"supervisor_token_budget": "junk", "evil": 1, "scheduler_poll_interval": 2.5}
            ),
            encoding="utf-8",
        )
        store = RuntimeSettingsStore(path=str(path))
        values = store.snapshot().values
        assert values["supervisor_token_budget"] == 8000  # junk ignored
        assert values["scheduler_poll_interval"] == 2.5  # valid kept
        assert "evil" not in values

    def test_describe_lists_bounds_and_wiring(self, store: RuntimeSettingsStore) -> None:
        described = {d["key"]: d for d in store.describe()}
        assert set(described) == {k.key for k in KNOBS}
        assert described["supervisor_token_budget"]["applied_to"] == "SupervisorAgent.token_budget"
        assert described["scheduler_poll_interval"]["minimum"] == 0.1


class TestSafetyLimitsAreNotWritable:
    """The whole point of the allowlist: safety values must not be editable."""

    def test_risk_limits_not_in_allowlist(self) -> None:
        keys = {k.key for k in KNOBS}
        for forbidden in (
            "max_daily_loss",
            "max_position_size",
            "max_exposure_percent",
            "max_daily_trades",
            "min_signal_confidence",
            "max_account_drawdown_percent",
        ):
            assert forbidden not in keys

    def test_store_refuses_risk_limit_patch(self, store: RuntimeSettingsStore) -> None:
        _, errors = store.update({"max_daily_loss": 1e9})
        assert errors


class TestApplyToRuntime:
    """Proves the knobs reach real objects — not just a JSON file."""

    def test_supervisor_budget_is_pushed(self) -> None:
        from src.system.endpoints import _apply_to_runtime

        runtime = get_runtime()
        supervisor = runtime.pipeline.supervisor
        original = supervisor.token_budget
        try:
            pushed = _apply_to_runtime({"supervisor_token_budget": 12345})
            assert pushed["supervisor_token_budget"] == 12345
            assert supervisor.token_budget == 12345
        finally:
            supervisor.token_budget = original

    def test_scheduler_interval_is_pushed(self) -> None:
        from src.system.endpoints import _apply_to_runtime

        runtime = get_runtime()
        original = runtime.scheduler.poll_interval
        try:
            pushed = _apply_to_runtime({"scheduler_poll_interval": 3.5})
            assert pushed["scheduler_poll_interval"] == 3.5
            assert runtime.scheduler.poll_interval == 3.5
        finally:
            runtime.scheduler.poll_interval = original

    def test_risk_limits_snapshot_reads_live_gate(self) -> None:
        from src.system.endpoints import _risk_limits_snapshot

        snap = _risk_limits_snapshot()
        assert snap["available"] is True
        # Values come from the live RiskEngine thresholds / gate limits.
        assert snap["limits"]["max_drawdown"] is not None
        assert snap["limits"]["daily_loss_limit"] is not None
        assert snap["limits"]["max_spread_pips"] is not None


class TestSettingsEndpoint:
    """Endpoint-level behaviour via the FastAPI test client."""

    @pytest.fixture()
    def client(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from fastapi.testclient import TestClient

        import src.system.settings_store as settings_store_module
        from src.main import app

        isolated = RuntimeSettingsStore(path=str(tmp_path / "settings.json"))
        monkeypatch.setattr(settings_store_module, "_STORE", isolated)
        monkeypatch.setattr("src.system.endpoints.get_settings_store", lambda: isolated)
        with TestClient(app) as c:
            yield c

    def test_get_returns_writable_and_risk_limits(self, client) -> None:
        r = client.get("/settings")
        assert r.status_code == 200
        body = r.json()
        assert {d["key"] for d in body["writable"]} == {k.key for k in KNOBS}
        assert "risk_limits" in body
        limits = body["risk_limits"]["limits"]
        assert limits["max_drawdown"] is not None
        assert limits["max_spread_pips"] is not None

    def test_put_applies_and_pushes_to_runtime(self, client) -> None:
        runtime = get_runtime()
        original = runtime.pipeline.supervisor.token_budget
        try:
            r = client.put("/settings", json={"supervisor_token_budget": 11000})
            assert r.status_code == 200
            body = r.json()
            assert body["ok"] is True
            assert body["applied"]["supervisor_token_budget"] == 11000
            assert runtime.pipeline.supervisor.token_budget == 11000
        finally:
            runtime.pipeline.supervisor.token_budget = original

    def test_put_rejects_risk_limit(self, client) -> None:
        r = client.put("/settings", json={"max_daily_loss": 1e9})
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is False
        assert body["errors"]

    def test_get_does_not_mutate_runtime(self, client) -> None:
        """A GET must never push values — startup/PUT own that."""
        runtime = get_runtime()
        runtime.pipeline.supervisor.token_budget = 777
        try:
            client.get("/settings")
            assert runtime.pipeline.supervisor.token_budget == 777
        finally:
            runtime.pipeline.supervisor.token_budget = 8000
