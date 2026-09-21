# -*- coding: utf-8 -*-
"""Tests for the Python API-key authentication middleware (audit P0-1)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.security.api_key import ApiKeyMiddleware, parse_public_paths


def _app_with_key(key: str) -> TestClient:
    app = FastAPI()

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.post("/mt5/terminals/arm")
    async def arm():
        return {"ok": True}

    @app.get("/pipeline/status")
    async def status():
        return {"ok": True}

    app.add_middleware(
        ApiKeyMiddleware,
        api_key=key,
        public_paths=parse_public_paths("/health,/metrics,/"),
    )
    return TestClient(app)


def test_parse_public_paths() -> None:
    assert parse_public_paths("/health,/metrics,/") == {"/health", "/metrics", "/"}
    assert parse_public_paths("") == set()


def test_unauthenticated_request_rejected() -> None:
    client = _app_with_key("secret-key")
    resp = client.post("/mt5/terminals/arm")
    assert resp.status_code == 401
    assert "Unauthorized" in resp.json()["detail"]


def test_wrong_key_rejected() -> None:
    client = _app_with_key("secret-key")
    resp = client.post("/mt5/terminals/arm", headers={"X-API-Key": "nope"})
    assert resp.status_code == 401


def test_correct_key_via_x_api_key() -> None:
    client = _app_with_key("secret-key")
    resp = client.post("/mt5/terminals/arm", headers={"X-API-Key": "secret-key"})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_correct_key_via_bearer() -> None:
    client = _app_with_key("secret-key")
    resp = client.get(
        "/pipeline/status",
        headers={"Authorization": "Bearer secret-key"},
    )
    assert resp.status_code == 200


def test_public_path_requires_no_key() -> None:
    client = _app_with_key("secret-key")
    resp = client.get("/health")
    assert resp.status_code == 200


def test_no_key_configured_allows_all(monkeypatch) -> None:
    """Dev mode: with no key configured the service stays open."""
    client = _app_with_key("")
    assert client.post("/mt5/terminals/arm").status_code == 200
    assert client.get("/pipeline/status").status_code == 200


if __name__ == "__main__":  # pragma: no cover
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
