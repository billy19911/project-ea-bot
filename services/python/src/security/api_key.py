# -*- coding: utf-8 -*-
"""API-key authentication middleware for the Python service (audit P0-1).

The Node/Express API is JWT-protected, but the Python FastAPI service previously
had **no authentication at all** while binding a routable interface — so the
order-arming switch (``POST /mt5/terminals/arm``), ``/pipeline/run`` and the
circuit-breaker controls were reachable by anyone who could reach the port.

This middleware closes that hole without breaking local development:

* **When** ``PYTHON_API_KEY`` **is set**, every request that is not on the public
  allowlist (``/health``, ``/metrics``, ``/`` by default) must present the key via
  ``X-API-Key: <key>`` or ``Authorization: Bearer <key>``. Missing/wrong → 401.
* **When** it is unset, authentication is disabled (dev mode). The service
  default bind is now loopback (``127.0.0.1``) so an unauthenticated instance is
  not reachable off-host.

The comparison is constant-time to avoid trivial key-length/timing leaks. The key
is never logged.
"""

from __future__ import annotations

import hmac
import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

__all__ = ["ApiKeyMiddleware", "parse_public_paths"]

# Methods that are always considered read-only-safe probes on public paths.
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def parse_public_paths(raw: str) -> set[str]:
    """Parse the comma-separated public-path env value into a set."""
    return {p.strip() for p in (raw or "").split(",") if p.strip()}


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """Reject requests without a valid API key when a key is configured.

    Args:
        app: The ASGI app.
        api_key: The required key. Empty string disables enforcement (dev mode).
        public_paths: Paths that never require the key (liveness/readiness).
    """

    def __init__(
        self,
        app,
        api_key: str = "",
        public_paths: set[str] | None = None,
    ) -> None:
        super().__init__(app)
        self._api_key = api_key or ""
        self._public_paths = public_paths or set()

    def _is_public(self, request: Request) -> bool:
        """Return True when the path is allowlisted for unauthenticated access."""
        path = request.url.path
        if path in self._public_paths:
            return True
        # CORS preflight must never be blocked.
        return request.method == "OPTIONS"

    @staticmethod
    def _extract_key(request: Request) -> str:
        """Read the presented key from X-API-Key or Authorization: Bearer."""
        header = request.headers.get("x-api-key")
        if header:
            return header.strip()
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        return ""

    async def dispatch(self, request: Request, call_next):
        # No key configured → dev mode, allow through.
        if not self._api_key:
            return await call_next(request)

        if self._is_public(request):
            return await call_next(request)

        presented = self._extract_key(request)
        # Constant-time comparison; also rejects empty presented keys.
        if presented and hmac.compare_digest(presented, self._api_key):
            return await call_next(request)

        logger.warning("Rejected unauthenticated request: %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=401,
            content={"detail": "Unauthorized — missing or invalid API key"},
        )
