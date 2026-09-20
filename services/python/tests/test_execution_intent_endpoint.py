# -*- coding: utf-8 -*-
"""Tests for Execution Intent state endpoint (Phase 34)."""

from fastapi.testclient import TestClient

from src.main import app

client = TestClient(app)


def test_intent_not_found() -> None:
    res = client.get("/execution/intent/unknown-id")
    assert res.status_code == 200
    data = res.json()
    assert "error" in data
    assert data["source"] == "unavailable"


# Additional tests would register an intent via internal API, but that requires
# invoking ExecutionEngine – out of scope for now; existence check ensures the
# endpoint is present and behaves on missing data.
