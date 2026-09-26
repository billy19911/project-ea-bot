# -*- coding: utf-8 -*-
"""Tests for the Python runtime env self-loader (FIX-503 T2).

The Python service is sometimes started via a path that does not export the
runtime environment (e.g. a bare ``python main.py``), so ``NINE_ROUTER_BASE_URL``
is empty and discovery hits the public internet. ``env_bootstrap`` mirrors the
Node ``loadEnv.ts`` pattern: read ``.env.runtime`` and fill only the keys that
are missing or blank — an explicit process env always wins.
"""

from __future__ import annotations

from src import env_bootstrap


def _write(tmp_path, content: str) -> str:
    path = tmp_path / ".env.runtime"
    path.write_text(content, encoding="utf-8")
    return str(path)


def test_loads_missing_keys(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("FIX503_KEY_ONE", raising=False)
    monkeypatch.delenv("FIX503_KEY_TWO", raising=False)
    path = _write(
        tmp_path,
        "\n".join(
            [
                "# a comment line",
                "FIX503_KEY_ONE=alpha",
                "",
                "FIX503_KEY_TWO=beta",
            ]
        ),
    )

    loaded = env_bootstrap.load_runtime_env(path)

    assert loaded == 2
    import os

    assert os.environ["FIX503_KEY_ONE"] == "alpha"
    assert os.environ["FIX503_KEY_TWO"] == "beta"


def test_does_not_override_existing(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FIX503_EXPLICIT", "from-shell")
    path = _write(tmp_path, "FIX503_EXPLICIT=from-file\n")

    loaded = env_bootstrap.load_runtime_env(path)

    import os

    assert os.environ["FIX503_EXPLICIT"] == "from-shell"
    assert loaded == 0


def test_blank_existing_is_filled(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FIX503_BLANK", "")
    path = _write(tmp_path, "FIX503_BLANK=filled\n")

    loaded = env_bootstrap.load_runtime_env(path)

    import os

    assert os.environ["FIX503_BLANK"] == "filled"
    assert loaded == 1


def test_missing_file_noop(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("FIX503_ABSENT", raising=False)

    loaded = env_bootstrap.load_runtime_env(str(tmp_path / "does-not-exist.env"))

    assert loaded == 0


def test_quotes_and_comments(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("FIX503_DQ", raising=False)
    monkeypatch.delenv("FIX503_SQ", raising=False)
    monkeypatch.delenv("FIX503_HASH", raising=False)
    path = _write(
        tmp_path,
        "\n".join(
            [
                "# full-line comment",
                'FIX503_DQ="double quoted value"',
                "FIX503_SQ='single quoted value'",
                "FIX503_HASH=value # inline comment is kept for unquoted? no -> treat raw",
                "   # indented comment",
            ]
        ),
    )

    loaded = env_bootstrap.load_runtime_env(path)

    import os

    assert loaded == 3
    assert os.environ["FIX503_DQ"] == "double quoted value"
    assert os.environ["FIX503_SQ"] == "single quoted value"
    # Unquoted values are taken verbatim (trailing whitespace trimmed).
    assert os.environ["FIX503_HASH"].startswith("value")
