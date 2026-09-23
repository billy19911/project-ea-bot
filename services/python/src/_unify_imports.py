# -*- coding: utf-8 -*-
"""Unify the dual import paths (``<name>`` and ``src.<name>``) onto ONE module.

Why this exists
---------------
``src/`` sits on ``sys.path`` both in production (editable install) and in the
test suite (``tests/conftest.py``), so ``import mt5.terminals`` and
``import src.mt5.terminals`` both succeed — but Python treats them as
DIFFERENT modules, duplicating every package's module-level state.

Concrete failure this fixes: the dashboard armed execution on
``src.mt5.terminals`` while the execution engine consulted ``mt5.terminals``
(a second, always-unarmed copy) and kept refusing real orders with
``EXECUTION NOT ARMED`` — an armed demo terminal could never trade.

Fix: a meta-path finder, installed from ``src/__init__.py``, keeps ONE module
object per source file. Whichever spelling is imported first loads the file;
the other spelling is aliased onto that same module object.

Scope and safety
----------------
- The finder never changes WHICH file an import resolves to: a bare name is
  only intercepted when ``PathFinder`` already resolves it to the same file
  under ``src/`` (``os.path.samefile``). Stdlib and third-party imports pass
  through untouched, and a same-named package elsewhere on ``sys.path`` can
  never be hijacked.
- Fail-safe: any doubt → no interception, normal import.
"""

from __future__ import annotations

import importlib
import importlib.machinery
import logging
import os
import sys

logger = logging.getLogger(__name__)

_PREFIX = "src."
_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
_installed = False
_resolved_cache: dict[str, bool] = {}


class _AliasLoader:
    """Load ``<name>`` as the module object of its canonical twin."""

    def __init__(self, canonical: str) -> None:
        self._canonical = canonical
        self._orig_spec = None
        self._orig_loader = None

    def create_module(self, spec):
        """Return the already-loaded canonical module object."""
        module = importlib.import_module(self._canonical)
        self._orig_spec = getattr(module, "__spec__", None)
        self._orig_loader = getattr(module, "__loader__", None)
        return module

    def exec_module(self, module) -> None:
        """Restore canonical metadata (importlib overwrote it with the alias spec)."""
        if self._orig_spec is not None:
            module.__spec__ = self._orig_spec
        if self._orig_loader is not None:
            module.__loader__ = self._orig_loader


def _src_entry_paths(name: str) -> tuple[str, ...]:
    """Candidate file paths under ``src/`` for a dotted module name."""
    parts = name.split(".")
    if not parts or not all(part.isidentifier() for part in parts):
        return ()
    base = os.path.join(_SRC_DIR, *parts)
    return (base + ".py", os.path.join(base, "__init__.py"))


def _path_is_src_file(path: str, name: str) -> bool:
    """True when ``path`` is the ``src/`` file for dotted ``name``."""
    if not path:
        return False
    for candidate in _src_entry_paths(name):
        if not os.path.isfile(candidate):
            continue
        try:
            if os.path.samefile(path, candidate):
                return True
        except OSError:
            return False
    return False


def _module_is_from_src(module, name: str) -> bool:
    """True when ``module`` is (or is the namespace of) the ``src/`` entry."""
    filename = getattr(module, "__file__", None)
    if filename:
        return _path_is_src_file(filename, name)
    target_dir = os.path.join(_SRC_DIR, *name.split("."))
    if not os.path.isdir(target_dir):
        return False
    for location in list(getattr(module, "__path__", None) or []):
        try:
            if os.path.samefile(location, target_dir):
                return True
        except OSError:
            continue
    return False


def _bare_top_resolves_to_src(top: str) -> bool:
    """True when ``import <top>`` would already resolve to the file under ``src/``.

    Covers regular packages (``src/<top>/__init__.py``), single-file modules
    (``src/<top>.py``) and namespace packages (``src/<top>/`` without
    ``__init__.py``). Cached: the answer depends only on ``sys.path``.
    """
    cached = _resolved_cache.get(top)
    if cached is not None:
        return cached

    result = False
    try:
        spec = importlib.machinery.PathFinder.find_spec(top, None)
    except (ImportError, ValueError, AttributeError):
        spec = None
    if spec is not None:
        origin = getattr(spec, "origin", None)
        if origin and origin != "namespace":
            result = _path_is_src_file(origin, top)
        else:
            target_dir = os.path.join(_SRC_DIR, top)
            if os.path.isdir(target_dir):
                for location in list(getattr(spec, "submodule_search_locations", None) or []):
                    try:
                        if os.path.samefile(location, target_dir):
                            result = True
                            break
                    except OSError:
                        continue

    _resolved_cache[top] = result
    return result


class _DualImportFinder:
    """Meta-path finder aliasing ``<name>`` and ``src.<name>`` onto one module."""

    _ea_bot_src_alias_finder = True

    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(_PREFIX):
            return self._spec_for_src_spelling(fullname)
        top = fullname.split(".", 1)[0]
        if not top.isidentifier() or top.startswith("_"):
            return None
        return self._spec_for_bare_spelling(fullname)

    @staticmethod
    def _spec_for_src_spelling(fullname: str):
        """``src.<name>`` → the already-loaded bare ``<name>`` module, if any."""
        bare = fullname[len(_PREFIX) :]
        module = sys.modules.get(bare)
        if module is not None and _module_is_from_src(module, bare):
            return importlib.machinery.ModuleSpec(fullname, _AliasLoader(bare))
        return None

    @staticmethod
    def _spec_for_bare_spelling(fullname: str):
        """Bare ``<name>`` → the canonical ``src.<name>`` module."""
        canonical = _PREFIX + fullname
        module = sys.modules.get(canonical)
        if module is not None and _module_is_from_src(module, fullname):
            return importlib.machinery.ModuleSpec(fullname, _AliasLoader(canonical))
        top = fullname.split(".", 1)[0]
        if not _bare_top_resolves_to_src(top):
            return None
        return importlib.machinery.ModuleSpec(fullname, _AliasLoader(canonical))


def install() -> bool:
    """Install the alias finder once per process. Returns True when active."""
    global _installed
    if any(getattr(finder, "_ea_bot_src_alias_finder", False) for finder in sys.meta_path):
        _installed = True
        return True
    try:
        sys.meta_path.insert(0, _DualImportFinder())
        _installed = True
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Dual-import alias finder not installed: %s", exc)
        return False
    return True
