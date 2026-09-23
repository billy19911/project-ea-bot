# -*- coding: utf-8 -*-
"""Regression: ``<pkg>`` and ``src.<pkg>`` must share ONE module object.

``src/`` sits on ``sys.path`` both in production (editable install) and in the
test suite (``tests/conftest.py``), so both spellings import successfully — but
Python used to treat them as different modules, duplicating module-level state.

The user-visible bug: the dashboard armed ``src.mt5.terminals`` while the
execution engine consulted ``mt5.terminals`` (a second, always-unarmed copy),
so an armed demo terminal could never trade — every cycle failed with
``EXECUTION NOT ARMED``.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(PY_DIR, "src")


def test_alias_finder_installed() -> None:
    import src  # noqa: F401  (importing the package installs the finder)

    assert any(getattr(f, "_ea_bot_src_alias_finder", False) for f in sys.meta_path)


def test_mt5_packages_are_unified() -> None:
    import mt5
    import mt5.terminals  # noqa: F401
    import src.mt5
    import src.mt5.terminals  # noqa: F401

    assert src.mt5 is mt5
    assert src.mt5.terminals is mt5.terminals


def test_execution_packages_are_unified() -> None:
    import execution.engine
    import src.execution.engine

    assert src.execution.engine is execution.engine


def test_single_file_modules_are_unified() -> None:
    """``src.audit`` and ``audit`` are the same shared audit log singleton."""
    from audit import get_shared_audit_log as from_bare
    from src.audit import get_shared_audit_log as from_src

    assert from_bare is from_src


def test_arm_state_shared_across_spellings(monkeypatch) -> None:
    """The real bug: arm through the ``src.`` spelling, gate reads the bare one."""
    import mt5.terminals as bare
    import src.mt5.terminals as aliased

    assert aliased is bare

    fake_view = {
        "terminals": [
            {"id": "demo-x", "execution_allowed": True, "running": True, "attached": True}
        ]
    }
    monkeypatch.setattr(bare, "list_terminals", lambda: fake_view)
    monkeypatch.setattr(bare, "_selected_id", "demo-x")
    monkeypatch.setattr(bare, "_execution_armed", False)

    assert bare.execution_permitted() is False

    aliased._execution_armed = True  # arm via the dashboard endpoint's spelling
    assert bare.execution_permitted() is True  # the engine's spelling sees it


def test_stdlib_and_third_party_are_untouched() -> None:
    from src._unify_imports import _bare_top_resolves_to_src

    assert _bare_top_resolves_to_src("json") is False
    assert _bare_top_resolves_to_src("pytest") is False
    assert _bare_top_resolves_to_src("mt5") is True
    assert _bare_top_resolves_to_src("execution") is True


def test_private_helper_module_keeps_its_name() -> None:
    import src._unify_imports as mod

    assert mod.__name__ == "src._unify_imports"


@pytest.mark.parametrize(
    "first, second",
    [
        ("src.mt5.terminals", "mt5.terminals"),
        ("mt5.terminals", "src.mt5.terminals"),
        ("src.execution.engine", "execution.engine"),
        ("execution.engine", "src.execution.engine"),
    ],
)
def test_unified_regardless_of_import_order(first: str, second: str) -> None:
    """In a fresh interpreter, both import orders must yield ONE module object."""
    code = (
        "import importlib, sys\n"
        f"sys.path.insert(0, {SRC_DIR!r})\n"
        f"sys.path.insert(0, {PY_DIR!r})\n"
        f"a = importlib.import_module({first!r})\n"
        f"b = importlib.import_module({second!r})\n"
        "assert a is b, (a, b)\n"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=PY_DIR)
    assert proc.returncode == 0, proc.stderr
