# -*- coding: utf-8 -*-
"""Resolve persistent-store paths relative to the *service root*, not the CWD.

Background (data-hygiene fix):
    The lesson stores used ``os.path.join("logs", "lessons.jsonl")`` — a
    **relative** path. Its meaning therefore depended on the process working
    directory: the running server resolved it to ``services/python/logs/...``
    while the test suite (CWD = repo root when run via the root ``pytest.ini``)
    resolved it to a *different* location. Worse, tests that boot the real
    FastAPI app (``TestClient(main.app)``) ran the lifespan, which built
    ``JsonlLessonStore()`` against the relative path and appended placeholder
    records (``trade_id="T-1"``, ``lesson="s"``) straight into the operator's
    production lesson file.

    These helpers make the default path **absolute and CWD-independent**, and
    give tests a single, explicit override mechanism so a test run can never
    contaminate real learning data.
"""

from __future__ import annotations

import os

__all__ = [
    "service_root",
    "resolve_store_path",
    "LESSON_PATH_ENV",
    "ENGINE_V2_PATH_ENV",
]

# Env vars that override the default location (used by operators *and* tests).
LESSON_PATH_ENV = "LESSON_STORE_PATH"
ENGINE_V2_PATH_ENV = "ENGINE_V2_STORE_PATH"

# ``store_paths.py`` lives at ``services/python/src/learning/store_paths.py``.
# service_root = ``services/python``.
_SERVICE_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.pardir, os.pardir)
)


def service_root() -> str:
    """Return the absolute ``services/python`` directory."""
    return _SERVICE_ROOT


def resolve_store_path(default_filename: str, env_var: str) -> str:
    """Resolve a persistent store path to an absolute, CWD-independent path.

    Order of precedence:
        1. ``env_var`` value if set (absolute values are honoured verbatim;
           relative values are anchored at the service root);
        2. ``<service_root>/logs/<default_filename>``.
    """
    override = os.getenv(env_var)
    if override:
        if os.path.isabs(override):
            return override
        return os.path.join(_SERVICE_ROOT, override)
    return os.path.join(_SERVICE_ROOT, "logs", default_filename)
