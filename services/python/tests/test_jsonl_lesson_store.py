# -*- coding: utf-8 -*-
"""Tests for the persistent JSONL lesson store (Phase 7).

The store must be API-compatible with ``InMemoryLessonStore`` (the contract
``PostTradeReviewAgent``/``ReviewLead`` already use) while surviving restarts:

* ``add_lesson`` appends one JSON line and keeps the in-memory cache in sync,
* a fresh instance reloads persisted lessons from the same file,
* corrupt lines are skipped (fail-safe) — never crash the loader,
* write failures degrade to cache-only (never break the review path).

No network, no MT5.
"""

from __future__ import annotations

import json

from learning.lesson_store import JsonlLessonStore


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
def test_add_lesson_appends_one_json_line(tmp_path) -> None:
    path = tmp_path / "lessons.jsonl"
    store = JsonlLessonStore(path=str(path))

    store.add_lesson({"trade_id": "T1", "outcome": "win"})

    assert path.exists()
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 1
    assert json.loads(lines[0])["trade_id"] == "T1"


def test_reload_reads_persisted_lessons(tmp_path) -> None:
    path = str(tmp_path / "lessons.jsonl")
    first = JsonlLessonStore(path=path)
    first.add_lesson({"trade_id": "T1", "outcome": "win"})
    first.add_lesson({"trade_id": "T2", "outcome": "loss"})

    reloaded = JsonlLessonStore(path=path)

    assert len(reloaded) == 2
    assert [lesson["trade_id"] for lesson in reloaded.all_lessons()] == ["T1", "T2"]


def test_corrupt_lines_are_skipped(tmp_path) -> None:
    path = tmp_path / "lessons.jsonl"
    path.write_text(
        '{"trade_id": "T1"}\nnot-json-at-all\n{"trade_id": "T2"}\n',
        encoding="utf-8",
    )

    store = JsonlLessonStore(path=str(path))

    assert len(store) == 2
    assert [lesson["trade_id"] for lesson in store.all_lessons()] == ["T1", "T2"]


def test_missing_file_starts_empty(tmp_path) -> None:
    store = JsonlLessonStore(path=str(tmp_path / "does-not-exist.jsonl"))
    assert store.all_lessons() == []
    assert len(store) == 0


# ---------------------------------------------------------------------------
# API compatibility with InMemoryLessonStore
# ---------------------------------------------------------------------------
def test_api_is_compatible_with_inmemory_store(tmp_path) -> None:
    store = JsonlLessonStore(path=str(tmp_path / "lessons.jsonl"))

    store.add_lesson({"trade_id": "T1"})
    assert store.all_lessons() == [{"trade_id": "T1"}]
    assert store.get_lessons() == [{"trade_id": "T1"}]
    assert len(store) == 1

    store.clear()
    assert store.all_lessons() == []
    assert len(store) == 0


def test_add_lesson_copies_input(tmp_path) -> None:
    """Later mutation of the caller's dict must not alias stored state."""
    store = JsonlLessonStore(path=str(tmp_path / "lessons.jsonl"))
    lesson = {"trade_id": "T1"}
    store.add_lesson(lesson)

    lesson["trade_id"] = "MUTATED"

    assert store.all_lessons()[0]["trade_id"] == "T1"


def test_clear_truncates_the_file(tmp_path) -> None:
    path = str(tmp_path / "lessons.jsonl")
    store = JsonlLessonStore(path=path)
    store.add_lesson({"trade_id": "T1"})

    store.clear()

    assert JsonlLessonStore(path=path).all_lessons() == []


# ---------------------------------------------------------------------------
# Fail-safe write
# ---------------------------------------------------------------------------
def test_write_failure_keeps_cache_and_never_raises(tmp_path) -> None:
    """An unwritable path must not break add_lesson (cache still updated)."""
    # A directory path cannot be opened as a file for appending.
    bad_path = tmp_path / "a-directory"
    bad_path.mkdir()

    store = JsonlLessonStore(path=str(bad_path))
    store.add_lesson({"trade_id": "T1"})  # must not raise

    assert len(store) == 1


# ---------------------------------------------------------------------------
# Default path
# ---------------------------------------------------------------------------
def test_default_path_comes_from_env(monkeypatch, tmp_path) -> None:
    target = tmp_path / "custom-lessons.jsonl"
    monkeypatch.setenv("LESSON_STORE_PATH", str(target))

    store = JsonlLessonStore()
    store.add_lesson({"trade_id": "T1"})

    assert target.exists()


def test_default_path_falls_back_to_logs_dir(monkeypatch) -> None:
    monkeypatch.delenv("LESSON_STORE_PATH", raising=False)

    store = JsonlLessonStore()

    assert store.path.replace("\\", "/").endswith("logs/lessons.jsonl")
