# -*- coding: utf-8 -*-
"""Compatibility shim — the real application lives in ``src.main``.

Historically this module held a standalone skeleton FastAPI app. The
production app (routers, agents, orchestration, safety stack) is
``src.main:app``; this shim only re-exports it so legacy invocations like
``uvicorn main:app`` (from ``services/python``) keep working and can never
serve a second, divergent application.

Run (canonical):  uvicorn src.main:app --host 127.0.0.1 --port 8787
"""

from src.main import app  # noqa: F401  (re-exported for uvicorn)

__all__ = ["app"]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.main:app", host="0.0.0.0", port=8787)
