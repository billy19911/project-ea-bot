# -*- coding: utf-8 -*-
"""Security hardening tests — PRD_V2 §28 Security (Python side).

Verifies the FastAPI CORS configuration is env-driven and never combines a
wildcard origin with credentials (an unsafe combination browsers reject).
"""

from __future__ import annotations

from fastapi.middleware.cors import CORSMiddleware

from src.main import app


def _cors_middleware() -> CORSMiddleware:
    for middleware in app.user_middleware:
        if middleware.cls is CORSMiddleware:
            return middleware
    raise AssertionError("CORSMiddleware not installed")


def _cors_options() -> dict:
    mw = _cors_middleware()
    return dict(mw.kwargs)


class TestCorsConfig:
    def test_no_wildcard_with_credentials(self) -> None:
        opts = _cors_options()
        origins = opts.get("allow_origins", [])
        credentials = opts.get("allow_credentials", False)
        # The dangerous combination: allow_origins=["*"] + credentials=True.
        assert not (
            "*" in origins and credentials
        ), "CORS wildcard origin must not be combined with credentials=True"

    def test_origins_declared_explicitly(self) -> None:
        opts = _cors_options()
        origins = opts.get("allow_origins", [])
        assert origins, "CORS origins must be configured explicitly"
        assert "*" not in origins

    def test_credentials_only_with_explicit_origins(self) -> None:
        opts = _cors_options()
        origins = opts.get("allow_origins", [])
        if opts.get("allow_credentials", False):
            assert origins and "*" not in origins

    def test_default_origins_include_localhost(self) -> None:
        opts = _cors_options()
        origins = opts.get("allow_origins", [])
        assert any("localhost:3000" in o or "127.0.0.1:3000" in o for o in origins)


class TestCorsEnvDriven:
    def test_settings_expose_cors_origins(self) -> None:
        from src.config import settings

        # A comma-separated env-driven list, defaulting to the local dev origins.
        assert isinstance(settings.cors_allowed_origins, str)
        assert settings.cors_allowed_origins
