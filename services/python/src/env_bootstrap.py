# -*- coding: utf-8 -*-
"""Runtime env self-loader for the Python service (FIX-503 T2).

The Python service is sometimes started through a path that does not export the
runtime environment (a bare ``python main.py``, a supervised restart, another
process), so ``NINE_ROUTER_BASE_URL`` ends up empty and model discovery falls
back to the public internet. This mirrors the Node ``apps/api/src/loadEnv.ts``
pattern: read ``.env.runtime`` and fill ONLY the keys that are missing or blank —
an explicit process env always wins.

Rules:
    - file missing / unreadable  -> no-op (never raise; startup must survive).
    - existing non-empty env var -> never overridden.
    - existing empty/blank env   -> filled.
    - values are parsed from a simple ``KEY=VALUE`` format; ``#`` full-line
      comments and blank lines are ignored; single/double quoted values are
      unquoted. Values are NEVER logged — only the count of loaded keys.

Import and call this BEFORE anything reads the environment (config/settings).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# Fallback when the repo root cannot be derived from ``__file__``.
_FALLBACK_PATH = "C:/xampp/htdocs/project-ea-bot/.env.runtime"


def _default_path() -> str:
    """Return the default ``.env.runtime`` path (repo root, derived from __file__).

    ``__file__`` lives at ``<repo>/services/python/src/env_bootstrap.py``; the
    repo root is three parents up. Falls back to the absolute XAMPP path when
    the derivation or the file is unavailable.
    """
    try:
        repo_root = Path(__file__).resolve().parents[3]
        candidate = repo_root / ".env.runtime"
        if candidate.exists():
            return str(candidate)
    except Exception:  # noqa: BLE001 - path derivation must never crash startup
        pass
    return _FALLBACK_PATH


def _parse_value(raw: str) -> str:
    """Strip surrounding single/double quotes; leave other values verbatim."""
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def _parse_file(text: str) -> list[tuple[str, str]]:
    """Parse ``.env`` text into an ordered list of ``(key, value)`` pairs."""
    pairs: list[tuple[str, str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[len("export ") :].lstrip()
        if "=" not in stripped:
            continue
        key, _, raw_value = stripped.partition("=")
        key = key.strip()
        if not key:
            continue
        pairs.append((key, _parse_value(raw_value)))
    return pairs


def load_runtime_env(path: str | None = None) -> int:
    """Load ``.env.runtime`` into ``os.environ``, filling only empty keys.

    Args:
        path: explicit file path; ``None`` uses the default repo-root location.

    Returns:
        Number of keys actually loaded (i.e. keys that were missing or blank).
        Returns ``0`` when the file is absent or nothing needed filling.
    """
    target = path if path is not None else _default_path()
    try:
        file = Path(target)
        if not file.is_file():
            return 0
        text = file.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001 - a bad runtime file must never crash startup
        logger.warning("Could not read runtime env file: %s", target)
        return 0

    loaded = 0
    for key, value in _parse_file(text):
        # Fill only when the variable is absent or blank; explicit env wins.
        if os.environ.get(key):
            continue
        os.environ[key] = value
        loaded += 1

    # Never log values — count only.
    logger.info("Loaded %d runtime env key(s) from %s", loaded, target)
    return loaded
