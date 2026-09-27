# -*- coding: utf-8 -*-
"""One-off migration: purge test/placeholder records from the lesson stores.

Background:
    Tests that boot the real FastAPI app leaked placeholder lessons
    (``trade_id="T-1"``, ``lesson="s"``, empty ``{}`` records) into the
    operator's production ``services/python/logs/lessons.jsonl`` because the
    store path used to be relative. The store path is now absolute and tests
    are isolated (see ``learning/store_paths.py`` + ``tests/conftest.py``), but
    the historical junk is still on disk. This script removes it.

What counts as junk (all must be true to drop a record):
    * source is ``review_auto_trigger`` (test leaks through that path), AND
    * at least one of:
        - ``trade_id`` starts with ``T-`` (test fixtures: ``T-1``, ``T-LIVE-1``),
        - ``trade_id`` is empty,
        - ``lesson`` is empty, ``"s"`` or ``"{}"``,
        - the whole record is empty / only default keys.

Records with real ticket ids and non-trivial lesson text are kept.

Usage:
    python scripts/clean_lessons.py                 # dry-run (report only)
    python scripts/clean_lessons.py --apply         # rewrite the file
    python scripts/clean_lessons.py --path <file>   # target a specific file
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parent.parent / "services" / "python"
_DEFAULT_LESSON = _SERVICE_ROOT / "logs" / "lessons.jsonl"
_DEFAULT_V2 = _SERVICE_ROOT / "logs" / "learning_engine_v2.jsonl"

_JUNK_LESSON_TEXTS = {"", "s", "{}", "none", "null"}


def _is_junk(record: dict) -> bool:
    """Return True when ``record`` is a leaked test/placeholder lesson."""
    if not isinstance(record, dict) or not record:
        return True

    trade_id = str(record.get("trade_id") or "")
    lesson = str(record.get("lesson") or "").strip().lower()

    # Test fixtures are always identifiable by their trade id (``T-1``,
    # ``T-BRIDGE``, ``T-LIVE-1``) or an empty id. This applies to both the
    # legacy store (``source == "review_auto_trigger"``) and the engine-v2
    # store (which has no ``source`` key). Real MT5 tickets are numeric and are
    # never dropped here.
    if trade_id == "" or trade_id.upper().startswith("T-"):
        return True

    # A record whose ONLY meaningful field is a non-numeric trade id (e.g.
    # ``{"trade_id": "T1"}`` leaked by the store tests) carries no trade data.
    # Real MT5 tickets are digit strings; anything else with no content is junk.
    if not trade_id.replace(".", "", 1).isdigit():
        content_keys = {
            k
            for k, v in record.items()
            if k != "trade_id" and v not in ("", None, {}, [])
        }
        if not content_keys:
            return True

    source = str(record.get("source") or "")
    if source == "review_auto_trigger":
        if lesson in _JUNK_LESSON_TEXTS:
            return True
        # A record where every value is empty/None is junk.
        values = [v for k, v in record.items() if k != "source"]
        if all(v in ("", None, {}, []) for v in values):
            return True

    return False


def _clean_file(path: Path, apply: bool) -> tuple[int, int]:
    """Return (kept, dropped) after filtering ``path`` (writes when apply)."""
    if not path.exists():
        print(f"  [skip] not found: {path}")
        return 0, 0

    kept: list[str] = []
    dropped = 0
    total = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            total += 1
            try:
                record = json.loads(stripped)
            except json.JSONDecodeError:
                dropped += 1
                continue
            if _is_junk(record):
                dropped += 1
            else:
                kept.append(stripped)

    print(f"  {path}")
    print(f"    total={total} kept={len(kept)} dropped={dropped}")

    if apply and dropped:
        backup = path.with_suffix(path.suffix + ".bak")
        shutil.copy2(path, backup)
        with path.open("w", encoding="utf-8") as handle:
            for line in kept:
                handle.write(line + "\n")
        print(f"    applied — backup at {backup}")

    return len(kept), dropped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Purge leaked placeholder lessons.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Rewrite the files (default is dry-run reporting only).",
    )
    parser.add_argument(
        "--path",
        action="append",
        default=None,
        help="Target a specific JSONL file (repeatable). Defaults to both stores.",
    )
    args = parser.parse_args(argv)

    if args.path:
        targets = [Path(p) for p in args.path]
    else:
        # Honour env overrides, else the absolute service-root defaults.
        lesson = Path(os.getenv("LESSON_STORE_PATH") or _DEFAULT_LESSON)
        v2 = Path(os.getenv("ENGINE_V2_STORE_PATH") or _DEFAULT_V2)
        targets = [lesson, v2]

    print(f"clean_lessons.py — {'APPLY' if args.apply else 'DRY-RUN'}")
    total_dropped = 0
    for target in targets:
        _, dropped = _clean_file(target, args.apply)
        total_dropped += dropped

    print(
        f"\nTotal junk records {'removed' if args.apply else 'detected'}: {total_dropped}"
    )
    if not args.apply and total_dropped:
        print("Re-run with --apply to rewrite the files (a .bak is kept).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
